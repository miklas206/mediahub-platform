import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.managed_apps import ManagedApps
from test_container_apps import runtime_and_spec

from agent.app_reset import clear_directory, reset_mounts


def test_reset_removes_settings_but_keeps_infrastructure_and_external_media(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "profiles").mkdir()
    (data / "profiles" / "old.conf").write_text("private VPN setup")
    (data / "mediavpn.sqlite").write_text("old account and profile state")
    (data / "integrations").mkdir()
    (data / "integrations" / "hub.token").write_text("host provisioned identity")
    media = tmp_path / "movie.mkv"
    media.write_text("keep movie")
    clear_directory(data, keep=("integrations",))
    assert sorted(p.name for p in data.iterdir()) == ["integrations"]
    assert (data / "integrations" / "hub.token").read_text() == "host provisioned identity"
    assert media.read_text() == "keep movie"
    clear_directory(data, keep=("integrations",))  # A retried cleanup is safe.


def test_nested_mount_blocks_reset_before_deleting_files(tmp_path, monkeypatch):
    root = tmp_path / "config"
    root.mkdir()
    (root / "settings").write_text("keep until mount can be checked")
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.setattr("agent.app_reset.os.path.ismount", lambda p: p == nested)
    with pytest.raises(ValueError, match="Nested mount"):
        clear_directory(root)
    assert (root / "settings").exists()


def test_reset_rejects_volume_root():
    from pathlib import Path

    with pytest.raises(ValueError, match="Unsafe"):
        clear_directory(Path.cwd().anchor)


@pytest.mark.parametrize("app", ["jellyfin", "radarr", "sonarr", "prowlarr", "autobrr"])
def test_each_container_app_resets_only_its_approved_configuration(tmp_path, app):
    runtime, spec = runtime_and_spec(tmp_path, app)
    plan = asyncio.run(runtime.build_plan(spec))
    config = tmp_path / "appdata" / ("mediahub-" + app)
    config.mkdir()
    (config / "settings.db").write_text("old user settings")
    (tmp_path / "movies" / "movie.mkv").write_text("keep")
    (tmp_path / "downloads" / "file").write_text("keep download")
    runtime.request = AsyncMock(return_value=[])
    asyncio.run(runtime.reset_configuration(app, plan))
    assert list(config.iterdir()) == []
    assert (tmp_path / "movies" / "movie.mkv").read_text() == "keep"
    assert (tmp_path / "downloads" / "file").read_text() == "keep download"
    assert runtime.record(app)["configurationReset"] is True


def test_reset_refuses_shared_config(tmp_path):
    runtime, spec = runtime_and_spec(tmp_path)
    plan = asyncio.run(runtime.build_plan(spec))
    root = tmp_path / "appdata" / "mediahub-radarr"
    root.mkdir()
    (root / "settings").write_text("keep")
    runtime.request = AsyncMock(
        side_effect=[[{"Id": "other"}], {"Mounts": [{"Source": str(root)}]}]
    )
    with pytest.raises(DomainError, match="Another container"):
        asyncio.run(runtime.reset_configuration("radarr", plan))
    assert (root / "settings").read_text() == "keep"


def test_helper_is_isolated_and_failure_is_reported():
    request = AsyncMock(side_effect=[{"Id": "helper"}, {}, {"StatusCode": 1}, {}])
    with pytest.raises(DomainError, match="reset failed"):
        asyncio.run(
            reset_mounts(
                request,
                "sha256:" + "a" * 64,
                [{"Type": "volume", "Source": "config", "Target": "/data"}],
            )
        )
    body = request.call_args_list[0].kwargs["body"]
    compile(body["Entrypoint"][2], "<reset helper>", "exec")
    assert body["HostConfig"]["NetworkMode"] == "none"
    assert body["HostConfig"]["ReadonlyRootfs"]
    assert [m["Target"] for m in body["HostConfig"]["Mounts"]] == ["/data"]
    assert request.call_args_list[-1].args == ("DELETE", "/containers/helper?force=false&v=false")


def test_managed_reset_plan_excludes_downloads_and_tokens(tmp_path):
    package = "org.mediahub.mediaseed"

    def item(service, binds):
        return {
            "spec": {
                "Image": "sha256:" + "a" * 64,
                "Labels": {
                    "com.docker.compose.project": "owned",
                    "com.docker.compose.service": service,
                },
                "HostConfig": {"Binds": binds},
            }
        }

    recipe = {
        "installationId": "owned-installation",
        "packageId": package,
        "containers": [
            item(
                "app",
                [
                    "owned_appdata:/data:rw",
                    "owned_secrets:/secrets:ro",
                    "owned_downloads:/downloads:rw",
                    "/host/token:/vpn-auth/token:ro",
                ],
            ),
            item("qbittorrent", ["owned_config:/config:rw", "owned_downloads:/downloads:rw"]),
        ],
    }
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    manager = object.__new__(ManagedApps)
    manager.policy = {
        package: SimpleNamespace(
            installFile=path, installationId="owned-installation", project="owned"
        )
    }
    plan = manager.reset_plan(package)
    assert {m["Source"] for m in plan["mounts"]} == {
        "owned_appdata",
        "owned_secrets",
        "owned_config",
    }
    recipe["containers"][1]["spec"]["HostConfig"]["Binds"][0] = "owned_downloads:/config:rw"
    path.write_text(json.dumps(recipe))
    with pytest.raises(DomainError, match="overlaps"):
        manager.reset_plan(package)


def test_failed_reset_blocks_success_and_reinstall(logged_in, tmp_path, monkeypatch):
    from mediahub.managed_install import ManagedInstaller
    from test_managed_apps import SEED, setup_manager

    _, manager, rows, _ = setup_manager(logged_in, tmp_path, monkeypatch)
    manager.reset_configuration.side_effect = DomainError(
        "reset_failed", "Synthetic reset failure", 409
    )

    async def scenario():
        ready = await manager.status(SEED)
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert not rows
        assert (await manager.status(SEED))["state"] == "failed"
        with pytest.raises(DomainError, match="Complete app removal"):
            await ManagedInstaller(manager.svc).plan(SEED)
        manager.reset_configuration.side_effect = None
        await manager.remove(SEED, ready["installationId"])
        await manager.tasks[SEED]
        assert (await manager.status(SEED))["configurationReset"] is True

    asyncio.run(scenario())


def test_plex_reset_deletes_encrypted_preferences_and_only_selected_config(tmp_path, monkeypatch):
    from pathlib import Path

    from agent.plex_runtime import PlexRuntime

    state = tmp_path / "state"
    state.mkdir()
    config = tmp_path / "appdata" / "plex-test"
    config.mkdir(parents=True)
    (config / "Metadata").mkdir()
    (config / "Metadata" / "old.db").write_text("old library")
    movie = tmp_path / "movie.mkv"
    movie.write_text("keep")
    control = SimpleNamespace(storage_verified=AsyncMock(return_value=True))
    runtime = PlexRuntime(control, None, state)
    runtime.vault.put("plex-test", b"old encrypted preferences")
    runtime.vault.put("plex-test-rollback", b"old rollback preferences")
    runtime.policy = lambda: SimpleNamespace(
        storage={"selected": SimpleNamespace(kind="appdata", path=str(config.parent))},
        initImage="sha256:" + "a" * 64,
        uid=1000,
        gid=1000,
    )
    plan = {"installation": {"installationId": "plex-test"}, "appdataPath": str(config)}
    (state / "plex-plan.json").write_text(json.dumps(plan))
    runtime.request = AsyncMock(return_value=[])

    async def helper(request, image, mounts, **kwargs):
        assert [m["Source"] for m in mounts] == [str(config)]
        clear_directory(Path(mounts[0]["Source"]))

    monkeypatch.setattr("agent.app_reset.reset_mounts", helper)
    asyncio.run(runtime.reset_configuration("plex-test"))
    assert list(config.iterdir()) == []
    assert not runtime.vault.status("plex-test")["configured"]
    assert not runtime.vault.status("plex-test-rollback")["configured"]
    assert movie.read_text() == "keep"


def test_legacy_seedbox_reset_keeps_downloads_and_removes_private_setup(tmp_path):
    from agent.seedbox_control import SeedboxControl

    paths = SimpleNamespace(extraStorage=[])
    for field in ("appdata", "vpnState", "downloads"):
        directory = tmp_path / field
        directory.mkdir()
        (directory / "old").write_text(field)
        setattr(paths, field, str(directory))
    for name in ("vault", "secrets"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "private").write_text("old credentials")
    (tmp_path / "wizard.json").write_text("old wizard")
    policy = SimpleNamespace(workRoot=str(tmp_path), paths=paths)
    control = SeedboxControl(SimpleNamespace(policy=lambda: policy), None, None, SimpleNamespace())
    control.driver.binding = lambda: (policy, SimpleNamespace())
    control.driver.storage_guard = AsyncMock()
    control.driver.request = AsyncMock(return_value=SimpleNamespace(json=lambda: []))
    asyncio.run(control.reset_configuration())
    assert (tmp_path / "downloads" / "old").read_text() == "downloads"
    assert not list((tmp_path / "appdata").iterdir())
    assert not list((tmp_path / "vault").iterdir())
    assert not list((tmp_path / "secrets").iterdir())
    assert not (tmp_path / "wizard.json").exists()
