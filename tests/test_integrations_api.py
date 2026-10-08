import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mediahub.db import ExternalIntegration, User
from mediahub.integrations.fjordhub import FjordHubClient
from mediahub.integrations.provider import IntegrationSnapshot
from pydantic import SecretStr
from sqlalchemy import select


def body():
    return {
        "name": "Private FjordHub",
        "baseUrl": "https://192.168.50.20:8443",
        "accessToken": "test-private-access-token-123456",
    }


@pytest.mark.parametrize(
    "snapshot,delay",
    [
        (
            IntegrationSnapshot(
                status="online", capabilities=["docker.resources.read"], metrics={"cpuPercent": 12}
            ),
            10,
        ),
        (IntegrationSnapshot(status="online"), 60),
        (IntegrationSnapshot(status="rate_limited", retry_after=120), 120),
        (IntegrationSnapshot(status="offline"), 60),
    ],
)
def test_resource_refresh_interval_and_backoff(logged_in, monkeypatch, snapshot, delay):
    monkeypatch.setattr("mediahub.integrations.service.time", SimpleNamespace(time=lambda: 10000))
    svc = logged_in.app.state.services
    sync = AsyncMock(return_value=snapshot)
    svc.integrations.provider_factory = lambda *args, **kwargs: SimpleNamespace(sync=sync)
    published = []
    original_publish = svc.events.publish

    def capture(kind, data):
        published.append((kind, data))
        original_publish(kind, data)

    monkeypatch.setattr(svc.events, "publish", capture)
    identifier = logged_in.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    response = logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={})
    assert response.status_code == 200
    assert response.json()["data"]["nextSync"] == 10000 + delay
    assert ("integration.updated", {"id": identifier}) in published
    logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={})
    sync.assert_awaited_once()


def wire(client, code=200):
    def handler(request):
        assert request.method == "GET"
        if code != 200:
            return httpx.Response(code)
        if request.url.path == "/api/integrations/v1/resources":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "/api/integrations/v1/apps": {
                    "items": [
                        {
                            "id": "new-app",
                            "name": "Dynamic future app",
                            "description": "Future catalog entry",
                        }
                    ]
                },
            }[request.url.path],
        )

    client.app.state.services.integrations.provider_factory = lambda url, token, **kw: (
        FjordHubClient(url, token, transport=httpx.MockTransport(handler), **kw)
    )


def test_integration_auth_and_csrf(client, logged_in):
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert client.post("/api/v1/integrations/fjordhub", json=body()).status_code == 403


def test_save_never_returns_or_persists_plain_token(logged_in):
    client = logged_in
    response = client.post("/api/v1/integrations/fjordhub", json=body())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["tokenConfigured"]
    secret = body()["accessToken"]
    assert secret not in response.text
    assert secret not in client.get("/api/v1/integrations").text
    svc = client.app.state.services
    for path in svc.config.data_dir.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
    assert "secret_reference" not in data
    with svc.sessions() as db:
        saved = db.scalar(select(ExternalIntegration))
        assert svc.integrations.store.get(saved.secret_reference).decode() == secret


def test_test_save_sync_dynamic_and_disconnect(logged_in):
    client = logged_in
    wire(client)
    response = client.post("/api/v1/integrations/fjordhub/test", json=body())
    assert response.json()["data"]["status"] == "online"
    assert client.get("/api/v1/integrations").json()["data"] == []
    identifier = client.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    data = client.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"]
    assert data["snapshot"]["apps"][0]["name"] == "Dynamic future app"
    assert data["lastSuccessfulSync"]
    svc = client.app.state.services
    with svc.sessions() as db:
        reference = db.get(ExternalIntegration, identifier).secret_reference
    encrypted_record = svc.integrations.store.directory / f"{reference}.sealed"
    assert encrypted_record.is_file()
    response = client.post(f"/api/v1/integrations/{identifier}/disconnect", json={})
    assert response.json()["data"]["tokenConfigured"] is False
    assert not encrypted_record.exists()
    assert client.post(f"/api/v1/integrations/{identifier}/refresh", json={}).status_code == 409


def test_multiple_and_real_auth_errors(logged_in):
    wire(logged_in, 401)
    result = logged_in.post("/api/v1/integrations/fjordhub/test", json=body()).json()["data"]
    assert result["status"] == "authentication_failed"
    for port in (8443, 8444):
        payload = {**body(), "baseUrl": f"https://192.168.50.20:{port}"}
        assert logged_in.post("/api/v1/integrations/fjordhub", json=payload).status_code == 200
    assert len(logged_in.get("/api/v1/integrations").json()["data"]) == 2
    assert logged_in.get("/api/v1/health").status_code == 200


def test_validation_error_never_echoes_token(logged_in):
    invalid = {**body(), "accessToken": body()["accessToken"] + "\n"}
    response = logged_in.post("/api/v1/integrations/fjordhub", json=invalid)
    assert response.status_code == 422
    assert body()["accessToken"] not in response.text
    assert "accessToken" not in json.dumps(response.json().get("data"))


def test_production_http_cannot_receive_credentials(logged_in):
    logged_in.app.state.services.config.dev_mode = False
    response = logged_in.post("/api/v1/integrations/fjordhub", json=body())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "https_required"


def test_viewer_cannot_configure_or_test_tokens(logged_in):
    with logged_in.app.state.services.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    for endpoint in ("/fjordhub", "/fjordhub/test"):
        assert logged_in.post("/api/v1/integrations" + endpoint, json=body()).status_code == 403


def test_offline_retains_last_success_and_marks_stale(logged_in):
    wire(logged_in)
    identifier = logged_in.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    first = logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"]
    with logged_in.app.state.services.sessions.begin() as db:
        db.get(ExternalIntegration, identifier).next_sync = 0
    wire(logged_in, 503)
    latest = logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"]
    assert latest["snapshot"]["status"] == "offline"
    assert latest["snapshot"]["stale"] is True
    assert latest["snapshot"]["apps"] == first["snapshot"]["apps"]
    assert latest["lastSuccessfulSync"] == first["lastSuccessfulSync"]


def test_tokenless_detection_is_bounded_and_recognizes_only_fjordhub(logged_in, monkeypatch):
    real_client = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request.url.path)
        assert "authorization" not in request.headers
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "docker": True})
        return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})

    monkeypatch.setattr(
        "mediahub.integrations.service.httpx.AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    payload = {"baseUrl": "https://192.168.1.42:8888"}
    response = logged_in.post("/api/v1/integrations/fjordhub/detect", json=payload)
    assert response.status_code == 200
    assert not response.json()["data"]["tokenConfigured"]
    assert calls == ["/api/health", "/api/integrations/v1/resources"]
    svc = logged_in.app.state.services.integrations
    identifier = response.json()["data"]["id"]
    svc.disconnect(identifier)
    assert not svc.register_detected(payload["baseUrl"], False)["enabled"]
    reconnected = logged_in.post("/api/v1/integrations/fjordhub/detect", json=payload)
    assert reconnected.status_code == 200
    assert reconnected.json()["data"]["id"] == identifier
    assert reconnected.json()["data"]["enabled"]
    assert not reconnected.json()["data"]["tokenConfigured"]
    assert reconnected.json()["data"]["snapshot"]["status"] == "detected"
    assert (
        logged_in.post("/api/v1/integrations/fjordhub/detect", json=payload).json()["data"]["id"]
        == response.json()["data"]["id"]
    )
    assert len(logged_in.get("/api/v1/integrations").json()["data"]) == 1
    assert (
        logged_in.post(
            "/api/v1/integrations/fjordhub/detect", json={"baseUrl": "http://8.8.8.8"}
        ).status_code
        == 422
    )


def test_detection_rejects_ordinary_health_page(logged_in, monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "mediahub.integrations.service.httpx.AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"status": "ok"})),
            **kwargs,
        ),
    )
    response = logged_in.post(
        "/api/v1/integrations/fjordhub/detect", json={"baseUrl": "https://192.168.1.42"}
    )
    assert response.status_code == 422
    assert logged_in.app.state.services.integrations.list() == []


def test_remove_requires_authentication_admin_csrf_and_disconnected(logged_in):
    svc = logged_in.app.state.services
    identifier = logged_in.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    url = f"/api/v1/integrations/{identifier}"
    assert logged_in.delete(url).status_code == 409
    assert logged_in.post(url + "/disconnect", json={}).status_code == 200
    csrf = logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.delete(url).status_code == 403
    logged_in.headers["X-MediaHub-CSRF"] = csrf
    with svc.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    assert logged_in.delete(url).status_code == 403
    with svc.sessions.begin() as db:
        db.scalar(select(User)).role = "administrator"
    cookies = dict(logged_in.cookies)
    logged_in.cookies.clear()
    assert logged_in.delete(url).status_code == 401
    logged_in.cookies.update(cookies)
    assert logged_in.delete(url).status_code == 200
    assert logged_in.delete(url).status_code == 404
    assert logged_in.delete("/api/v1/integrations/unknown-id").status_code == 404


def test_remove_only_selected_record_secret_and_snapshots(logged_in):
    svc = logged_in.app.state.services
    service = svc.integrations
    selected = logged_in.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    other = logged_in.post(
        "/api/v1/integrations/fjordhub", json={**body(), "baseUrl": "https://192.168.50.21:8443"}
    ).json()["data"]["id"]
    with svc.sessions.begin() as db:
        row = db.get(ExternalIntegration, selected)
        reference = row.secret_reference
        row.enabled = False
        row.snapshot = {
            "status": "disconnected",
            "apps": [{"id": "cached"}],
            "metrics": {"cpuPercent": 12},
            "fjordflix": {"ok": True, "recent": [{"id": "movie"}]},
        }
        other_reference = db.get(ExternalIntegration, other).secret_reference
    service.provider_factory = lambda *args, **kwargs: pytest.fail(
        "Removal must never call FjordHub"
    )
    response = logged_in.delete(f"/api/v1/integrations/{selected}")
    assert response.json()["data"] == {"id": selected, "removed": True}
    with svc.sessions() as db:
        assert db.get(ExternalIntegration, selected) is None
        assert db.get(ExternalIntegration, other).secret_reference == other_reference
    assert not (service.store.directory / f"{reference}.sealed").exists()
    assert service.store.get(other_reference).decode() == body()["accessToken"]
    assert [row["id"] for row in service.list()] == [other]
    assert (
        logged_in.get(f"/api/v1/integrations/{selected}/fjordflix/posters/movie").status_code == 404
    )


def test_remove_persists_discovery_opt_out_and_manual_reconnect(logged_in):
    from mediahub.errors import DomainError
    from mediahub.integrations.service import IntegrationService

    svc = logged_in.app.state.services
    service = svc.integrations
    identifier = service.save(
        SimpleNamespace(
            **{
                "name": body()["name"],
                "baseUrl": body()["baseUrl"],
                "allowHttp": False,
                "accessToken": SecretStr(body()["accessToken"]),
            }
        )
    )["id"]
    service.disconnect(identifier)
    service.remove(identifier)
    restarted = IntegrationService(svc.config, svc.sessions, svc.events)
    restarted.default_origin = body()["baseUrl"]
    restarted.detect = AsyncMock(side_effect=AssertionError("Removed origins must not be probed"))
    asyncio.run(restarted.discover_known())
    restarted.detect.assert_not_awaited()
    with pytest.raises(DomainError, match="permanently removed"):
        restarted.register_detected(body()["baseUrl"], False)
    row = restarted.register_detected(body()["baseUrl"], False, reconnect=True)
    assert row["id"] != identifier and row["enabled"]
    assert not row["tokenConfigured"]


def test_late_refresh_cannot_restore_removed_integration(logged_in):
    from mediahub.errors import DomainError

    service = logged_in.app.state.services.integrations
    identifier = logged_in.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()

        async def sync(**kwargs):
            started.set()
            await finish.wait()
            return IntegrationSnapshot(status="online", apps=[{"id": "late"}])

        service.provider_factory = lambda *args, **kwargs: SimpleNamespace(sync=sync)
        task = asyncio.create_task(service.refresh(identifier))
        await started.wait()
        service.disconnect(identifier)
        service.remove(identifier)
        finish.set()
        with pytest.raises(DomainError, match="Integration not found"):
            await task
        assert service.list() == []

    asyncio.run(scenario())


@pytest.mark.parametrize("reconnect", [False, True])
def test_late_detection_cannot_recreate_removed_entry(logged_in, monkeypatch, reconnect):
    from mediahub.errors import DomainError

    service = logged_in.app.state.services.integrations
    row = service.register_detected(body()["baseUrl"], False)
    service.disconnect(row["id"])
    real_client = httpx.AsyncClient

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()

        async def handler(request):
            if request.url.path == "/api/health":
                started.set()
                await finish.wait()
                return httpx.Response(200, json={"status": "ok", "docker": True})
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})

        monkeypatch.setattr(
            "mediahub.integrations.service.httpx.AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
        )
        task = asyncio.create_task(
            service.detect(
                SimpleNamespace(baseUrl=body()["baseUrl"], allowHttp=False), reconnect=reconnect
            )
        )
        await started.wait()
        service.remove(row["id"])
        finish.set()
        with pytest.raises(DomainError, match="permanently removed"):
            await task
        assert service.list() == []

    asyncio.run(scenario())


def test_environment_managed_removal_is_blocked_until_configuration_changes(logged_in):
    from mediahub.errors import DomainError
    from mediahub.integrations.service import IntegrationService

    svc = logged_in.app.state.services
    svc.config.fjordhub_base_url = body()["baseUrl"]
    svc.config.fjordhub_access_token = SecretStr(body()["accessToken"])
    service = IntegrationService(svc.config, svc.sessions, svc.events)
    row = service.list()[0]
    assert row["managedByEnvironment"]
    service.disconnect(row["id"])
    with pytest.raises(DomainError, match="server environment"):
        service.remove(row["id"])
    restarted = IntegrationService(svc.config, svc.sessions, svc.events)
    assert restarted.list()[0]["enabled"] is False
    svc.config.fjordhub_base_url = None
    svc.config.fjordhub_access_token = None
    restarted = IntegrationService(svc.config, svc.sessions, svc.events)
    assert restarted.remove(row["id"])["removed"]
    assert restarted.list() == []
