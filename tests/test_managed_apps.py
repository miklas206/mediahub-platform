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


def test_owned_stop_and_start_preserve_vpn_client_choice(logged_in, tmp_path, monkeypatch):
    from mediahub.managed_apps import ManagedAdapter

    svc, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch, runtime=True)
    app = next(iter(rows.values()))
    app["Config"]["Labels"]["com.docker.compose.service"] = "app"
    clone = deepcopy(app)
    clone.update(Id="b" * 64, Name="/owned-vpn-client")
    clone["Config"]["Labels"] = {"org.mediahub.mediavpn.seedbox": "mediaseed"}
    original = deepcopy(app)
    original.update(Id="c" * 64, Name="/original-qbittorrent")
    original["Config"]["Labels"]["com.docker.compose.service"] = "qbittorrent"
    original["State"]["Running"] = False
    rows.update({clone["Id"]: clone, original["Id"]: original})
    docker = manager.docker

    async def request(method, path, **kwargs):
        if method == "POST" and path.endswith("/start"):
            calls.append((method, path))
            rows[path.split("/")[2]]["State"]["Running"] = True
            return {}
        return await docker(method, path, **kwargs)

    monkeypatch.setattr(manager, "docker", request)
    adapter = ManagedAdapter(manager, SEED)
    assert asyncio.run(adapter.stop()) == "stopped"
    assert not app["State"]["Running"] and not clone["State"]["Running"]
    # A new Core adapter can recover the saved selection after its own restart.
    adapter = ManagedAdapter(manager, SEED)
    assert asyncio.run(adapter.start()) == "running"
    assert app["State"]["Running"] and clone["State"]["Running"]
    assert not original["State"]["Running"]
    assert not any(method == "DELETE" for method, path in calls)
    assert asyncio.run(adapter.logs())["entries"]


def test_uptime_uses_primary_app_not_initialization_container(logged_in, tmp_path, monkeypatch):
    from mediahub.managed_apps import ManagedAdapter

    svc, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)
    app = next(iter(rows.values()))
    app["Config"]["Labels"]["com.docker.compose.service"] = "app"
    app["State"].update(StartedAt="2026-10-14T20:00:00Z", Health={"Status": "healthy"})
    helper = deepcopy(app)
    helper["Id"] = "b" * 64
    helper["Config"]["Labels"]["com.docker.compose.service"] = "client-init"
    helper["State"].update(Running=False, StartedAt="2026-10-14T10:00:00Z")
    rows[helper["Id"]] = helper
    adapter = ManagedAdapter(manager, SEED)
    result = asyncio.run(adapter.runtime_summary())
    assert result["state"] == "running" and result["startedAt"] == "2026-10-14T20:00:00Z"
    assert len(result["containers"]) == 2
    assert "Env" not in json.dumps(result)
    adapter._observations = None
    app["State"].update(Running=False)
    stopped = asyncio.run(adapter.runtime_summary())
    assert stopped["state"] == "stopped" and stopped["startedAt"] is None


def setup_manager(logged_in, tmp_path, monkeypatch, package=SEED, runtime=False):
    svc = logged_in.app.state.services
    policy = {package: {"installationId": "synthetic-installation", "project": "synthetic-app"}}
    if runtime:
        policy[package]["runtimeLabels"] = ({"org.mediahub.mediavpn.seedbox": "mediaseed"} if package == SEED else {"org.mediahub.mediavpn.owner": "mediavpn"})
        if package == SEED:
            policy[package].update(integrationUrl="http://127.0.0.1:18802", integrationTokenFile=str(tmp_path / "synthetic-integration.token"))
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy))
    svc.config.managed_apps_policy_file = path
    svc.config.operator_app_urls[package] = "http://127.0.0.1:18802"
    manager = ManagedApps(svc)
    manager.reset_plan = lambda package: {"image": "sha256:" + "a" * 64, "mounts": []}
    manager.reset_configuration = AsyncMock()
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

    stages = []
    original_save = manager.save

    def capture(package, job):
        stages.append((job.get("progress"), job.get("phase"), job["state"]))
        original_save(package, job)

    monkeypatch.setattr(manager, "save", capture)

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
    assert stages == [
        (0, "preparing", "accepted"),
        (5, "preparing", "running"),
        (10, "removing", "running"),
        (80, "removing", "running"),
        (90, "verifying", "running"),
        (100, "complete", "succeeded"),
    ]
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


def test_live_seed_health_ignores_saved_stopped_state_and_replaced_client(logged_in, tmp_path, monkeypatch):
    from mediahub.db import InstalledApp
    from sqlalchemy import select

    svc, manager, _, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    with svc.sessions.begin() as db:
        stored = db.scalar(select(InstalledApp).where(InstalledApp.package_id == SEED))
        stored.state = "stopped"
        app_id = stored.id
    rows = [
        {"Config": {"Labels": {"com.docker.compose.service": "app"}},
         "State": {"Running": True, "Health": {"Status": "healthy"}}},
        {"Config": {"Labels": {"com.docker.compose.service": "qbittorrent"}},
         "State": {"Running": False}},
        {"Config": {"Labels": {"org.mediahub.mediavpn.seedbox": "mediaseed"}},
         "State": {"Running": True}},
    ]
    monkeypatch.setattr(manager, "containers", AsyncMock(return_value=rows))
    response = logged_in.get("/api/v1/apps")
    assert response.status_code == 200
    actual = next(row for row in response.json()["data"] if row["id"] == app_id)
    assert actual["health"]["status"] == "healthy"
    assert all(check["status"] == "healthy" for check in actual["health"]["checks"])
    with svc.sessions() as db:
        assert db.get(InstalledApp, app_id).state == "stopped"
    rows[-1]["State"]["Running"] = False
    response = logged_in.get("/api/v1/apps")
    actual = next(row for row in response.json()["data"] if row["id"] == app_id)
    assert actual["health"]["status"] != "healthy"


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


def test_vpn_removal_dependency_has_persistent_guidance_but_post_stays_blocked(logged_in, tmp_path, monkeypatch):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch, VPN, True)
    rows["b" * 64] = {
        "Id": "b" * 64,
        "Config": {"Labels": {"org.mediahub.mediavpn.seedbox": "mediaseed"}},
        "HostConfig": {"NetworkMode": "bridge"},
    }
    app = next(app for app in manager.svc.apps.list() if app["packageId"] == VPN)
    endpoint = "/api/v1/apps/" + app["id"] + "/uninstall"
    response = logged_in.get(endpoint)
    assert response.status_code == 200
    report = response.json()["data"]
    assert report["state"] == "blocked"
    assert report["configurationPath"] == "/store/mediavpn"
    assert "MediaSeed" in report["message"]
    assert "installationId" not in report
    assert logged_in.post(endpoint, json={"confirmedInstallationId": "wrong"}).status_code == 409
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
        assert (await manager.status(SEED))["progress"] == 10
        assert (await manager.status(SEED))["phase"] == "removing"
        assert rows and any(app["packageId"] == SEED for app in svc.apps.list())
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "succeeded"

    asyncio.run(remove())


def test_failed_removal_with_recreated_containers_requires_fresh_confirmation(
    logged_in, tmp_path, monkeypatch
):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)

    async def remove():
        previous, confirmation = await manager.preflight(SEED)
        manager.save(
            SEED,
            {
                "state": "failed",
                "installationId": manager.policy[SEED].installationId,
                "confirmation": confirmation,
                "containers": previous,
                "volumes": ["previous-data"],
                "progress": 5,
                "phase": "preparing",
                "message": "Installation changed during removal",
            },
        )
        replacement = rows.pop("a" * 64)
        replacement["Id"] = "b" * 64
        rows["b" * 64] = replacement
        ready = await manager.status(SEED)
        assert ready["state"] == "ready"
        assert ready["installationId"] != confirmation
        with pytest.raises(DomainError, match="review removal again"):
            await manager.remove(SEED, confirmation)
        assert not any(method != "GET" for method, _ in calls)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["state"] == "succeeded"
        assert not rows
        assert ("GET", "/volumes/previous-data") in calls

    asyncio.run(remove())


def test_labels_changed_after_review_blocks_removal_without_writes(
    logged_in, tmp_path, monkeypatch
):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)

    async def remove():
        ready = await manager.status(SEED)
        rows["a" * 64]["Config"]["Labels"]["com.docker.compose.service"] = "replacement"
        with pytest.raises(DomainError, match="review removal again"):
            await manager.remove(SEED, ready["installationId"])
        assert not any(method != "GET" for method, _ in calls)

    asyncio.run(remove())


def test_replacement_after_acceptance_stops_at_preflight_then_allows_review(
    logged_in, tmp_path, monkeypatch
):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)

    async def remove():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        replacement = rows.pop("a" * 64)
        replacement["Id"] = "b" * 64
        rows["b" * 64] = replacement
        await manager.tasks[SEED]
        failed = manager.saved(SEED)
        assert failed["state"] == "failed"
        assert failed["progress"] == 5
        assert not any(method != "GET" for method, _ in calls)
        review = await manager.status(SEED)
        assert review["state"] == "ready"
        assert review["installationId"] != ready["installationId"]
        await manager.remove(SEED, review["installationId"])
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


def test_seed_removal_fences_present_controller_before_client_is_created(
    logged_in, tmp_path, monkeypatch
):
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


@pytest.mark.parametrize("settings", [None, {"enabled": False}, {"enabled": True}])
def test_stopped_controller_checks_saved_settings_before_seed_removal(
    logged_in, tmp_path, monkeypatch, settings
):
    _, manager, rows, calls = setup_manager(logged_in, tmp_path, monkeypatch)
    manager.policy[VPN] = manager.policy[SEED].model_copy(update={"project": "synthetic-vpn"})
    rows["b" * 64] = {
        "Id": "b" * 64,
        "Config": {
            "Labels": {
                "com.docker.compose.project": "synthetic-vpn",
                "com.docker.compose.service": "app",
            }
        },
        "State": {"Running": False},
        "Mounts": [],
    }
    monkeypatch.setattr(manager, "controller_settings", AsyncMock(return_value=settings))
    disconnect = AsyncMock(
        side_effect=AssertionError("Stopped disabled controller needs no HTTP call")
    )
    monkeypatch.setattr(manager, "disconnect_client", disconnect)

    async def remove():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        if settings and settings["enabled"]:
            assert manager.saved(SEED)["state"] == "failed"
            assert "Start MediaVPN" in manager.saved(SEED)["message"]
            assert not any(method != "GET" for method, _ in calls)
        else:
            assert manager.saved(SEED)["state"] == "succeeded"
            assert "a" * 64 not in rows
        assert "b" * 64 in rows  # MediaVPN remains untouched.

    asyncio.run(remove())
    disconnect.assert_not_called()


@pytest.mark.parametrize(
    "content,expected",
    [(b'{"enabled":false}', False), (b'{"enabled":true}', True), (b'{"enabled":"false"}', None)],
)
def test_controller_archive_is_bounded_and_validated(
    logged_in, tmp_path, monkeypatch, content, expected
):
    import io
    import tarfile

    import httpx

    _, manager, _, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w") as archive:
        member = tarfile.TarInfo("seedbox.json")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))

    def handler(request):
        assert request.url.params["path"] == "/data/seedbox.json"
        return httpx.Response(200, content=payload.getvalue())

    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    if expected is None:
        with pytest.raises(DomainError, match="could not be verified"):
            asyncio.run(manager.controller_settings("a" * 64))
    else:
        assert asyncio.run(manager.controller_settings("a" * 64))["enabled"] is expected


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
