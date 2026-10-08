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


@pytest.mark.parametrize(
    "status,headers",
    [
        (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(time.time()) + 3600)}),
        (403, {"retry-after": "3600"}),
        (429, {"retry-after": "Mon, 05 Oct 2099 22:00:00 GMT"}),
        (429, {"retry-after": "invalid", "x-ratelimit-reset": "nan"}),
    ],
)
def test_deferred_check_survives_restart_with_stale_release(
    logged_in, monkeypatch, status, headers
):
    requests = []
    token = "ghp_" + "a" * 30

    async def handler(request):
        if request.url.host != "api.github.com":
            assert "authorization" not in request.headers
            return httpx.Response(
                200, json={"metricsReachable": True, "connections": 4, "version": "2026.8.0"}
            )
        requests.append(request)
        assert request.headers["authorization"] == "Bearer " + token
        if len(requests) == 1:
            return httpx.Response(
                200, headers={"etag": '"release-1"'}, json={"tag_name": "2026.9.1"}
            )
        return httpx.Response(status, headers=headers, text=token)

    mock_client(monkeypatch, handler)
    sessions = logged_in.app.state.services.sessions

    async def scenario():
        monitor = CloudflareTunnelMonitor(
            config(probes=[]), sessions=sessions, token_provider=lambda: token
        )
        await monitor.update_check()
        monitor.release_cached_at -= 1000
        first = await monitor.update_check(force=True)
        assert first["checkStatus"] == "deferred"
        assert first["latestVersion"] == "2026.9.1"
        assert first["stale"] is True
        assert first["updateAvailable"] is True
        assert token not in json.dumps(first)
        restarted = CloudflareTunnelMonitor(
            config(probes=[]), sessions=sessions, token_provider=lambda: token
        )
        assert restarted.release_etag == '"release-1"'
        for force in (False, True, True):
            result = await restarted.update_check(force=force)
            assert result["retryAt"] == first["retryAt"]
            assert result["checkedAt"] == first["checkedAt"]
            assert result["checkStatus"] == "deferred"
        assert (await restarted.status())["metricsReachable"] is True
        assert (await restarted.status())["connections"] == 4
        assert (await restarted.status())["status"] == (await monitor.status())["status"]
        assert len(requests) == 2

    asyncio.run(scenario())


def test_conditional_cache_is_reused_after_restart_and_revalidated(logged_in, monkeypatch):
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            assert "if-none-match" not in request.headers
            return httpx.Response(200, headers={"etag": '"stable"'}, json={"tag_name": "2026.9.1"})
        assert request.headers["if-none-match"] == '"stable"'
        return httpx.Response(304)

    mock_client(monkeypatch, handler)
    sessions = logged_in.app.state.services.sessions

    async def scenario():
        monitor = CloudflareTunnelMonitor(config(), sessions=sessions)
        original = await monitor._latest_release()
        restarted = CloudflareTunnelMonitor(config(), sessions=sessions)
        assert (await restarted._latest_release())["version"] == original["version"]
        assert len(requests) == 1
        restarted.release_cached_at -= 1000
        refreshed = await restarted._latest_release()
        assert refreshed["version"] == original["version"]
        assert refreshed["checkedAt"] >= original["checkedAt"]
        assert refreshed["cached"] is True
        assert len(requests) == 2

    asyncio.run(scenario())


def test_concurrent_forced_checks_and_repeat_force_make_one_request(monkeypatch):
    requests = []

    async def handler(request):
        requests.append(request)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"tag_name": "2026.9.1"})

    mock_client(monkeypatch, handler)

    async def scenario():
        monitor = CloudflareTunnelMonitor(config())
        results = await asyncio.gather(*(monitor._latest_release(force=True) for _ in range(10)))
        assert all(result["version"] == "2026.9.1" for result in results)
        for _ in range(5):
            await monitor._latest_release(force=True)
        assert len(requests) == 1

    asyncio.run(scenario())


def test_rate_limit_without_cache_is_deferred_not_up_to_date(monkeypatch):
    async def handler(request):
        return httpx.Response(429)

    mock_client(monkeypatch, handler)
    result = asyncio.run(CloudflareTunnelMonitor(config(probes=[])).update_check())
    assert result["checkStatus"] == "deferred"
    assert result["latestVersion"] is None
    assert result["checkedAt"] is None
    assert result["updateAvailable"] is False
    assert "up to date" not in result["message"]


@pytest.mark.parametrize("status", [401, 403, 502])
def test_other_http_failures_are_not_hidden_by_saved_release(monkeypatch, status):
    async def handler(request):
        return httpx.Response(status, text="secret upstream detail")

    mock_client(monkeypatch, handler)
    monitor = CloudflareTunnelMonitor(config())
    monitor.release_cached = {
        "version": "2026.9.1",
        "releaseUrl": "unused",
        "checkedAt": time.time(),
    }
    with pytest.raises(DomainError) as error:
        asyncio.run(monitor._latest_release())
    assert error.value.code == "update_source_http_error"
    assert "secret" not in error.value.message


def test_persisted_cooldown_expires_and_success_clears_it(logged_in, monkeypatch):
    from mediahub.db import Setting
    from sqlalchemy import select

    requests = []
    sessions = logged_in.app.state.services.sessions

    async def handler(request):
        if request.url.host != "api.github.com":
            return httpx.Response(200, json={"metricsReachable": True, "connections": 4})
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"retry-after": "900"})
        return httpx.Response(200, json={"tag_name": "2026.10.0"})

    mock_client(monkeypatch, handler)

    async def scenario():
        monitor = CloudflareTunnelMonitor(config(), sessions=sessions)
        results = await asyncio.gather(*(monitor.update_check(force=True) for _ in range(5)))
        assert all(result["checkStatus"] == "deferred" for result in results)
        github_calls = [request for request in requests if request.url.host == "api.github.com"]
        # Only GitHub requests are relevant; status helper requests are read-only.
        assert len(github_calls) == 1
        restarted = CloudflareTunnelMonitor(config(), sessions=sessions)
        with pytest.raises(DomainError):
            await restarted._latest_release(force=True)
        clock, monotonic = time.time, time.monotonic
        with monkeypatch.context() as context:
            context.setattr(time, "time", lambda: clock() + 901)
            context.setattr(time, "monotonic", lambda: monotonic() + 901)
            recovered = CloudflareTunnelMonitor(config(), sessions=sessions)
            assert (await recovered._latest_release())["version"] == "2026.10.0"
        with sessions() as db:
            state = db.scalar(select(Setting).where(Setting.key == "cloudflared-release-cache"))
            assert state.value["retryAt"] == 0
        assert (await CloudflareTunnelMonitor(config(), sessions=sessions)._latest_release())[
            "version"
        ] == "2026.10.0"

    asyncio.run(scenario())
