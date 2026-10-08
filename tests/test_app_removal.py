import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mediahub.apps.cloudflared import register_cloudflared_app
from mediahub.apps.remote_registry import register_remote_apps
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError
from sqlalchemy import select

from agent.plex_runtime import PlexRuntime


def test_cloudflare_removes_only_monitoring(logged_in):
    svc = logged_in.app.state.services
    svc.cloudflare_tunnel.configure(
        {"status_url": "http://192.168.1.2:20242/status", "public_hostnames": "app.example.test"}
    )
    register_cloudflared_app(svc)
    app = next(a for a in svc.apps.list() if a["packageId"] == "org.mediahub.cloudflared")
    path = "/api/v1/apps/" + app["id"] + "/uninstall"
    assert logged_in.post(path, json={"confirmedInstallationId": "wrong"}).status_code == 409
    response = logged_in.post(path, json={"confirmedInstallationId": app["id"]})
    assert response.status_code == 200
    assert response.json()["data"]["dataPreserved"]
    assert not svc.cloudflare_tunnel.status_url and not svc.cloudflare_tunnel.probe_urls
    register_cloudflared_app(svc)
    assert not any(a["id"] == app["id"] for a in svc.apps.list())


def test_remote_removal_keeps_registration_until_confirmed(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        app = InstalledApp(
            package_id="org.mediahub.seedbox",
            name="Seedbox",
            version="1",
            state="running",
            is_mock=False,
        )
        db.add(app)
        db.flush()
        aid = app.id
        db.add(
            Setting(
                key="seedbox_installation",
                value={"hostId": "test", "installationId": "seedbox-test"},
            )
        )
    agent = SimpleNamespace(
        request=AsyncMock(return_value={"state": "ready", "installationId": "seedbox-test"})
    )
    monkeypatch.setattr(svc.hosts, "client", lambda _: agent)
    register_remote_apps(svc)
    path = "/api/v1/apps/" + aid + "/uninstall"
    assert logged_in.post(path, json={"confirmedInstallationId": "wrong"}).status_code == 409
    agent.request.side_effect = [
        {"state": "ready", "installationId": "seedbox-test"},
        {"state": "accepted"},
    ]
    assert logged_in.post(path, json={"confirmedInstallationId": "seedbox-test"}).status_code == 200
    assert svc.apps.get(aid)["state"] == "removing"
    agent.request.side_effect = None
    agent.request.return_value = {"state": "failed", "installationId": "seedbox-test"}
    assert logged_in.get(path).status_code == 200
    assert any(a["id"] == aid for a in svc.apps.list())
    agent.request.return_value = {"state": "succeeded", "installationId": "seedbox-test"}
    assert logged_in.get(path).status_code == 409
    assert any(a["id"] == aid for a in svc.apps.list())
    agent.request.return_value = {
        "state": "succeeded",
        "installationId": "seedbox-test",
        "dataPreserved": True,
    }
    assert logged_in.get(path).status_code == 200
    assert not any(a["id"] == aid for a in svc.apps.list())
    with svc.sessions() as db:
        assert db.scalar(select(Setting).where(Setting.key == "seedbox_installation")) is None


def test_plex_removal_verifies_ownership_and_keeps_data(tmp_path):
    async def run():
        policy = SimpleNamespace(installationId="plex-test", vpnEnabled=False)
        control = SimpleNamespace(
            policy=lambda: policy,
            lock=asyncio.Lock(),
            inspect=AsyncMock(return_value={"Id": "owned-id", "State": {"Running": True}}),
            save_intent=MagicMock(),
            record=MagicMock(),
        )
        runtime = PlexRuntime(control, None, tmp_path)
        runtime.request = AsyncMock(return_value={})
        runtime.checkpoint = AsyncMock()
        with pytest.raises(DomainError):
            await runtime.uninstall("wrong")
        assert not control.inspect.called
        await runtime.uninstall("plex-test")
        await runtime.update_task
        assert runtime.operation["state"] == "succeeded"
        assert runtime.request.await_args_list[1].args == (
            "DELETE",
            "/containers/owned-id?force=false&v=false",
        )
        control.save_intent.assert_called_once_with(policy, False)
        assert (tmp_path / "plex-removal.json").exists()

    asyncio.run(run())


def test_plex_ownership_failure_never_deletes(tmp_path):
    async def run():
        policy = SimpleNamespace(installationId="plex-test", vpnEnabled=False)
        control = SimpleNamespace(
            policy=lambda: policy,
            lock=asyncio.Lock(),
            inspect=AsyncMock(side_effect=DomainError("ownership", "Mismatch", 409)),
            save_intent=MagicMock(),
            record=MagicMock(),
        )
        runtime = PlexRuntime(control, None, tmp_path)
        runtime.request = AsyncMock()
        await runtime.uninstall("plex-test")
        await runtime.update_task
        assert runtime.operation["state"] == "failed"
        runtime.request.assert_not_called()

    asyncio.run(run())
