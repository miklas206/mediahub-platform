import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mediahub.apps.cloudflared import register_cloudflared_app
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
