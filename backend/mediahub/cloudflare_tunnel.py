"""Read-only Cloudflare Tunnel health and end-to-end route probes."""

import asyncio
import time
from urllib.parse import urlsplit

import httpx


class CloudflareTunnelMonitor:
    def __init__(self, config, *, cache_seconds=10):
        self.status_url = config.cloudflared_status_url
        self.probe_urls = config.cloudflared_probe_urls
        self.cache_seconds = cache_seconds
        self.lock = asyncio.Lock()
        self.cached = None
        self.cached_at = 0.0

    async def _source(self, client):
        if not self.status_url:
            return None
        response = await client.get(self.status_url, headers={"Accept": "application/json"})
        response.raise_for_status()
        if len(response.content) > 64 * 1024:
            raise ValueError("Cloudflared status response is too large")
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
        if not self.status_url:
            return {
                "configured": False,
                "status": "not_configured",
                "checkedAt": time.time(),
                "metricsReachable": False,
                "connections": 0,
                "routes": [],
                "message": "Cloudflared monitoring is not configured",
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
            if not connected:
                health, message = "critical", "Cloudflare Tunnel is not connected"
            elif failed_routes:
                health, message = (
                    "degraded",
                    f"Tunnel connected, but {failed_routes} public route(s) cannot reach their origin",
                )
            elif not routes:
                health, message = "degraded", "Tunnel connected; no public route probe is configured"
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
            }
            self.cached, self.cached_at = result, time.monotonic()
            return result
