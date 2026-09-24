import asyncio
from types import SimpleNamespace

import httpx
from mediahub.cloudflare_tunnel import CloudflareTunnelMonitor


def config(probes=None):
    return SimpleNamespace(
        cloudflared_status_url="http://192.168.50.10:20242/status",
        cloudflared_probe_urls=(
            ["https://media.example.test"] if probes is None else probes
        ),
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
