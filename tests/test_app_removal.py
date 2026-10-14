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


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("partial", ["none", "helper", "container", "foreign", "foreign-name"])
def test_failed_plex_install_can_be_removed_without_managed_policy(tmp_path, partial, managed):
    from agent.install_files import save_json

    async def run():
        control = SimpleNamespace(policy_file=tmp_path / "missing-policy.json", lock=asyncio.Lock())
        if managed:
            control.policy_file.write_text("retained policy")
            control.policy = lambda: SimpleNamespace(installationId="plex-test", vpnEnabled=False)
            control.save_intent = MagicMock()
        operation = {
            "action": "install",
            "state": "failed",
            "hostId": "local",
            "installationId": "plex-test",
        }
        save_json(tmp_path / "plex-install-operation.json", operation)
        runtime = PlexRuntime(control, None, tmp_path)
        runtime.policy = lambda: SimpleNamespace(hostId="local")
        persistent = tmp_path / "media-and-appdata"
        persistent.write_bytes(b"keep existing data")
        container = {
            "Id": "a" * 64,
            "Name": "/mediahub-plex-test" + ("-prepare" if partial == "helper" else ""),
            "Config": {
                "Labels": {
                    "org.mediahub.installation": "other" if partial == "foreign" else "plex-test",
                    "org.mediahub.package": "org.mediahub.plex",
                }
            },
            "State": {"Running": True},
        }
        if partial == "foreign-name":
            container["Name"] = "/unrelated-app"
        if managed:
            control.inspect = AsyncMock(return_value=container)
            runtime.checkpoint = AsyncMock()
        remaining = [] if partial == "none" else [container]
        mutations = []

        async def request(method, path, **kwargs):
            if method == "GET" and path.startswith("/containers/json?"):
                return [{"Id": item["Id"]} for item in remaining]
            if method == "GET" and path.endswith("/json"):
                return container
            mutations.append((method, path))
            if method == "DELETE":
                remaining.clear()
            return {}

        runtime.request = request
        assert (await runtime.uninstall_status())["installationId"] == "plex-test"
        with pytest.raises(DomainError, match="Exact installation confirmation"):
            await runtime.uninstall("wrong")
        assert mutations == []
        await runtime.uninstall("plex-test")
        await runtime.update_task
        if partial in {"foreign", "foreign-name"}:
            assert runtime.operation["state"] == "failed"
            assert mutations == []
        else:
            assert runtime.operation["state"] == "succeeded"
            report = await runtime.uninstall_status()
            assert report == {
                "state": "succeeded",
                "installationId": "plex-test",
                "dataPreserved": True,
            }
            assert all(
                "/containers/" in path and "v=false" in path
                for method, path in mutations
                if method == "DELETE"
            )
            restarted = PlexRuntime(control, None, tmp_path)
            restarted.policy = runtime.policy
            restarted.request = request
            assert (await restarted.uninstall_status())["state"] == "succeeded"
            if managed and partial == "container":
                control.inspect.assert_awaited_once()
                runtime.checkpoint.assert_awaited_once()
        assert persistent.read_bytes() == b"keep existing data"

    asyncio.run(run())


def test_failed_plex_removal_does_not_guess_identity_or_interrupt_installer(tmp_path):
    async def run():
        control = SimpleNamespace(
            policy_file=tmp_path / "missing.json",
            lock=asyncio.Lock(),
            policy=lambda: (_ for _ in ()).throw(DomainError("plex_disabled", "Unavailable", 503)),
        )
        runtime = PlexRuntime(control, None, tmp_path)
        runtime.policy = lambda: SimpleNamespace(hostId="local")
        runtime.request = AsyncMock()
        with pytest.raises(DomainError):
            await runtime.uninstall_status()
        runtime.operation = {
            "state": "running",
            "action": "install",
            "hostId": "local",
            "installationId": "plex-test",
        }
        with pytest.raises(DomainError, match="Another Plex operation"):
            await runtime.uninstall("plex-test")
        runtime.request.assert_not_awaited()

    asyncio.run(run())


def test_peer_removal_must_succeed_before_forgetting_app_binding(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        app = InstalledApp(
            package_id="org.mediahub.jellyfin",
            name="Jellyfin",
            version="unknown",
            state="removing",
            is_mock=False,
        )
        db.add(app)
        db.flush()
        identifier = app.id
        db.add(
            Setting(
                key="container_installation_jellyfin",
                value={"hostId": "local", "installationId": "mediahub-jellyfin"},
            )
        )
    agent = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "state": "succeeded",
                "installationId": "mediahub-jellyfin",
                "dataPreserved": True,
            }
        )
    )
    monkeypatch.setattr(svc.hosts, "client", lambda host: agent)
    register_remote_apps(svc)
    forget = AsyncMock(side_effect=DomainError("vpn_unavailable", "VPN unavailable", 503))
    monkeypatch.setattr(svc.shared_vpn, "forget_peer", forget)
    endpoint = "/api/v1/apps/" + identifier + "/uninstall"
    assert logged_in.get(endpoint).status_code == 503
    assert svc.apps.get(identifier)["state"] == "removing"
    with svc.sessions() as db:
        assert (
            db.scalar(select(Setting).where(Setting.key == "container_installation_jellyfin"))
            is not None
        )
    forget.side_effect = None
    assert logged_in.get(endpoint).status_code == 200
    assert svc.apps.get(identifier)["state"] == "uninstalled"
    forget.assert_awaited_with("org.mediahub.jellyfin", "local")
