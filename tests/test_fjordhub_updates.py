import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mediahub.db import ExternalIntegration
from mediahub.errors import DomainError
from mediahub.integrations.fjordhub import FjordHubClient
from mediahub.integrations.fjordhub_metadata import app_info, icon_path, updates

ORIGIN = "https://192.168.50.20:8443"
TOKEN = "test-private-access-token-123456"


def metadata(identifier="fjordflix", permission=True, port=9234, icon=None):
    return {
        identifier: {
            "id": identifier,
            "name": identifier.title(),
            "installed": True,
            "port": port,
            "icon_url": icon
            or ORIGIN + "/static/logos/icons/fjordflix-mark-transparent-512.png?v=brand-20261005",
            "permissions": {"updates": permission, "app_data": False},
        }
    }


def status(identifier="fjordflix", running=False, available=True, ok=True):
    return {
        "app_id": identifier,
        "ok": ok,
        "state": "updating" if running else "idle",
        "running": running,
        "update_available": available,
        "current_rev": "old",
        "remote_rev": "new",
        "checked_at": 12345,
        "logs": TOKEN,
        "error": TOKEN,
    }


def setup(logged_in, handler):
    service = logged_in.app.state.services.integrations
    service.provider_factory = lambda origin, token, **kw: FjordHubClient(
        origin, token, transport=httpx.MockTransport(handler), **kw
    )
    identifier = logged_in.post(
        "/api/v1/integrations/fjordhub",
        json={"name": "FjordHub", "baseUrl": ORIGIN, "accessToken": TOKEN},
    ).json()["data"]["id"]
    return service, identifier, f"/api/v1/integrations/{identifier}"


def test_exact_keyed_contract_and_token_redaction():
    client = FjordHubClient(ORIGIN, TOKEN)
    info = app_info(client, metadata())
    assert info["fjordflix"]["port"] == 9234
    assert info["fjordflix"]["permissions"] == {"updates": True, "app_data": False}
    result = updates(client, {"fjordflix": status()})
    assert result["fjordflix"]["current_rev"] == "old"
    assert TOKEN not in repr(result)
    assert "logs" not in result["fjordflix"]
    assert app_info(client, {"wrong": metadata()["fjordflix"]}) == {}


@pytest.mark.parametrize("port", [True, 0, -1, 65536, 9234.5, "9234", None])
def test_invalid_ports(port):
    assert app_info(FjordHubClient(ORIGIN, TOKEN), metadata(port=port))["fjordflix"]["port"] is None


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/static/logos/icon.png",
        ORIGIN + "/api/secrets.png",
        ORIGIN + "/static/logos/../icon.png",
        ORIGIN + "/static/logos/icon.svg",
        ORIGIN + "/static/logos/icon.png?token=secret",
        ORIGIN + "/static/logos/icon.png#fragment",
        ORIGIN + "/static/logos/%2e%2e/icon.png",
        "http://192.168.50.20:8443/static/logos/icon.png",
        ORIGIN + "/static/logos/" + TOKEN + ".png",
    ],
)
def test_unsafe_icons(url):
    assert icon_path(url, FjordHubClient(ORIGIN, TOKEN)) is None


def test_relative_icons_use_the_configured_fjordhub_origin():
    path = "/static/logos/icons/fjordflix.png?v=brand-1"
    assert icon_path(path, FjordHubClient(ORIGIN, TOKEN)) == path
    assert icon_path("//evil.example/static/logos/icon.png", FjordHubClient(ORIGIN, TOKEN)) is None


def test_metadata_resource_and_fallback():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata()})
        return httpx.Response(200, json={"ok": True, "apps": [], "hub": {}, "capacity": {}})

    snapshot = asyncio.run(
        FjordHubClient(ORIGIN, TOKEN, transport=httpx.MockTransport(handler)).sync()
    )
    assert snapshot.status == "online" and snapshot.app_info["fjordflix"]["port"] == 9234
    assert paths == ["/api/integrations/v1/resources", "/api/integrations/v1/app-info"]


@pytest.mark.parametrize("identifier", ["fjordflix", "fjordhub"])
def test_accepted_progression_and_no_auto_start(logged_in, monkeypatch, identifier):
    clock = [10000]
    monkeypatch.setattr(
        "mediahub.integrations.service.time", SimpleNamespace(time=lambda: clock[0])
    )
    calls = []
    phase = [0]

    def handler(request):
        assert request.headers["authorization"] == "Bearer " + TOKEN
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata(identifier)})
        if request.url.path.endswith("/start"):
            phase[0] = 1
            return httpx.Response(202, json=status(identifier, running=True))
        return httpx.Response(
            200,
            json={
                "ok": True,
                "updates": {
                    identifier: status(identifier, running=phase[0] == 1, available=phase[0] != 2)
                },
            },
        )

    service, key, path = setup(logged_in, handler)
    view = logged_in.get(path + "/updates").json()["data"]
    assert view["updates"][identifier]["update_available"]
    assert not any(method == "POST" for method, _ in calls)
    response = logged_in.post(path + f"/updates/{identifier}/start", json={})
    assert response.status_code == 202
    assert response.json()["data"]["updates"][identifier]["running"]
    assert TOKEN not in response.text
    assert logged_in.post(path + f"/updates/{identifier}/start", json={}).status_code == 409
    with service.sessions() as db:
        assert db.get(ExternalIntegration, key).snapshot["updates_next_poll"] == 10005
    phase[0] = 2
    clock[0] += 6
    final = logged_in.get(path + "/updates").json()["data"]
    assert not final["updates"][identifier]["running"]
    assert not final["updates"][identifier]["update_available"]


@pytest.mark.parametrize("code", [401, 403, 404, 409, 503])
def test_start_errors_preserve_uncertain_progress(logged_in, code):
    def handler(request):
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata()})
        if request.url.path.endswith("/start"):
            return httpx.Response(code, json={"error": TOKEN})
        return httpx.Response(200, json={"ok": True, "updates": {"fjordflix": status()}})

    service, key, path = setup(logged_in, handler)
    response = logged_in.post(path + "/updates/fjordflix/start", json={})
    assert response.status_code == code
    assert TOKEN not in response.text
    with service.sessions() as db:
        snapshot = db.get(ExternalIntegration, key).snapshot
        assert snapshot["updates"]["fjordflix"]["running"]
        assert snapshot["updates"]["fjordflix"]["stale"]
        assert snapshot["app_info_stale"]


@pytest.mark.parametrize(
    "permission,running,available,expected",
    [(False, False, True, 403), (True, True, True, 409), (True, False, False, 409)],
)
def test_server_permission_and_status_gates(logged_in, permission, running, available, expected):
    posts = []

    def handler(request):
        if request.method == "POST":
            posts.append(request.url.path)
        if request.url.path.endswith("app-info"):
            return httpx.Response(
                200, json={"ok": True, "app_info": metadata(permission=permission)}
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "updates": {"fjordflix": status(running=running, available=available)},
            },
        )

    _, _, path = setup(logged_in, handler)
    assert logged_in.post(path + "/updates/fjordflix/start", json={}).status_code == expected
    assert posts == []
    assert logged_in.post(path + "/updates/unknown/start", json={}).status_code == 404
    assert posts == []


def test_timeout_restart_and_poll_retains_running(logged_in, monkeypatch):
    clock = [10000]
    monkeypatch.setattr(
        "mediahub.integrations.service.time", SimpleNamespace(time=lambda: clock[0])
    )
    phase = [0]

    def handler(request):
        if phase[0] == 1 or request.url.path.endswith("/start"):
            phase[0] = 1
            raise httpx.ReadTimeout(TOKEN, request=request)
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata()})
        return httpx.Response(
            200, json={"ok": True, "updates": {"fjordflix": status(ok=phase[0] != 2)}}
        )

    _, _, path = setup(logged_in, handler)
    assert logged_in.post(path + "/updates/fjordflix/start", json={}).status_code == 503
    clock[0] += 6
    response = logged_in.get(path + "/updates")
    assert response.json()["data"]["updates"]["fjordflix"]["running"]
    assert TOKEN not in response.text
    phase[0] = 2
    clock[0] += 6
    response = logged_in.get(path + "/updates")
    assert response.json()["data"]["updates"]["fjordflix"]["ok"] is False
    assert not response.json()["data"]["updates"]["fjordflix"]["running"]


def test_update_csrf(logged_in):
    _, _, path = setup(logged_in, lambda _: httpx.Response(404))
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.post(path + "/updates/fjordflix/start", json={}).status_code == 403


def test_concurrent_start_lock(logged_in):
    service, key, _ = setup(logged_in, lambda _: httpx.Response(404))

    async def exercise():
        async with service.lock:
            with pytest.raises(DomainError) as error:
                await service.updates(key, "fjordflix", "start")
            assert error.value.status == 409
            assert (await service.updates(key))["updates"] == {}

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "kind,payload,code",
    [
        ("image/png", b"\x89PNG\r\n\x1a\nfixture", 200),
        ("text/html", b"danger", 404),
        ("image/png", b"invalid", 404),
        ("image/png", b"\x89PNG\r\n\x1a\n" + b"x" * (2 * 1024 * 1024), 404),
    ],
    ids=["png", "html", "bad-signature", "oversized"],
)
def test_bounded_icon_proxy(logged_in, kind, payload, code):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer " + TOKEN
        return httpx.Response(200, content=payload, headers={"Content-Type": kind})

    service, key, path = setup(logged_in, handler)
    with service.sessions.begin() as db:
        row = db.get(ExternalIntegration, key)
        row.snapshot = {"app_info": app_info(FjordHubClient(ORIGIN, TOKEN), metadata())}
    response = logged_in.get(path + "/apps/fjordflix/icon")
    assert response.status_code == code
    assert TOKEN not in response.text
    assert len(calls) == 1


@pytest.mark.parametrize("code", [200, 302, 403])
def test_registry_icon_proxy_never_forwards_access_token(logged_in, code):
    url = "https://raw.githubusercontent.com/qlerup/fjordflix/main/app/static/logos/icons/fjordflix-mark-transparent-512.png?v=brand-20261005"
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert "authorization" not in request.headers
        return httpx.Response(
            code,
            content=b"\x89PNG\r\n\x1a\nfixture",
            headers={"Content-Type": "image/png", "Location": "https://evil.example/icon.png"},
        )

    service, key, path = setup(logged_in, handler)
    with service.sessions.begin() as db:
        db.get(ExternalIntegration, key).snapshot = {
            "app_info": app_info(FjordHubClient(ORIGIN, TOKEN), metadata(icon=url))
        }
    response = logged_in.get(path + "/apps/fjordflix/icon")
    assert response.status_code == (200 if code == 200 else 404)
    assert calls == [url]
    assert TOKEN not in response.text


def test_registry_icons_are_exact_and_app_specific():
    from mediahub.integrations.fjordhub_metadata import REGISTRY_ICONS

    client = FjordHubClient(ORIGIN, TOKEN)
    for identifier, path in REGISTRY_ICONS.items():
        url = "https://raw.githubusercontent.com" + path
        assert icon_path(url, client, identifier) == url
        assert icon_path(url, client, "unknown") is None
        assert icon_path(url.replace("/qlerup/", "/attacker/"), client, identifier) is None
        assert icon_path(url + "?token=secret", client, identifier) is None
        assert icon_path(url.replace("https:", "http:"), client, identifier) is None


def test_check_is_explicit_and_not_installation(logged_in):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata()})
        if request.url.path.endswith("/check"):
            return httpx.Response(200, json=status())
        return httpx.Response(200, json={"ok": True, "updates": {"fjordflix": status()}})

    _, _, path = setup(logged_in, handler)
    assert logged_in.post(path + "/updates/fjordflix/check", json={}).status_code == 200
    assert [url for method, url in calls if method == "POST"] == [
        "/api/integrations/v1/updates/fjordflix/check"
    ]


def test_missing_status_is_not_a_confirmed_outcome(logged_in, monkeypatch):
    clock = [10000]
    monkeypatch.setattr(
        "mediahub.integrations.service.time", SimpleNamespace(time=lambda: clock[0])
    )
    phase = [0]

    def handler(request):
        if request.url.path.endswith("app-info"):
            return httpx.Response(
                200, json={"ok": True, "app_info": metadata() if phase[0] == 0 else {}}
            )
        if request.url.path.endswith("/start"):
            return httpx.Response(202, json=status(running=True))
        return httpx.Response(
            200, json={"ok": True, "updates": {"fjordflix": status()} if phase[0] == 0 else {}}
        )

    _, _, path = setup(logged_in, handler)
    assert logged_in.post(path + "/updates/fjordflix/start", json={}).status_code == 202
    phase[0] = 1
    clock[0] += 6
    view = logged_in.get(path + "/updates").json()["data"]
    assert view["updates"]["fjordflix"]["running"]
    assert view["updates"]["fjordflix"]["stale"]
    assert logged_in.post(path + "/updates/fjordflix/start", json={}).status_code == 404


def test_old_refresh_preserves_metadata_and_status(logged_in):
    from mediahub.integrations.provider import IntegrationSnapshot

    service, key, path = setup(logged_in, lambda _: httpx.Response(404))
    with service.sessions.begin() as db:
        row = db.get(ExternalIntegration, key)
        row.snapshot = {
            "status": "online",
            "app_info": app_info(FjordHubClient(ORIGIN, TOKEN), metadata()),
            "updates": {"fjordflix": {**status(running=True), "stale": False}},
        }

    async def sync(**_):
        return IntegrationSnapshot(
            status="online", capabilities=["docker.resources.read"], metrics={"cpuPercent": 10}
        )

    service.provider_factory = lambda *_, **__: SimpleNamespace(sync=sync)
    response = logged_in.post(path + "/refresh", json={}).json()["data"]["snapshot"]
    assert response["metrics"]["cpuPercent"] == 10
    assert response["app_info"]["fjordflix"]["port"] == 9234
    assert response["app_info_stale"]
    assert response["updates"]["fjordflix"]["running"]


def test_concurrent_actions_poll_refresh_and_config_fencing(logged_in):
    from unittest.mock import AsyncMock

    from pydantic import SecretStr

    service, key, _ = setup(logged_in, lambda _: httpx.Response(404))

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        async def metadata_read():
            entered.set()
            await release.wait()
            return app_info(FjordHubClient(ORIGIN, TOKEN), metadata())

        start = AsyncMock(return_value={**status(running=True), "accepted": True})
        service.provider_factory = lambda *_, **__: SimpleNamespace(
            metadata=metadata_read,
            update_poll=AsyncMock(return_value={"fjordflix": status()}),
            update_action=start,
        )
        task = asyncio.create_task(service.updates(key, "fjordflix", "start"))
        await entered.wait()
        for operation in (service.updates(key, "fjordflix", "start"), service.refresh(key)):
            with pytest.raises(DomainError) as error:
                await operation
            assert error.value.status == 409
        assert (await service.updates(key))["updates"] == {}
        service.save(
            SimpleNamespace(
                name="FjordHub",
                baseUrl=ORIGIN,
                allowHttp=False,
                accessToken=SecretStr(TOKEN + "changed"),
            )
        )
        release.set()
        with pytest.raises(DomainError) as error:
            await task
        assert error.value.status == 409
        start.assert_not_awaited()

    asyncio.run(exercise())


def test_viewer_reads_status_but_cannot_act(logged_in):
    from mediahub.db import User
    from sqlalchemy import select

    def handler(request):
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata()})
        return httpx.Response(200, json={"ok": True, "updates": {"fjordflix": status()}})

    service, _, path = setup(logged_in, handler)
    with service.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    assert logged_in.get(path + "/updates").status_code == 200
    for action in ("check", "start"):
        assert logged_in.post(path + "/updates/fjordflix/" + action, json={}).status_code == 403


def test_icon_redirect_is_not_followed(logged_in):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example/"})

    service, key, path = setup(logged_in, handler)
    with service.sessions.begin() as db:
        db.get(ExternalIntegration, key).snapshot = {
            "app_info": app_info(FjordHubClient(ORIGIN, TOKEN), metadata())
        }
    assert logged_in.get(path + "/apps/fjordflix/icon").status_code == 404
    assert len(calls) == 1 and calls[0].startswith(ORIGIN)


def test_check_can_recover_failed_status(logged_in):
    def handler(request):
        if request.url.path.endswith("app-info"):
            return httpx.Response(200, json={"ok": True, "app_info": metadata()})
        if request.url.path.endswith("/check"):
            return httpx.Response(200, json=status())
        return httpx.Response(200, json={"ok": True, "updates": {"fjordflix": status(ok=False)}})

    _, _, path = setup(logged_in, handler)
    assert logged_in.post(path + "/updates/fjordflix/check", json={}).status_code == 200
