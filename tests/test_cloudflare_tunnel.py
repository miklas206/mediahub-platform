import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from mediahub.apps.cloudflared import CloudflaredAppAdapter, register_cloudflared_app
from mediahub.cloudflare_tunnel import CloudflareTunnelMonitor
from mediahub.errors import DomainError


def config(probes=None):
    return SimpleNamespace(
        cloudflared_status_url="http://192.168.50.10:20242/status",
        cloudflared_probe_urls=(["https://media.example.test"] if probes is None else probes),
    )


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_connected_tunnel_and_route(monkeypatch):
    async def handler(request):
        if request.url.host == "192.168.50.10":
            return httpx.Response(
                200,
                json={
                    "metricsReachable": True,
                    "connections": 4,
                    "totalRequests": 20,
                    "requestErrors": 1,
                    "version": "2026.9.0",
                },
            )
        return httpx.Response(302, headers={"location": "/login"})

    mock_client(monkeypatch, handler)
    result = asyncio.run(CloudflareTunnelMonitor(config()).status())
    assert result["status"] == "healthy"
    assert result["connections"] == 4
    assert result["routes"][0]["reachable"] is True


def test_prometheus_metrics_are_connector_sessions_not_tunnel_count(monkeypatch):
    prometheus = """\
# HELP cloudflared_tunnel_ha_connections Number of active HA connections
cloudflared_tunnel_ha_connections 4
cloudflared_tunnel_total_requests 42
cloudflared_tunnel_request_errors 2
build_info{goversion="go1.24",type="cloudflared",version="2026.9.3"} 1
"""

    async def handler(request):
        if request.url.path == "/metrics":
            return httpx.Response(200, text=prometheus)
        return httpx.Response(302, headers={"location": "/login"})

    cfg = config()
    cfg.cloudflared_status_url = "http://192.168.50.10:20241/metrics"
    mock_client(monkeypatch, handler)
    result = asyncio.run(CloudflareTunnelMonitor(cfg).status())
    assert result["status"] == "healthy"
    assert result["connections"] == 4
    assert result["totalRequests"] == 42
    assert result["requestErrors"] == 2
    assert result["version"] == "2026.9.3"


def test_prometheus_parser_accepts_cloudflared_prefixed_build_info():
    source = CloudflareTunnelMonitor._prometheus_source(
        "cloudflared_tunnel_ha_connections 2\n"
        'cloudflared_build_info{version="2026.9.4",goversion="go1.24"} 1\n'
    )
    assert source["connections"] == 2
    assert source["version"] == "2026.9.4"


def test_assisted_configuration_applies_routes_without_account_token(monkeypatch):
    async def handler(request):
        return httpx.Response(302, headers={"location": "/login"})

    cfg = config(probes=[])
    cfg.cloudflared_status_url = None
    monitor = CloudflareTunnelMonitor(cfg)
    applied = monitor.configure(
        {
            "values": {
                "setup_mode": "existing-tunnel",
                "tunnel_name": "Home tunnel",
                "public_hostnames": "media.example.test, home.example.test",
                "origin_url": "https://192.168.1.50:18765",
                "status_url": "",
            }
        }
    )
    assert applied == {
        "setupMode": "existing-tunnel",
        "tunnelName": "Home tunnel",
        "originUrl": "https://192.168.1.50:18765",
        "statusUrlConfigured": False,
        "routeCount": 2,
        "tunnels": [
            {
                "id": "legacy",
                "name": "Home tunnel",
                "setupMode": "existing-tunnel",
                "originUrl": "https://192.168.1.50:18765",
                "statusUrlConfigured": False,
                "routeCount": 2,
                "routes": [
                    "https://media.example.test",
                    "https://home.example.test",
                ],
            }
        ],
    }
    mock_client(monkeypatch, handler)
    result = asyncio.run(monitor.status())
    assert result["status"] == "degraded"
    assert result["routeCount"] == 2
    assert result["connections"] == 0


def test_multiple_tunnel_profiles_are_saved_and_aggregated():
    cfg = config(probes=[])
    cfg.cloudflared_status_url = None
    monitor = CloudflareTunnelMonitor(cfg)
    applied = monitor.configure(
        {
            "values": {
                "tunnel_profiles": json.dumps(
                    [
                        {
                            "id": "home",
                            "name": "Home tunnel",
                            "setupMode": "existing-tunnel",
                            "publicHostnames": ["media.example.test"],
                            "originUrl": "https://192.168.1.50:18765",
                            "statusUrl": "",
                        },
                        {
                            "id": "parents",
                            "name": "Parents tunnel",
                            "setupMode": "existing-tunnel",
                            "publicHostnames": ["home.example.test"],
                            "originUrl": "https://192.168.1.60:8443",
                            "statusUrl": "http://192.168.1.60:20241/metrics",
                        },
                    ]
                )
            }
        }
    )
    assert applied["routeCount"] == 2
    assert [item["name"] for item in applied["tunnels"]] == [
        "Home tunnel",
        "Parents tunnel",
    ]
    assert monitor.probe_urls == [
        "https://media.example.test",
        "https://home.example.test",
    ]
    assert monitor.status_url == "http://192.168.1.60:20241/metrics"


def test_connected_tunnel_with_failed_origin_is_degraded(monkeypatch):
    async def handler(request):
        if request.url.host == "192.168.50.10":
            return httpx.Response(200, json={"metricsReachable": True, "connections": 4})
        return httpx.Response(502)

    mock_client(monkeypatch, handler)
    result = asyncio.run(CloudflareTunnelMonitor(config()).status())
    assert result["status"] == "degraded"
    assert result["routes"][0]["reachable"] is False


def test_unreachable_status_is_critical(monkeypatch):
    async def handler(request):
        raise httpx.ConnectError("offline", request=request)

    mock_client(monkeypatch, handler)
    result = asyncio.run(CloudflareTunnelMonitor(config(probes=[])).status())
    assert result["status"] == "critical"
    assert result["connections"] == 0


def test_official_release_check_reports_available_update(monkeypatch):
    async def handler(request):
        if request.url.host == "192.168.50.10":
            return httpx.Response(
                200,
                json={
                    "metricsReachable": True,
                    "connections": 4,
                    "version": "2026.8.3",
                },
            )
        assert str(request.url) == (
            "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
        )
        return httpx.Response(
            200,
            json={
                "tag_name": "2026.9.1",
                "draft": False,
                "prerelease": False,
                "html_url": "https://untrusted.example/ignored",
            },
        )

    mock_client(monkeypatch, handler)
    result = asyncio.run(CloudflareTunnelMonitor(config(probes=[])).update_check())
    assert result["installedVersion"] == "2026.8.3"
    assert result["latestVersion"] == "2026.9.1"
    assert result["releaseVersions"] == ["2026.9.1"]
    assert result["updateAvailable"] is True
    assert result["installSupported"] is False
    assert result["releaseUrl"] == (
        "https://github.com/cloudflare/cloudflared/releases/tag/2026.9.1"
    )


def test_release_check_rejects_unverifiable_metadata(monkeypatch):
    async def handler(request):
        if request.url.host == "192.168.50.10":
            return httpx.Response(
                200,
                json={"metricsReachable": True, "connections": 4, "version": "2026.9.0"},
            )
        return httpx.Response(
            200,
            json={"tag_name": "not a release", "draft": False, "prerelease": False},
        )

    mock_client(monkeypatch, handler)
    with pytest.raises(DomainError) as failure:
        asyncio.run(CloudflareTunnelMonitor(config(probes=[])).update_check())
    assert failure.value.code == "update_check_unavailable"


def test_configured_monitor_is_registered_as_read_only_app(logged_in, monkeypatch):
    async def handler(request):
        if request.url.host == "192.168.50.10":
            return httpx.Response(
                200,
                json={
                    "metricsReachable": True,
                    "connections": 4,
                    "version": "2026.9.1",
                },
            )
        return httpx.Response(204)

    mock_client(monkeypatch, handler)
    svc = logged_in.app.state.services
    svc.config.cloudflared_status_url = "http://192.168.50.10:20242/status"
    svc.config.cloudflared_probe_urls = ["https://media.example.test"]
    svc.cloudflare_tunnel = CloudflareTunnelMonitor(svc.config)
    register_cloudflared_app(svc)

    apps = logged_in.get("/api/apps").json()["data"]
    app = next(item for item in apps if item["packageId"] == "org.mediahub.cloudflared")
    assert app["detailPath"] == f"/apps/{app['id']}"
    assert app["health"]["status"] == "healthy"

    runtime = logged_in.get(f"/api/apps/{app['id']}/runtime").json()["data"]
    assert runtime["view"] == "cloudflare"
    assert runtime["report"]["cloudflare"]["version"] == "2026.9.1"

    action = logged_in.post(f"/api/apps/{app['id']}/actions/restart")
    assert action.status_code == 400
    assert action.json()["error"]["code"] == "read_only_app"


@pytest.mark.parametrize(
    "status,headers,code",
    [
        (403, {"x-ratelimit-remaining": "0"}, "update_source_rate_limited"),
        (502, {}, "update_source_http_error"),
    ],
)
def test_release_http_failure_has_actionable_reason(monkeypatch, status, headers, code):
    async def handler(request):
        return httpx.Response(status, headers=headers, text="private upstream body")

    mock_client(monkeypatch, handler)
    with pytest.raises(DomainError) as failure:
        asyncio.run(CloudflareTunnelMonitor(config(probes=[]))._latest_release())
    assert failure.value.code == code
    assert "private upstream body" not in failure.value.message


def test_app_checks_share_release_cache_for_fifteen_minutes(monkeypatch):
    requests = []

    async def handler(request):
        if request.url.host == "api.github.com":
            requests.append(request)
            return httpx.Response(200, json={"tag_name": "2026.9.1"})
        return httpx.Response(
            200, json={"metricsReachable": True, "connections": 4, "version": "2026.9.0"}
        )

    mock_client(monkeypatch, handler)
    monitor = CloudflareTunnelMonitor(config(probes=[]))
    adapter = CloudflaredAppAdapter(monitor, None, "cloudflare")

    async def check():
        await adapter.updateCheck()
        monitor.release_cached_at -= 899
        await adapter.updateCheck()
        assert len(requests) == 1
        monitor.release_cached_at -= 2
        await adapter.updateCheck()
        assert len(requests) == 2

    asyncio.run(check())


@pytest.mark.parametrize(
    "headers",
    [
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 3600)},
        {"retry-after": "3600"},
    ],
)
def test_rate_limit_pauses_even_forced_checks_until_retry_then_recovers(monkeypatch, headers):
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers=headers)
        return httpx.Response(200, json={"tag_name": "2026.9.1"})

    mock_client(monkeypatch, handler)
    monitor = CloudflareTunnelMonitor(config(probes=[]))

    async def check():
        for force in (False, True, False):
            with pytest.raises(DomainError) as failure:
                await monitor._latest_release(force=force)
            assert failure.value.code == "update_source_rate_limited"
            assert "UTC" in failure.value.message
        assert len(requests) == 1
        assert monitor.release_retry_at - time.monotonic() > 3500
        monitor.release_retry_at = time.monotonic() - 1
        assert (await monitor._latest_release())["version"] == "2026.9.1"
        assert len(requests) == 2

    asyncio.run(check())
