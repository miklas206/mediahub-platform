import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from mediahub.db import InstalledApp
from mediahub.errors import DomainError
from mediahub.managed_apps import Installation
from sqlalchemy import select

PACKAGE = "org.mediahub.mediavpn"


def prepare(logged_in, tmp_path, monkeypatch):
    svc = logged_in.app.state.services
    spec = {
        "Image": "sha256:" + "a" * 64,
        "Env": ["SECRET=private"],
        "User": "10001",
        "Labels": {"com.docker.compose.project": "approved-app"},
        "HostConfig": {"Binds": ["kept-data:/data"]},
    }
    recipe = {
        "packageId": PACKAGE,
        "installationId": "synthetic-installation",
        "containers": [
            {
                "name": "approved-app-1",
                "spec": spec,
                "volumes": ["kept-data"],
                "networks": ["approved-net"],
            }
        ],
    }
    path = tmp_path / "install.json"
    path.write_text(json.dumps(recipe))
    svc.managed_apps.policy[PACKAGE] = Installation(
        installationId="synthetic-installation", project="approved-app", installFile=path
    )
    svc.config.sso_app_urls[PACKAGE] = "https://vpn.example"
    monkeypatch.setattr(svc.managed_apps, "docker", AsyncMock(return_value={}))
    monkeypatch.setattr(svc.managed_apps, "containers", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc.managed_apps, "initialize", AsyncMock())
    return svc, svc.managed_installer, recipe


def test_plan_exposes_no_recipe_or_secrets_and_requires_approval(logged_in, tmp_path, monkeypatch):
    svc, installer, recipe = prepare(logged_in, tmp_path, monkeypatch)
    response = logged_in.get("/api/v1/managed-install/" + PACKAGE)
    assert response.status_code == 200
    assert "SECRET" not in response.text and "kept-data" not in response.text
    with pytest.raises(DomainError):
        asyncio.run(installer.install(PACKAGE, "0" * 64))
    assert not installer.journal(PACKAGE).exists()
    svc.config.sso_app_urls.clear()
    assert logged_in.get("/api/v1/managed-install/" + PACKAGE).status_code == 409


@pytest.mark.parametrize("existing", [False, True])
def test_install_reuses_approved_data_and_clears_removal_state(
    logged_in, tmp_path, monkeypatch, existing
):
    svc, installer, recipe = prepare(logged_in, tmp_path, monkeypatch)
    spec = recipe["containers"][0]["spec"]
    container = {
        "Id": "owned",
        "Image": spec["Image"],
        "Config": spec,
        "HostConfig": spec["HostConfig"],
        "State": {"Running": False},
    }
    calls = []

    async def docker(method, path, missing=False, body=None):
        calls.append((method, path, body))
        if path.startswith("/containers/") and path.endswith("/json"):
            return deepcopy(container) if existing else None
        return {}

    monkeypatch.setattr(svc.managed_apps, "docker", docker)
    monkeypatch.setattr(
        svc.managed_apps, "containers", AsyncMock(return_value=[{"State": {"Running": True}}])
    )
    svc.managed_apps.journal(PACKAGE).write_text(json.dumps({"state": "succeeded"}))

    async def run():
        digest = (await installer.plan(PACKAGE))["planDigest"]
        await installer.install(PACKAGE, digest)
        await svc.managed_apps.tasks[PACKAGE]

    asyncio.run(run())
    assert installer.status(PACKAGE)["state"] == "succeeded"
    assert not svc.managed_apps.journal(PACKAGE).exists()
    assert not any(
        method == "DELETE" or path.startswith("/volumes/create") for method, path, _ in calls
    )
    creations = [body for method, path, body in calls if path.startswith("/containers/create")]
    assert creations == ([] if existing else [spec])
    assert "SECRET" not in installer.journal(PACKAGE).read_text()
    with svc.sessions() as db:
        assert (
            db.scalar(select(InstalledApp).where(InstalledApp.package_id == PACKAGE)).state
            == "running"
        )


def test_foreign_container_blocks_install_without_mutations(logged_in, tmp_path, monkeypatch):
    svc, installer, recipe = prepare(logged_in, tmp_path, monkeypatch)
    foreign = {
        "Image": recipe["containers"][0]["spec"]["Image"],
        "Config": {"Labels": {"com.docker.compose.project": "foreign"}},
        "State": {"Running": False},
    }
    docker = AsyncMock(return_value=foreign)
    monkeypatch.setattr(svc.managed_apps, "docker", docker)
    asyncio.run(installer.run(PACKAGE))
    assert installer.status(PACKAGE)["state"] == "failed"
    assert all(call.args[0] == "GET" for call in docker.await_args_list)


def test_install_requires_https_csrf_and_rejects_client_docker_specs(
    logged_in, tmp_path, monkeypatch
):
    svc, installer, recipe = prepare(logged_in, tmp_path, monkeypatch)
    endpoint = "/api/v1/managed-install/" + PACKAGE
    body = {"planDigest": (asyncio.run(installer.plan(PACKAGE)))["planDigest"]}
    assert logged_in.post(endpoint, json=body).status_code == 403
    assert (
        logged_in.post(
            "https://127.0.0.1:18765" + endpoint, json={**body, "image": "attacker"}
        ).status_code
        == 422
    )
    csrf = logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.post("https://127.0.0.1:18765" + endpoint, json=body).status_code == 403
    logged_in.headers["X-MediaHub-CSRF"] = csrf
    action = AsyncMock(return_value={"state": "accepted", "dataPreserved": True})
    monkeypatch.setattr(installer, "install", action)
    assert logged_in.post("https://127.0.0.1:18765" + endpoint, json=body).status_code == 202
    action.assert_awaited_once_with(PACKAGE, body["planDigest"])


def test_install_without_host_preparation_reports_unavailable(logged_in):
    assert logged_in.get("/api/v1/managed-install/" + PACKAGE).status_code == 409


def test_pending_operation_resumes_but_changed_recipe_requires_review(
    logged_in, tmp_path, monkeypatch
):
    svc, installer, recipe = prepare(logged_in, tmp_path, monkeypatch)
    installer.journal(PACKAGE).write_text(json.dumps({"state": "accepted", "planDigest": "0" * 64}))

    async def run():
        await installer.initialize()
        await svc.managed_apps.tasks[PACKAGE]

    asyncio.run(run())
    assert installer.status(PACKAGE)["state"] == "failed"
    svc.managed_apps.docker.assert_not_awaited()


def test_non_administrator_cannot_access_installation(logged_in, tmp_path, monkeypatch):
    from mediahub.db import User

    svc, installer, recipe = prepare(logged_in, tmp_path, monkeypatch)
    with svc.sessions.begin() as db:
        db.scalar(select(User).where(User.username == "tester")).role = "viewer"
    assert logged_in.get("/api/v1/managed-install/" + PACKAGE).status_code == 403
    svc.managed_apps.docker.assert_not_awaited()
