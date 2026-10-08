import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.apps.containers import CONTAINER_APPS, ContainerInstallation, ContainerInstallRequest
from mediahub.errors import DomainError
from pydantic import ValidationError

from agent.container_apps import ContainerApps
from agent.install_files import save_json


def test_container_app_allowlist_and_ports():
    assert set(CONTAINER_APPS) == {"jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"}
    assert len({app["port"] for app in CONTAINER_APPS.values()}) == 5


def test_prowlarr_reuses_approved_host_without_installed_plex(tmp_path, monkeypatch):
    runtime, spec = runtime_and_spec(tmp_path, "prowlarr")
    approved = json.loads(runtime.policy_file.read_text())
    approved.update(
        image="lscr.io/linuxserver/plex@sha256:" + "a" * 64,
        initImage="sha256:" + "b" * 64,
        requiredFilesystemUuids={},
    )
    approved["storage"].pop("downloads")
    approved["storage"]["other"] = {
        "label": "Other", "kind": "other", "path": str(tmp_path / "other")
    }
    runtime.policy_file.write_text(json.dumps(approved))
    runtime.approved_host_policy_file = runtime.policy_file
    runtime.policy_file = None
    options = asyncio.run(runtime.options("prowlarr"))
    assert options["hostId"] == "test"
    assert "other" not in {choice["id"] for choice in options["storage"]}
    with monkeypatch.context() as patch:
        patch.setattr(
            "agent.container_apps.os", SimpleNamespace(name="posix", geteuid=lambda: 10001)
        )
        assert runtime.policy().uid == 10001
    plan = asyncio.run(runtime.build_plan(spec))
    assert plan["container"]["HostConfig"]["PortBindings"]["9696/tcp"][0]["HostIp"] == "192.168.1.110"
    runtime.policy_file = tmp_path / "missing-explicit-policy.json"
    with pytest.raises(DomainError, match="not been configured"):
        runtime.policy()
    runtime.policy_file = None
    runtime.approved_host_policy_file.write_text("{}")
    with pytest.raises(DomainError, match="not been configured"):
        runtime.policy()


def test_installation_rejects_arbitrary_apps_fields_and_timezones():
    for values in (
        {"app": "untrusted", "hostId": "local"},
        {"app": "radarr", "hostId": "local", "image": "untrusted:latest"},
        {"app": "radarr", "hostId": "local", "timezone": "not-a-timezone"},
    ):
        with pytest.raises(ValidationError):
            ContainerInstallation(**values)


def runtime_and_spec(tmp_path, app="radarr"):
    storage = {}
    for kind in ("appdata", "movies", "tv", "downloads"):
        directory = tmp_path / kind
        directory.mkdir()
        storage[kind] = {"kind": kind, "label": kind, "path": str(directory)}
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "hostId": "test",
                "bindAddress": "192.168.1.110",
                "storage": storage,
                "hostMountSnapshot": str(tmp_path / "snapshot.json"),
                "requiredMounts": {str(tmp_path): "test-disk"},
                "storageMarkers": {"marker": "id"},
            }
        )
    )
    runtime = ContainerApps(policy, "docker.sock", tmp_path)
    runtime.storage_control.storage_verified = AsyncMock(return_value=True)
    slots = {"appdata": "appdata"}
    if app in {"radarr", "sonarr"}:
        slots.update(downloads="downloads")
        slots["movies" if app == "radarr" else "tv"] = "movies" if app == "radarr" else "tv"
    if app == "jellyfin":
        slots.update(movies="movies", tv="tv")
    return runtime, ContainerInstallation(app=app, hostId="test", storageIds=slots)


def inspected_container(plan):
    return {
        "Image": "sha256:" + "a" * 64,
        "State": {"Running": True},
        "Config": {
            "User": plan["container"]["User"],
            "Labels": {**plan["container"]["Labels"], "image.label": "value"},
        },
        "HostConfig": copy.deepcopy(plan["container"]["HostConfig"]),
        "Mounts": [
            {"Source": mount["Source"], "Destination": mount["Target"], "RW": not mount["ReadOnly"]}
            for mount in plan["container"]["HostConfig"]["Mounts"]
        ],
    }


@pytest.mark.parametrize("app", CONTAINER_APPS)
def test_plans_pin_images_and_scope_mounts(tmp_path, app):
    runtime, spec = runtime_and_spec(tmp_path, app)
    plan = asyncio.run(runtime.build_plan(spec))
    assert "@sha256:" in plan["container"]["Image"]
    host = plan["container"]["HostConfig"]
    assert (
        host["PortBindings"][str(CONTAINER_APPS[app]["port"]) + "/tcp"][0]["HostIp"]
        == "192.168.1.110"
    )
    assert host["Privileged"] is False
    assert plan["container"]["User"] == "1000:1000"
    assert not host.get("CapAdd")
    assert host["RestartPolicy"] == {"Name": "no"}
    if app == "jellyfin":
        assert all(
            mount["ReadOnly"] for mount in host["Mounts"] if mount["Target"] in {"/movies", "/tv"}
        )
    if app in {"radarr", "sonarr"}:
        assert any(mount["Target"] == "/downloads" for mount in host["Mounts"])


def test_plan_rejects_unverified_storage_wrong_host_and_mapping(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    for invalid in (
        spec.model_copy(update={"hostId": "other"}),
        spec.model_copy(update={"storageIds": {"appdata": "/etc"}}),
        spec.model_copy(update={"storageIds": {**spec.storageIds, "root": "appdata"}}),
    ):
        with pytest.raises(DomainError):
            asyncio.run(runtime.build_plan(invalid))
    runtime.storage_control.storage_verified.return_value = False
    with pytest.raises(DomainError, match="mounted"):
        asyncio.run(runtime.build_plan(spec))


def test_changed_plan_and_foreign_container_are_not_modified(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    runtime.request = AsyncMock(return_value={"Config": {"Labels": {}}})
    plan = asyncio.run(runtime.build_plan(spec))
    with pytest.raises(DomainError, match="updated plan"):
        asyncio.run(
            runtime.install(
                ContainerInstallRequest(installation=spec, confirmedPlanDigest="0" * 64)
            )
        )
    runtime.request.assert_not_called()
    with pytest.raises(DomainError, match="already in use"):
        asyncio.run(
            runtime.install(
                ContainerInstallRequest(installation=spec, confirmedPlanDigest=plan["planDigest"])
            )
        )
    assert all(call.args[0] == "GET" for call in runtime.request.call_args_list)


def test_runtime_ownership_checks_and_data_preserving_removal(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    plan = asyncio.run(runtime.build_plan(spec))
    plan["imageId"] = "sha256:" + "a" * 64
    inspected = inspected_container(plan)
    runtime.verify(inspected, plan)
    foreign = copy.deepcopy(inspected)
    foreign["Config"]["Labels"]["org.mediahub.package"] = "other"
    with pytest.raises(DomainError):
        runtime.verify(foreign, plan)
    save_json(runtime.record_path("radarr"), plan)
    runtime.request = AsyncMock(return_value=inspected)
    with pytest.raises(DomainError):
        asyncio.run(runtime.action("radarr", "uninstall", "wrong"))
    result = asyncio.run(runtime.action("radarr", "uninstall", "mediahub-radarr"))
    assert result["dataPreserved"] is True
    assert runtime.record_path("radarr").exists()
    assert runtime.request.call_args_list[-1].args == (
        "DELETE",
        "/containers/mediahub-radarr?force=false&v=false",
    )


def test_pull_failure_is_reported_without_creating_container(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    plan = asyncio.run(runtime.build_plan(spec))
    runtime.request = AsyncMock(side_effect=DomainError("failed", "pull failed", 503))
    asyncio.run(runtime.provision("radarr", plan))
    assert runtime.operations["radarr"]["state"] == "failed"
    assert runtime.request.call_count == 1


def test_uninstall_failed_installation_only_forgets_registration(tmp_path):
    runtime, _ = runtime_and_spec(tmp_path)
    runtime.request = AsyncMock()
    runtime.operations["radarr"] = {"state": "failed"}
    assert asyncio.run(runtime.action("radarr", "uninstall", "mediahub-radarr"))["dataPreserved"]
    runtime.request.assert_not_called()
    assert asyncio.run(runtime.status("radarr"))["state"] == "not-installed"
    with pytest.raises(DomainError):
        asyncio.run(runtime.action("radarr", "uninstall", "wrong"))


def test_owned_existing_container_can_resume_after_failed_install(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    plan = asyncio.run(runtime.build_plan(spec))
    plan["imageId"] = "sha256:" + "a" * 64
    inspected = inspected_container(plan)
    inspected["State"]["Running"] = False
    save_json(runtime.record_path("radarr"), plan)
    runtime.operations["radarr"] = {"state": "failed"}
    runtime.request = AsyncMock(return_value=inspected)
    result = asyncio.run(
        runtime.install(
            ContainerInstallRequest(installation=spec, confirmedPlanDigest=plan["planDigest"])
        )
    )
    assert result["state"] == "installed"
    assert runtime.request.call_args_list[-1].args == ("POST", "/containers/mediahub-radarr/start")
    assert "radarr" not in runtime.operations


def test_provision_records_ownership_before_creating_and_starting(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    plan = asyncio.run(runtime.build_plan(spec))
    calls = []

    async def request(method, path, body=None, missing=False):
        calls.append((method, path))
        if path.startswith("/images/") and method == "GET":
            return {"Id": "sha256:" + "a" * 64}
        if path == "/networks/mediahub-apps":
            return {
                "Labels": {"org.mediahub.network": "apps"},
                "Driver": "bridge",
                "Internal": False,
            }
        if path.startswith("/containers/create"):
            assert runtime.record("radarr")["desiredRunning"] is False
        if path.endswith("/json"):
            return inspected_container(plan)
        return {}

    runtime.request = request
    asyncio.run(runtime.provision("radarr", plan))
    assert runtime.operations["radarr"]["state"] == "installed"
    assert runtime.record("radarr")["desiredRunning"] is True
    assert calls[-1] == ("POST", "/containers/mediahub-radarr/start")


def test_container_api_requires_login_https_and_csrf(client, logged_in):
    assert client.get("/api/v1/container-apps/radarr/install-options").status_code == 403
    response = logged_in.post(
        "/api/v1/container-apps/install-plan",
        json={"app": "radarr", "hostId": "local", "storageIds": {}},
        headers={"X-MediaHub-CSRF": "wrong"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_rejected"
    response = logged_in.get("/api/v1/container-apps/radarr/install-options")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "https_required"


def test_container_api_install_registers_owning_host_and_adapter(logged_in):
    from mediahub.apps.remote_registry import register_remote_apps

    svc = logged_in.app.state.services
    agent = SimpleNamespace(
        config=SimpleNamespace(agent_url="https://192.168.1.110:18767"),
        request=AsyncMock(return_value={"state": "accepted"}),
    )
    svc.hosts.client = lambda host: agent
    spec = {"app": "prowlarr", "hostId": "approved", "storageIds": {"appdata": "config"}}
    response = logged_in.post(
        "https://127.0.0.1:18765/api/v1/container-apps/install",
        json={"installation": spec, "confirmedPlanDigest": "a" * 64},
    )
    assert response.status_code == 202
    installed = next(app for app in svc.apps.list() if app["packageId"] == "org.mediahub.prowlarr")
    assert installed["detailPath"] == "/apps/install/prowlarr"
    assert svc.apps.adapter(installed["id"]).host_id == "approved"
    register_remote_apps(svc)
    assert (
        svc.apps.adapter(installed["id"]).definition.agent_prefix == "/v1/container-apps/prowlarr"
    )
    response = logged_in.post(
        "https://127.0.0.1:18765/api/v1/container-apps/install",
        json={"installation": {**spec, "hostId": "other"}, "confirmedPlanDigest": "a" * 64},
    )
    assert response.status_code == 409
    assert agent.request.call_count == 1


def test_container_api_unauthenticated(client):
    assert client.get("/api/v1/container-apps/radarr/install-options").status_code == 401


def test_container_status_passes_shared_adapter_schema_without_claiming_health(tmp_path):
    from mediahub.apps.remote_status import RemoteStatusCache

    runtime, spec = runtime_and_spec(tmp_path)
    plan = asyncio.run(runtime.build_plan(spec))
    plan["imageId"] = "sha256:" + "a" * 64
    save_json(runtime.record_path("radarr"), plan)
    runtime.request = AsyncMock(return_value=inspected_container(plan))
    report = asyncio.run(runtime.status("radarr"))
    client = SimpleNamespace(request=AsyncMock(return_value=report))
    forwarded = asyncio.run(
        RemoteStatusCache().get("test", client, "/v1/container-apps/radarr/status")
    )
    assert forwarded["available"] is True
    assert forwarded["health"] == "unknown"
    assert forwarded["installationId"] == "mediahub-radarr"
