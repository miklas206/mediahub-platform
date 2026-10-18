import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import mediahub.app_dependencies as dependencies
import pytest


@pytest.mark.parametrize("changed_source", [False, True])
def test_helper_inherits_only_existing_approved_core_storage(
    tmp_path, monkeypatch, changed_source
):
    approved = tmp_path / "container-apps.json"
    approved.write_text(
        json.dumps(
            {
                "requiredMounts": {"/mnt/media": "synthetic-device"},
                "hostMountSnapshot": "/host-evidence/snapshot.json",
            }
        )
    )
    real_path = dependencies.Path
    monkeypatch.setattr(
        dependencies,
        "Path",
        lambda value: approved if value == "/state/container-apps.json" else real_path(value),
    )
    policy = tmp_path / "managed.json"
    policy.write_text("{}")
    created = []
    own = {
        "HostConfig": {"GroupAdd": ["1000", "10001", "991"]},
        "Image": "sha256:synthetic",
        "Config": {
            "Labels": {
                "com.docker.compose.project": "mediahub-platform",
                "com.docker.compose.service": "core",
            }
        },
        "Mounts": [
            {"Type": "bind", "Source": "/opt/mediahub/data", "Destination": "/data"},
            {
                "Type": "bind",
                "Source": "/other" if changed_source else "/mnt/media",
                "Destination": "/mnt/media",
            },
            {"Type": "bind", "Source": "/host-evidence", "Destination": "/host-evidence"},
            {"Type": "bind", "Source": "/unapproved", "Destination": "/unapproved"},
        ],
    }

    async def docker(method, path, **kwargs):
        if path.endswith("/json") and "mediahub-app-dependencies" not in path:
            return own
        if method == "POST" and "/containers/create" in path:
            created.append(kwargs["body"])
        if method == "GET" and "mediahub-app-dependencies" in path:
            return None if kwargs.get("missing") else {"State": {"Running": False, "ExitCode": 0}}
        return {}

    svc = SimpleNamespace(
        config=SimpleNamespace(
            managed_apps_docker_socket=True,
            managed_apps_policy_file=policy,
            base_url="https://192.168.1.50:18765",
        ),
        managed_apps=SimpleNamespace(docker=docker, policy={}),
    )
    controller = dependencies.AppDependencies(svc)
    asyncio.run(controller._run())
    if changed_source:
        assert controller.message and not created
    else:
        assert controller.message is None
        binds = created[0]["HostConfig"]["Binds"]
        assert created[0]["HostConfig"]["GroupAdd"] == ["1000", "10001", "991"]
        assert "/mnt/media:/mnt/media:ro" in binds
        assert "/host-evidence:/host-evidence:ro" in binds
        assert not any("unapproved" in bind for bind in binds)


@pytest.mark.parametrize("failed", [False, True])
def test_preparation_refreshes_observed_versions_after_finishing(failed, monkeypatch):
    monkeypatch.setattr("mediahub.storage_control.ensure_storage", AsyncMock())
    monitor = SimpleNamespace(refresh_managed_versions=AsyncMock())
    manager = SimpleNamespace(lock=asyncio.Lock())
    controller = dependencies.AppDependencies(SimpleNamespace(updates=monitor, managed_apps=manager))
    controller._run = AsyncMock()
    controller.message = "Preparation failed" if failed else None
    asyncio.run(controller.run())
    monitor.refresh_managed_versions.assert_awaited_once_with("failed" if failed else "ready")
