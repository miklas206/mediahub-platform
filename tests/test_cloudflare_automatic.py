import asyncio
import copy
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from mediahub.cloudflare_management import CloudflareManagement, PublishApp
from mediahub.errors import DomainError

BASE = "/api/v1/cloudflare/manage"
ACCOUNT = "a" * 32
ZONE = "b" * 32
TUNNEL = "11111111-2222-4333-8444-555555555555"
UNRELATED = "99999999-2222-4333-8444-555555555555"
BODY = {"zoneId": ZONE, "label": "hub", "packageId": "mediahub"}


@pytest.fixture
def automatic(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    svc.config.base_url = "https://192.168.1.50:18765"
    svc.config.allowed_origins.append("https://127.0.0.1:18765")
    logged_in.base_url = "https://127.0.0.1:18765"
    manager = svc.cloudflare_management
    manager.store.put("api_token", b"synthetic-cloudflare-private-token")
    manager.save({"accountId": ACCOUNT, "tunnels": [], "routes": []})
    remote = {
        "tunnels": [{"id": UNRELATED, "name": "existing-home-tunnel", "config_src": "cloudflare"}],
        "records": [],
        "calls": [],
        "config": {"ingress": [{"service": "http_status:404"}]},
    }

    async def call(method, path, body=None, params=None, token=None):
        remote["calls"].append((method, path, copy.deepcopy(body)))
        if path == "/zones/" + ZONE:
            return {"name": "example.com", "account": {"id": ACCOUNT}}
        if path.endswith("/cfd_tunnel"):
            if method == "POST":
                row = {"id": TUNNEL, **body}
                remote["tunnels"].append(row)
                return copy.deepcopy(row)
            return copy.deepcopy(remote["tunnels"])
        if path.endswith("/cfd_tunnel/" + TUNNEL):
            return copy.deepcopy(next(row for row in remote["tunnels"] if row["id"] == TUNNEL))
        if path.endswith("/dns_records"):
            if method == "POST":
                row = {"id": "c" * 32, **body}
                remote["records"].append(row)
                return row
            return copy.deepcopy(
                [row for row in remote["records"] if row.get("name") == params["name"]]
            )
        if path.endswith("/configurations"):
            if method == "PUT":
                remote["config"] = copy.deepcopy(body["config"])
            return {"config": copy.deepcopy(remote["config"])}
        raise AssertionError((method, path))

    monkeypatch.setattr(manager, "call", call)
    preflight = AsyncMock(return_value=({}, {}))
    install = AsyncMock(
        return_value={"state": "starting", "tunnelId": TUNNEL, "location": "MediaHub host"}
    )
    monkeypatch.setattr("mediahub.cloudflare_connector.preflight", preflight)
    monkeypatch.setattr("mediahub.cloudflare_connector.install", install)
    return manager, remote, preflight, install


def finish(client, manager):
    async def wait():
        await manager.setup_task

    client.portal.call(wait)
    return manager.public()


def submit(client, manager, body=None):
    response = client.post(BASE + "/publish", json=body or BODY)
    assert response.status_code == 202, response.text
    return finish(client, manager)


def mutations(remote):
    return [row for row in remote["calls"] if row[0] != "GET"]


def test_publish_configures_app_and_reuses_only_own_dedicated_tunnel(logged_in, automatic):
    manager, remote, _, install = automatic
    before = copy.deepcopy(remote["tunnels"][0])
    first = submit(logged_in, manager)
    assert first["setup"]["state"] == "succeeded"
    assert first["setup"]["hostname"] == "hub.example.com"
    assert first["automaticTunnel"]["name"].startswith("mediahub-")
    assert first["automaticTunnel"]["id"] == TUNNEL
    assert first["routes"][0]["lastApplied"] == manager.svc.config.base_url
    assert first["connectors"][TUNNEL]["state"] == "starting"
    assert remote["records"][0]["content"] == TUNNEL + ".cfargotunnel.com"
    assert remote["tunnels"][0] == before
    second = submit(logged_in, manager)
    assert second["setup"]["state"] == "succeeded"
    assert len(second["routes"]) == len(remote["records"]) == 1
    assert len([row for row in mutations(remote) if row[1].endswith("/cfd_tunnel")]) == 1
    assert install.await_count == 2


def test_lost_creation_response_recovers_journaled_random_name(logged_in, automatic, monkeypatch):
    manager, remote, _, _ = automatic
    original = manager.call
    lose_response = True

    async def call(method, path, *args, **kwargs):
        nonlocal lose_response
        result = await original(method, path, *args, **kwargs)
        if method == "POST" and path.endswith("/cfd_tunnel") and lose_response:
            lose_response = False
            raise DomainError("cloudflare_api", "Synthetic lost response", 502)
        return result

    monkeypatch.setattr(manager, "call", call)
    first = submit(logged_in, manager)
    assert first["setup"]["state"] == "failed"
    assert "id" not in first["automaticTunnel"]
    saved_name = first["automaticTunnel"]["name"]
    second = submit(logged_in, manager)
    assert second["setup"]["state"] == "succeeded"
    assert second["automaticTunnel"]["name"] == saved_name
    assert len(remote["tunnels"]) == 2
    assert len([row for row in mutations(remote) if row[1].endswith("/cfd_tunnel")]) == 1


def test_dns_conflict_fails_before_creating_tunnel_or_connector(logged_in, automatic):
    manager, remote, _, install = automatic
    remote["records"] = [
        {"id": "existing", "name": "hub.example.com", "type": "A", "content": "203.0.113.1"}
    ]
    state = submit(logged_in, manager)
    assert state["setup"]["state"] == "failed"
    assert state["setup"]["code"] == "dns_conflict"
    assert not mutations(remote)
    assert "automaticTunnel" not in state
    install.assert_not_awaited()


def test_missing_local_requirements_do_not_create_remote_resources(logged_in, automatic):
    manager, remote, preflight, install = automatic
    preflight.side_effect = DomainError("connector_runtime", "Synthetic missing runtime", 409)
    state = submit(logged_in, manager)
    assert state["setup"]["code"] == "connector_runtime"
    assert not mutations(remote)
    install.assert_not_awaited()


def test_existing_manual_route_keeps_its_connector_and_settings(logged_in, automatic):
    manager, remote, preflight, install = automatic
    state = manager.state()
    state["tunnels"] = [{"id": UNRELATED, "name": "existing-home-tunnel"}]
    state["routes"] = [
        {
            "id": "existing-route",
            "tunnelId": UNRELATED,
            "zoneId": ZONE,
            "hostname": "hub.example.com",
            "packageId": "mediahub",
            "autoSync": False,
            "caPool": "/custom/ca.pem",
            "lastApplied": manager.svc.config.base_url,
            "status": "synced",
        }
    ]
    manager.save(state)
    remote["records"] = [
        {
            "name": "hub.example.com",
            "type": "CNAME",
            "proxied": True,
            "content": UNRELATED + ".cfargotunnel.com",
        }
    ]
    remote["config"]["ingress"].insert(
        0,
        {
            "hostname": "hub.example.com",
            "service": manager.svc.config.base_url,
            "originRequest": {"caPool": "/custom/ca.pem"},
        },
    )
    snapshot = copy.deepcopy(remote["config"])
    result = submit(logged_in, manager)
    assert result["setup"]["state"] == "succeeded"
    assert result["setup"]["connectorMode"] == "existing"
    assert "existing connector" in result["setup"]["message"]
    assert result["routes"][0]["autoSync"] is False
    assert "automaticTunnel" not in result
    assert remote["config"] == snapshot
    assert not mutations(remote)
    preflight.assert_not_awaited()
    install.assert_not_awaited()


def test_changed_automatic_tunnel_identity_is_not_silently_adopted(logged_in, automatic):
    manager, remote, _, install = automatic
    assert submit(logged_in, manager)["setup"]["state"] == "succeeded"
    next(row for row in remote["tunnels"] if row["id"] == TUNNEL)["name"] = "manually-renamed"
    install.reset_mock()
    before = len(mutations(remote))
    result = submit(logged_in, manager)
    assert result["setup"]["code"] == "tunnel_conflict"
    assert len(mutations(remote)) == before
    install.assert_not_awaited()


def test_danish_domain_label_is_validated_as_idna(logged_in, automatic):
    manager, remote, _, _ = automatic
    state = submit(logged_in, manager, {**BODY, "label": "æøå"})
    assert state["setup"]["state"] == "succeeded"
    assert remote["records"][0]["name"] == "æøå".encode("idna").decode() + ".example.com"


def test_origin_changed_during_connector_install_is_revalidated(logged_in, automatic, monkeypatch):
    manager, remote, _, install = automatic
    monkeypatch.setattr(
        manager,
        "origin",
        AsyncMock(
            side_effect=[
                "https://192.168.1.50:18765",
                "https://192.168.1.50:18765",
                "https://127.0.0.1:18765",
            ]
        ),
    )
    result = submit(logged_in, manager)
    assert result["setup"]["state"] == "failed"
    assert result["setup"]["code"] == "connector_origin"
    install.assert_awaited_once()
    assert not remote["records"]
    assert not any(
        method == "PUT" and path.endswith("/configurations") for method, path, _ in remote["calls"]
    )


def test_acceptance_serializes_journal_after_existing_state_writer(logged_in, automatic):
    manager, _, _, _ = automatic

    async def scenario():
        async with manager.lock:
            state = manager.state()
            pending = asyncio.create_task(manager.publish(PublishApp(**BODY)))
            await asyncio.sleep(0)
            assert not pending.done()
            assert "setup" not in manager.state()
            state["independentSetting"] = "preserved"
            manager.save(state)
        await pending
        await manager.setup_task

    logged_in.portal.call(scenario)
    result = manager.public()
    assert result["setup"]["state"] == "succeeded"
    assert result["setup"]["hostname"] == "hub.example.com"
    assert result["independentSetting"] == "preserved"


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "label": "https://bad"},
        {**BODY, "packageId": "org.mediahub.jellyfin"},
        {**BODY, "packageId": "org.other.app"},
    ],
)
def test_invalid_or_uninstalled_app_is_rejected_immediately(logged_in, automatic, body):
    _, remote, _, install = automatic
    assert logged_in.post(BASE + "/publish", json=body).status_code in {409, 422}
    assert not mutations(remote)
    install.assert_not_awaited()


def test_zone_must_belong_to_connected_account(logged_in, automatic, monkeypatch):
    manager, remote, _, install = automatic
    original = manager.call

    async def call(method, path, *args, **kwargs):
        result = await original(method, path, *args, **kwargs)
        if path == "/zones/" + ZONE:
            result["account"]["id"] = "d" * 32
        return result

    monkeypatch.setattr(manager, "call", call)
    state = submit(logged_in, manager)
    assert state["setup"]["code"] == "cloudflare_account"
    assert not mutations(remote)
    install.assert_not_awaited()


def test_lost_route_update_response_is_retried_without_duplicate_records(
    logged_in, automatic, monkeypatch
):
    manager, remote, _, _ = automatic
    original = manager.call
    fail = True

    async def call(method, path, *args, **kwargs):
        nonlocal fail
        result = await original(method, path, *args, **kwargs)
        if method == "PUT" and fail:
            fail = False
            raise DomainError("cloudflare_api", "Synthetic lost response", 502)
        return result

    monkeypatch.setattr(manager, "call", call)
    assert submit(logged_in, manager)["setup"]["state"] == "failed"
    state = submit(logged_in, manager)
    assert state["setup"]["state"] == "succeeded"
    assert len(state["routes"]) == len(remote["records"]) == 1


def test_progress_polling_and_duplicate_request_do_not_wait_for_install(logged_in, automatic):
    manager, _, _, install = automatic
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused(*_):
        entered.set()
        await release.wait()
        return {"state": "starting", "tunnelId": TUNNEL}

    install.side_effect = paused
    try:
        assert logged_in.post(BASE + "/publish", json=BODY).status_code == 202
        logged_in.portal.call(entered.wait)
        status = logged_in.get(BASE)
        assert status.status_code == 200
        assert status.json()["data"]["setup"]["phase"] == "connector"
        assert logged_in.post(BASE + "/publish", json=BODY).status_code == 202
        assert logged_in.post(BASE + "/publish", json={**BODY, "label": "other"}).status_code == 409
        assert install.await_count == 1
    finally:
        logged_in.portal.call(release.set)
        finish(logged_in, manager)


def test_restart_marks_incomplete_setup_retryable_without_losing_identity(logged_in, automatic):
    manager, _, _, _ = automatic
    state = manager.state()
    state["setup"] = {**BODY, "state": "running", "phase": "tunnel"}
    state["automaticTunnel"] = {"name": "mediahub-" + "e" * 32, "accountId": ACCOUNT}
    manager.save(state)
    restored = CloudflareManagement(manager.svc).public()
    assert restored["setup"]["state"] == "failed"
    assert restored["setup"]["code"] == "setup_interrupted"
    assert restored["automaticTunnel"] == state["automaticTunnel"]


def test_connector_token_is_readable_only_by_its_container_user(logged_in, monkeypatch, tmp_path):
    from mediahub.cloudflare_connector import install

    manager = logged_in.app.state.services.cloudflare_management
    manager.save({"accountId": ACCOUNT, "routes": [], "tunnels": [{"id": TUNNEL, "name": "owned"}]})
    manager.svc.config.managed_apps_docker_socket = tmp_path / "socket"
    monkeypatch.setenv("HOSTNAME", "owned-core")
    own = {
        "Config": {"Labels": {"com.docker.compose.project": "mediahub-platform"}},
        "Mounts": [
            {"Type": "bind", "Destination": "/data", "Source": "/opt/mediahub/data"},
            {"Type": "bind", "Destination": "/trust", "Source": "/opt/mediahub/trust"},
        ],
    }
    created = []

    async def docker(method, path, **kwargs):
        if path == "/containers/owned-core/json":
            return own
        if method == "GET":
            return None
        if path.startswith("/containers/create"):
            created.append(kwargs["body"])
        return {}

    monkeypatch.setattr(manager.svc.managed_apps, "docker", docker)
    monkeypatch.setattr(manager, "call", AsyncMock(return_value="private-connector-token"))
    original = httpx.AsyncClient
    pulls = []

    def handler(request):
        pulls.append(request)
        if request.method == "POST":
            assert dict(request.url.params) == {
                "fromImage": "cloudflare/cloudflared",
                "tag": "latest",
            }
            return httpx.Response(200, text='{"status":"Pull complete"}\n')
        return httpx.Response(
            200,
            json={
                "Id": "sha256:" + "f" * 64,
                "RepoDigests": ["cloudflare/cloudflared@sha256:" + "e" * 64],
            },
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **{**kwargs, "transport": httpx.MockTransport(handler)},
        ),
    )
    chown = Mock()
    monkeypatch.setattr("mediahub.cloudflare_connector.os.chown", chown, raising=False)
    logged_in.portal.call(install, manager, TUNNEL)
    path = manager.svc.config.data_dir / "cloudflare-connectors" / (TUNNEL + ".token")
    chown.assert_called_once_with(path, 10001, 10001, follow_symlinks=False)
    assert created[0]["User"] == "10001:10001"
    assert created[0]["Image"] == "sha256:" + "f" * 64
    assert [request.method for request in pulls] == ["POST", "GET"]
    assert "private-connector-token" not in str(created)
    assert path.read_text() == "private-connector-token"
