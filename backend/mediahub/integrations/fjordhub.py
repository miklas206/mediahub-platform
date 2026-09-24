"""Read-only FjordHub Access Token adapter; current resources API and legacy catalog.

Contract verified against qlerup/fjordhub app.py and README, September 2026.
Never probes session-only administrative endpoints or controls FjordHub containers.
"""

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx

from mediahub.integrations.provider import IntegrationSnapshot


class ProviderFailure(Exception):
    def __init__(self, status, retry_after=None):
        super().__init__(status)  # Never include response bodies, URLs or Access Tokens.
        self.status, self.retry_after = status, retry_after


def validate_url(value: str, allow_http: bool = False):
    parsed = urlsplit(value)
    try:
        address = ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise ValueError("Use an explicit private IP for this initial integration") from None
    if (
        parsed.scheme not in ({"https", "http"} if allow_http else {"https"})
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port == 0
    ):
        raise ValueError("Invalid integration origin or HTTP not explicitly enabled")
    return value.rstrip("/")


def retry_seconds(value):
    try:
        seconds = int(value)
    except (ValueError, TypeError):
        try:
            seconds = int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            seconds = 60
    return max(1, min(seconds, 86400))


class FjordHubClient:
    """Only GET requests, fixed paths and bounded typed data. Test transport is injected."""

    def __init__(self, base_url, access_token, *, allow_http=False, transport=None):
        self.base_url = validate_url(base_url, allow_http)
        self._access_token = access_token
        self._transport = transport
        self._current_endpoint = None

    async def _get(self, client, path, params=None):
        self._current_endpoint = path
        async with client.stream("GET", path, params=params) as response:
            if response.status_code == 401:
                raise ProviderFailure("authentication_failed")
            if response.status_code == 403:
                raise ProviderFailure("lan_access_denied")
            if response.status_code == 429:
                raise ProviderFailure(
                    "rate_limited", retry_seconds(response.headers.get("Retry-After"))
                )
            if response.status_code in {404, 406, 426}:
                raise ProviderFailure("api_incompatible")
            if response.status_code != 200:
                raise ProviderFailure("offline")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    raise ProviderFailure("invalid_response")
        import json

        try:
            body = json.loads(data)
            if not isinstance(body, dict):
                raise ValueError()
            return body
        except ValueError:
            raise ProviderFailure("invalid_response") from None

    def text(self, value, limit=200):
        if not isinstance(value, str):
            return None
        # Defend against reflection of the bearer Access Token into metadata.
        return (
            value.replace(self._access_token, "[redacted]")[:limit]
            if self._access_token
            else value[:limit]
        )

    def rows(self, items, fields):
        if not isinstance(items, list):
            raise ProviderFailure("invalid_response")
        rows = []
        for item in items[:200]:
            if not isinstance(item, dict):
                continue
            row = {}
            for key in fields:
                value = item.get(key)
                if isinstance(value, str):
                    row[key] = self.text(value, 500)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    if value >= 0 and value < 1e30:
                        row[key] = value
            rows.append(row)
        return rows

    async def test(self):
        return await self.sync(summary_only=True)

    def resource_snapshot(self, body):
        import math

        if (
            body.get("ok") is not True
            or not isinstance(body.get("apps"), list)
            or not isinstance(body.get("hub"), dict)
            or not isinstance(body.get("capacity"), dict)
        ):
            raise ProviderFailure("invalid_response")
        fields = [
            "id",
            "name",
            "container_count",
            "running_count",
            "cpu_percent",
            "cpu_capacity_percent",
            "memory_usage",
            "memory_percent",
            "net_rx",
            "net_tx",
            "block_read",
            "block_write",
        ]
        apps = self.rows(body["apps"], fields)
        metrics = {}
        for source, target in {
            "cpu_capacity_percent": "cpuPercent",
            "memory_usage": "memoryBytes",
            "memory_percent": "memoryPercent",
            "net_rx": "networkReceivedBytes",
            "net_tx": "networkSentBytes",
            "block_read": "diskReadBytes",
            "block_write": "diskWrittenBytes",
            "container_count": "containers",
            "running_count": "runningContainers",
        }.items():
            value = body["hub"].get(source)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and 0 <= value < 1e30
            ):
                metrics[target] = value
        return IntegrationSnapshot(
            status="online",
            api_version="1",
            capabilities=["docker.resources.read"],
            apps=apps,
            metrics=metrics,
            warnings=[
                "Read-only Docker resources; not Proxmox/LXC host metrics.",
                "Network and disk I/O values are cumulative byte counters, not transfer speeds.",
                "This token does not grant file access, logs, configuration or container control.",
            ],
        )

    async def sync(self, *, cursor=None, summary_only=False):
        snapshot = IntegrationSnapshot(status="offline")
        try:
            async with asyncio.timeout(20):
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    headers={"Authorization": "Bearer " + self._access_token},
                    timeout=5,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    try:
                        body = await self._get(client, "/api/integrations/v1/resources")
                    except ProviderFailure as error:
                        if error.status != "api_incompatible":
                            raise
                        # Older installed versions exposed only this read-only
                        # catalog route. Never fall back on auth or permission errors.
                        body = await self._get(client, "/api/integrations/v1/apps")
                    else:
                        return self.resource_snapshot(body)
                    items = body.get("items")
                    if not isinstance(items, list) or any(
                        not isinstance(item, dict)
                        or not isinstance(item.get("id"), str)
                        or not isinstance(item.get("name"), str)
                        or not isinstance(item.get("description"), str)
                        for item in items
                    ):
                        raise ProviderFailure("invalid_response")
                    snapshot.api_version = "1"
                    snapshot.capabilities = ["app_catalog.read"]
                    # Capability is inferred from the verified route, not a claimed
                    # upstream scopes response. This API has no scope negotiation.
                    snapshot.apps = self.rows(items, ["id", "name", "description"])
                    snapshot.status = "online"
                    snapshot.warnings = [
                        "Installable app catalog only; not the list of installed or running apps.",
                        "Storage, CPU, RAM, uptime, app health, events and software version are not available through this Access Token API.",
                    ]
                    if len(items) > 200:
                        snapshot.warnings.append(
                            "Catalog display limited to the first 200 entries."
                        )
        except ProviderFailure as error:
            snapshot.status, snapshot.retry_after = error.status, error.retry_after
        except (httpx.TimeoutException, TimeoutError):
            snapshot.status = "timeout"
        except httpx.HTTPError:
            snapshot.status = "offline"
        except (TypeError, ValueError):
            snapshot.status = "invalid_response"
        if snapshot.status not in {"online", "degraded"}:
            snapshot.failed_endpoint = self._current_endpoint
        return snapshot


class FjordHubIntegrationProvider(FjordHubClient):
    """Only this adapter knows FjordHub's version-dependent read-only contract."""

    async def test_connection(self):
        return await self.test()

    async def get_health(self):
        return (await self.test()).status

    async def get_info(self):
        result = await self.test()
        return {"version": result.version, "apiVersion": result.api_version}

    async def get_capabilities(self):
        return (await self.test()).capabilities

    async def get_apps(self):
        return (await self.sync()).apps

    async def get_storage(self):
        return None  # Not available in this token API; no speculative requests.

    async def get_metrics(self):
        return (await self.sync()).metrics or None

    async def get_events(self, cursor=None):
        return None
