import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from mediahub.config import Config
from mediahub.errors import DomainError
from mediahub.managed_apps import ManagedApps

SEED = "org.mediahub.mediaseed"
VPN = "org.mediahub.mediavpn"


def setup_manager(logged_in, tmp_path, monkeypatch, package=SEED, runtime=False):
    svc = logged_in.app.state.services
    policy = {package: {"installationId": "synthetic-installation", "project": "synthetic-app"}}
    if runtime:
        policy[package]["runtimeLabels"] = {"org.mediahub.mediavpn.owner": "mediavpn"}
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    svc.config.managed_apps_policy_file = path
    svc.config.operator_app_urls[package] = "http://127.0.0.1:18802"
    manager = ManagedApps(svc)
    svc.managed_apps = manager
    rows = {
        "a" * 64: {
            "Id": "a" * 64,
            "Name": "/synthetic-app-1",
            "Config": {
                "Labels": {"com.docker.compose.project": "synthetic-app"},
                "Env": ["SECRET=must-not-be-journaled"],
            },
            "State": {"Running": True},
            "HostConfig": {"NetworkMode": "bridge"},
            "Mounts": [
                {"Type": "volume", "Name": "synthetic-data"},
                {"Type": "bind", "Source": "/preserved"},
            ],
        }
    }
    calls = []

    async def docker(method, path, missing=False):
        calls.append((method, path))
        url = urlsplit(path)
        if url.path == "/containers/json":
            filters = json.loads(parse_qs(url.query).get("filters", ["{}"][0:1])[0])
            labels = dict(value.split("=", 1) for value in filters.get("label", []))
            return [
                deepcopy(row)
                for row in rows.values()
                if all(row["Config"]["Labels"].get(key) == value for key, value in labels.items())
            ]
        if url.path.startswith("/volumes/"):
            return {"Name": unquote(url.path.rsplit("/", 1)[-1])}
        identifier = url.path.split("/")[2]
        if method == "GET":
            return deepcopy(rows.get(identifier))
        if method == "POST":
            rows[identifier]["State"]["Running"] = False
        if method == "DELETE":
            assert url.query == "force=false&v=false"
            rows.pop(identifier)
        return {}

    monkeypatch.setattr(manager, "docker", docker)
    asyncio.run(manager.initialize())
    return svc, manager, rows, calls


def test_managed_registration_confirmation_removal_and_restart(logged_in, tmp_path, monkeypatch):
    svc, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)
    install_journal = svc.config.data_dir / "managed-install-mediaseed.json"
    install_journal.write_text(json.dumps({"state": "succeeded"}))
    app = logged_in.get("/api/v1/app-settings/" + SEED).json()["data"]["removableApp"]
    assert app and not app["isMock"] and app["removable"]
    listed = logged_in.get("/api/v1/apps?include_health=false").json()["data"]
    assert next(row for row in listed if row["id"] == app["id"])["removable"]
    endpoint = "/api/v1/apps/" + app["id"] + "/uninstall"
    ready = logged_in.get(endpoint).json()["data"]
    assert logged_in.post(endpoint, json={"confirmedInstallationId": "wrong"}).status_code == 409
    assert not any(method != "GET" for method, _ in calls)
    svc.config.sso_app_urls[SEED] = "https://seed.example"

    async def remove():
        result = await manager.remove(SEED, ready["installationId"])
        assert result["state"] == "accepted"
        await manager.tasks[SEED]
        result = await manager.status(SEED)
        assert result["state"] == "succeeded" and result["dataPreserved"]
        assert not rows
        assert not install_journal.exists()
        assert (await manager.remove(SEED, ready["installationId"]))["state"] == "succeeded"
        await manager.initialize()

    asyncio.run(remove())
    assert "SECRET" not in manager.journal(SEED).read_text()
    assert logged_in.get("/api/v1/mediaseed/status").json()["data"]["configured"] is False
    assert not any(app["packageId"] == SEED for app in logged_in.get("/api/v1/apps").json()["data"])
    assert logged_in.get("/api/v1/app-settings/" + SEED).json()["data"]["removableApp"] is None
    from mediahub.sso import configured_app

    with pytest.raises(DomainError):
        configured_app(svc, SEED)
    assert not any(
        path.startswith(("/images", "/networks", "/volumes")) and method != "GET"
        for method, path in calls
    )


def test_container_replacement_invalidates_confirmation(logged_in, tmp_path, monkeypatch):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)
    ready = asyncio.run(manager.status(SEED))
    replacement = rows.pop("a" * 64)
    replacement["Id"] = "b" * 64
    rows["b" * 64] = replacement
    with pytest.raises(DomainError):
        asyncio.run(manager.remove(SEED, ready["installationId"]))
    assert not any(method != "GET" for method, _ in calls)


@pytest.mark.parametrize("dependency", ["client", "namespace"])
def test_vpn_dependency_blocks_all_mutations(logged_in, tmp_path, monkeypatch, dependency):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch, VPN, True)
    rows["b" * 64] = {
        "Id": "b" * 64,
        "Config": {
            "Labels": {"org.mediahub.mediavpn.seedbox": "mediaseed"}
            if dependency == "client"
            else {}
        },
        "HostConfig": {
            "NetworkMode": "container:" + "a" * 64 if dependency == "namespace" else "bridge"
        },
    }
    with pytest.raises(DomainError, match="MediaSeed|Another app"):
        asyncio.run(manager.status(VPN))
    assert not any(method != "GET" for method, _ in calls)


def test_uninstall_requires_admin_and_csrf(logged_in, tmp_path, monkeypatch):
    _, manager, _, calls = setup_manager(logged_in, tmp_path, monkeypatch)
    app = logged_in.get("/api/v1/app-settings/" + SEED).json()["data"]["removableApp"]
    endpoint = "/api/v1/apps/" + app["id"] + "/uninstall"
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.post(endpoint, json={"confirmedInstallationId": "wrong"}).status_code == 403
    from mediahub.db import User
    from sqlalchemy import select

    with manager.svc.sessions.begin() as db:
        db.scalar(select(User).where(User.username == "tester")).role = "user"
    assert logged_in.get(endpoint).status_code == 403
    assert not any(method != "GET" for method, _ in calls)


def test_failure_keeps_snapshot_and_can_retry(logged_in, tmp_path, monkeypatch):
    svc, manager, rows, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    original = manager.docker
    failed = False

    async def docker(method, path, missing=False):
        nonlocal failed
        if method == "DELETE" and not failed:
            failed = True
            raise DomainError("failure", "Synthetic runtime failure", 503)
        return await original(method, path, missing)

    monkeypatch.setattr(manager, "docker", docker)

    async def remove():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "failed"
        assert rows and any(app["packageId"] == SEED for app in svc.apps.list())
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "succeeded"

    asyncio.run(remove())


def test_controller_failure_never_deletes_containers(logged_in, tmp_path, monkeypatch):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)
    rows["a" * 64]["Config"]["Labels"]["org.mediahub.mediavpn.seedbox"] = "mediaseed"
    monkeypatch.setattr(
        manager,
        "disconnect_client",
        AsyncMock(side_effect=DomainError("controller", "Unavailable", 409)),
    )

    async def remove():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "failed"

    asyncio.run(remove())
    assert not any(method != "GET" for method, _ in calls)


def test_unattached_seed_removal_does_not_require_mediavpn(logged_in, tmp_path, monkeypatch):
    _, manager, rows, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    disconnect = AsyncMock(side_effect=DomainError("controller", "MediaVPN removed", 503))
    monkeypatch.setattr(manager, "disconnect_client", disconnect)

    async def remove():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "succeeded"

    asyncio.run(remove())
    disconnect.assert_not_called()
    assert not rows


def test_seed_removal_fences_present_controller_before_client_is_created(logged_in, tmp_path, monkeypatch):
    _, manager, _, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    manager.policy[VPN] = manager.policy[SEED].model_copy(update={"project": "synthetic-vpn"})
    containers = manager.containers

    async def current(package):
        return [{"Id": "vpn-controller"}] if package == VPN else await containers(package)

    monkeypatch.setattr(manager, "containers", current)
    disconnect = AsyncMock()
    monkeypatch.setattr(manager, "disconnect_client", disconnect)

    async def remove():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "succeeded"

    asyncio.run(remove())
    disconnect.assert_awaited_once()


def test_pending_removal_resumes_after_restart(logged_in, tmp_path, monkeypatch):
    _, manager, rows, _ = setup_manager(logged_in, tmp_path, monkeypatch)

    async def resume():
        current, confirmation = await manager.preflight(SEED)
        manager.save(
            SEED,
            {
                "state": "running",
                "installationId": manager.policy[SEED].installationId,
                "confirmation": confirmation,
                "containers": current,
                "volumes": ["synthetic-data"],
            },
        )
        await manager.initialize()
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "succeeded"
        assert not rows

    asyncio.run(resume())


def test_controller_disconnect_preserves_profile(logged_in, tmp_path, monkeypatch):
    import httpx

    _, manager, _, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    token_file = tmp_path / "integration.token"
    token_file.write_text("synthetic-test-token")
    policy = manager.policy[SEED].model_copy(
        update={"integrationUrl": "http://127.0.0.1:18802", "integrationTokenFile": token_file}
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["X-MediaSeed-Key"] == "synthetic-test-token"
        return httpx.Response(200, json={"enabled": request.method == "GET", "profileId": "a" * 24})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    asyncio.run(manager.disconnect_client(policy))
    assert json.loads(requests[1].content) == {"enabled": False, "profileId": "a" * 24}


def test_api_dispatches_managed_removal(logged_in, tmp_path, monkeypatch):
    _, manager, _, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    app = logged_in.get("/api/v1/app-settings/" + SEED).json()["data"]["removableApp"]
    path = "/api/v1/apps/" + app["id"] + "/uninstall"
    confirmation = logged_in.get(path).json()["data"]["installationId"]
    response = logged_in.post(path, json={"confirmedInstallationId": confirmation})
    assert response.status_code == 200 and response.json()["data"]["state"] == "accepted"
    for _ in range(50):
        result = logged_in.get(path).json()["data"]
        if result["state"] == "succeeded":
            break
    assert result["state"] == "succeeded" and result["dataPreserved"]


def test_unsafe_policy_is_rejected(tmp_path):
    from types import SimpleNamespace

    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                SEED: {
                    "installationId": "synthetic-installation",
                    "project": "synthetic-app",
                    "runtimeLabels": {"org.mediahub.mediavpn.seedbox": "mediaseed"},
                }
            }
        )
    )
    with pytest.raises(ValueError):
        ManagedApps(SimpleNamespace(config=Config(managed_apps_policy_file=path, _env_file=None)))
