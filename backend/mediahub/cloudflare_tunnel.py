"""Read-only Cloudflare Tunnel health and end-to-end route probes."""

import asyncio
import re
import time
from urllib.parse import quote, urlsplit

import httpx
from packaging.version import InvalidVersion, Version

from mediahub.config import Config
from mediahub.errors import DomainError

LATEST_RELEASE_URL = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"


class CloudflareTunnelMonitor:
    def __init__(self, config, *, cache_seconds=10, release_cache_seconds=600):
        self.status_url = config.cloudflared_status_url
        self.probe_urls = config.cloudflared_probe_urls
        self.setup_mode = "existing-tunnel"
        self.tunnel_name = None
        self.origin_url = None
        self.cache_seconds = cache_seconds
        self.lock = asyncio.Lock()
        self.cached = None
        self.cached_at = 0.0
        self.release_cache_seconds = release_cache_seconds
        self.release_lock = asyncio.Lock()
        self.release_cached = None
        self.release_cached_at = 0.0

    @staticmethod
    def _public_routes(value):
        entries = value if isinstance(value, list) else re.split(r"[\s,;]+", str(value or ""))
        urls = []
        for entry in entries:
            entry = str(entry).strip()
            if entry:
                urls.append(entry if "://" in entry else "https://" + entry)
        return Config.valid_cloudflared_probe_urls(urls)

    def configure(self, configuration):
        """Apply catalog-backed setup values without requiring a Core restart."""

        values = dict((configuration or {}).get("values") or configuration or {})
        if not values:
            return self.configuration()
        if "status_url" in values:
            raw_status = str(values.get("status_url") or "").strip()
            self.status_url = Config.valid_cloudflared_status_url(raw_status or None)
        if "public_hostnames" in values:
            self.probe_urls = self._public_routes(values.get("public_hostnames"))
        elif "probe_url" in values:  # migrate the old preview field in place
            self.probe_urls = self._public_routes(values.get("probe_url"))
        self.setup_mode = str(values.get("setup_mode") or self.setup_mode)[:40]
        self.tunnel_name = str(values.get("tunnel_name") or "").strip()[:100] or None
        raw_origin = str(values.get("origin_url") or "").strip()[:500]
        self.origin_url = Config.validate_url(raw_origin) if raw_origin else None
        self.cached = None
        self.cached_at = 0.0
        return self.configuration()

    def configuration(self):
        return {
            "setupMode": self.setup_mode,
            "tunnelName": self.tunnel_name,
            "originUrl": self.origin_url,
            "statusUrlConfigured": bool(self.status_url),
            "routeCount": len(self.probe_urls),
        }

    @staticmethod
    def _metric_values(text, name):
        values = []
        prefix = name + "{"
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not (line.startswith(prefix) or line.startswith(name + " ")):
                continue
            try:
                values.append(float(line.rsplit(None, 1)[1]))
            except (IndexError, ValueError):
                continue
        return values

    @classmethod
    def _prometheus_source(cls, text):
        connections = sum(cls._metric_values(text, "cloudflared_tunnel_ha_connections"))
        requests = sum(cls._metric_values(text, "cloudflared_tunnel_total_requests"))
        errors = sum(cls._metric_values(text, "cloudflared_tunnel_request_errors"))
        build_match = re.search(
            r"^(?:cloudflared_)?build_info\{(?P<labels>[^\n}]*)\}\s+[0-9.eE+-]+$",
            text,
            re.MULTILINE,
        )
        version_match = (
            re.search(
                r'(?:^|,)version="([^"\n]{1,80})"(?:,|$)',
                build_match.group("labels"),
            )
            if build_match
            else None
        )
        if "cloudflared_tunnel_ha_connections" not in text and not build_match:
            raise ValueError("Cloudflared Prometheus metrics were not found")
        return {
            "metricsReachable": True,
            "connections": max(0, min(int(connections), 1000)),
            "totalRequests": max(0, int(requests)),
            "requestErrors": max(0, int(errors)),
            "version": version_match.group(1) if version_match else None,
        }

    async def _source(self, client):
        if not self.status_url:
            return None
        response = await client.get(self.status_url, headers={"Accept": "application/json"})
        response.raise_for_status()
        if len(response.content) > 512 * 1024:
            raise ValueError("Cloudflared status response is too large")
        if self.status_url.endswith("/metrics") or not response.content.lstrip().startswith(b"{"):
            return self._prometheus_source(response.text)
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Invalid Cloudflared status response")
        return {
            "metricsReachable": bool(body.get("metricsReachable")),
            "connections": max(0, min(int(body.get("connections", 0)), 1000)),
            "totalRequests": max(0, int(body.get("totalRequests", 0))),
            "requestErrors": max(0, int(body.get("requestErrors", 0))),
            "version": str(body.get("version") or "")[:80] or None,
        }

    @staticmethod
    async def _probe(client, url):
        started = time.monotonic()
        try:
            async with client.stream(
                "GET", url, headers={"User-Agent": "MediaHub-Tunnel-Monitor/1"}
            ) as response:
                code = response.status_code
            reachable = code < 500
            return {
                "url": url,
                "hostname": urlsplit(url).hostname,
                "reachable": reachable,
                "statusCode": code,
                "latencyMs": round((time.monotonic() - started) * 1000),
                "message": "Route reached Cloudflare/origin" if reachable else "Origin unavailable",
            }
        except (httpx.HTTPError, ValueError):
            return {
                "url": url,
                "hostname": urlsplit(url).hostname,
                "reachable": False,
                "statusCode": None,
                "latencyMs": round((time.monotonic() - started) * 1000),
                "message": "Route could not be reached",
            }

    async def status(self, *, force=False):
        if not self.status_url and not self.probe_urls:
            return {
                "configured": False,
                "status": "not_configured",
                "checkedAt": time.time(),
                "metricsReachable": False,
                "connections": 0,
                "routes": [],
                "message": "Cloudflared monitoring is not configured",
                **self.configuration(),
            }
        async with self.lock:
            if not force and self.cached and time.monotonic() - self.cached_at < self.cache_seconds:
                return {**self.cached, "cached": True}
            timeout = httpx.Timeout(4, connect=2)
            limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
            async with httpx.AsyncClient(
                timeout=timeout, limits=limits, follow_redirects=False
            ) as client:
                try:
                    source = await self._source(client)
                except (httpx.HTTPError, ValueError, TypeError, OverflowError):
                    source = None
                routes = await asyncio.gather(
                    *(self._probe(client, url) for url in self.probe_urls)
                )
            connected = bool(source and source["metricsReachable"] and source["connections"] > 0)
            failed_routes = sum(not route["reachable"] for route in routes)
            reachable_routes = sum(route["reachable"] for route in routes)
            if not self.status_url and reachable_routes and not failed_routes:
                health, message = (
                    "degraded",
                    "Public routes are reachable; connector metrics are not configured",
                )
            elif not connected and reachable_routes:
                health, message = (
                    "degraded",
                    "Public routes are reachable; local connector metrics are unavailable",
                )
            elif not connected:
                health, message = "critical", "Cloudflare Tunnel is not connected"
            elif failed_routes:
                health, message = (
                    "degraded",
                    f"Tunnel connected, but {failed_routes} public route(s) cannot reach their origin",
                )
            elif not routes:
                health, message = (
                    "degraded",
                    "Tunnel connected; no public route probe is configured",
                )
            else:
                health, message = "healthy", "Tunnel and configured public routes are reachable"
            result = {
                "configured": True,
                "status": health,
                "checkedAt": time.time(),
                "cached": False,
                "metricsReachable": bool(source and source["metricsReachable"]),
                "connections": source["connections"] if source else 0,
                "totalRequests": source["totalRequests"] if source else 0,
                "requestErrors": source["requestErrors"] if source else 0,
                "version": source["version"] if source else None,
                "routes": routes,
                "message": message,
                **self.configuration(),
            }
            self.cached, self.cached_at = result, time.monotonic()
            return result

    async def _latest_release(self, *, force=False):
        async with self.release_lock:
            if (
                not force
                and self.release_cached
                and time.monotonic() - self.release_cached_at < self.release_cache_seconds
            ):
                return {**self.release_cached, "cached": True}
            try:
                timeout = httpx.Timeout(8, connect=4)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    response = await client.get(
                        LATEST_RELEASE_URL,
                        headers={
                            "Accept": "application/vnd.github+json",
                            "User-Agent": "MediaHub-cloudflared-update-check/1",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                    )
                response.raise_for_status()
                if len(response.content) > 64 * 1024:
                    raise ValueError("Release response is too large")
                body = response.json()
                if (
                    not isinstance(body, dict)
                    or body.get("draft") is True
                    or body.get("prerelease") is True
                ):
                    raise ValueError("Latest stable release is unavailable")
                raw_tag = str(body.get("tag_name") or "")[:80]
                normalized = raw_tag.removeprefix("v")
                latest = Version(normalized)
            except (httpx.HTTPError, ValueError, TypeError, InvalidVersion) as error:
                raise DomainError(
                    "update_check_unavailable",
                    "The official cloudflared release could not be verified",
                    503,
                ) from error
            result = {
                "version": str(latest),
                "releaseUrl": (
                    "https://github.com/cloudflare/cloudflared/releases/tag/"
                    + quote(raw_tag, safe="")
                ),
                "checkedAt": time.time(),
                "cached": False,
            }
            self.release_cached, self.release_cached_at = result, time.monotonic()
            return result

    async def update_check(self, *, force=False):
        """Compare the observed binary with Cloudflare's latest stable release.

        This is intentionally read-only. Installation and restart behavior depends
        on how cloudflared was installed and therefore remains an operator action.
        """

        tunnel, release = await asyncio.gather(self.status(), self._latest_release(force=force))
        installed_raw = tunnel.get("version")
        installed = None
        if installed_raw:
            try:
                installed = Version(str(installed_raw).removeprefix("v"))
            except InvalidVersion:
                installed = None
        latest = Version(release["version"])
        update_available = bool(installed is not None and installed < latest)
        if installed is None:
            message = (
                f"Latest stable cloudflared release is {latest}; "
                "the installed version is not currently observable"
            )
        elif update_available:
            message = (
                f"cloudflared {latest} is available; installation remains manual "
                "to preserve the active tunnel"
            )
        else:
            message = f"cloudflared {installed} is up to date"
        return {
            "supported": True,
            "installSupported": False,
            "installedVersion": str(installed) if installed is not None else None,
            "latestVersion": str(latest),
            "releaseVersions": [str(latest)] if update_available else [],
            "updateAvailable": update_available,
            "releaseUrl": release["releaseUrl"],
            "checkedAt": release["checkedAt"],
            "cached": release.get("cached", False),
            "message": message,
        }
