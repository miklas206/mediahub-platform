import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mediahub.apps.plex import PlexInstallation
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.plex_control import PlexPolicy
from agent.plex_install import PlexInstallPolicy, installation_plan, temp_choices, transcode_mount
from agent.plex_transcode import migrate, preferences, reconcile, recover
from agent.plex_transcode_worker import MARKER, prepare


def test_owned_temp_cleanup_is_scoped_and_never_runs_for_active_mode(tmp_path):
    prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0)
    root = tmp_path / "Temp/plex-main"
    session = root / "work/Transcode/Sessions/plex-transcode-abcdefgh-1234"
    session.mkdir(parents=True)
    (session / "segment.ts").write_text("temporary")
    other = root / "work/Transcode/Sessions/keep-this"
    other.mkdir()
    media = tmp_path / "movie.mkv"
    media.write_text("original")
    prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0, clean=False)
    assert session.exists()
    result = prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0, clean=True)
    assert result["removedSessions"] == 1
    assert not session.exists() and other.exists() and media.read_text() == "original"
    assert (root / MARKER).exists()


def test_unowned_nonempty_directory_and_other_installation_are_preserved(tmp_path):
    root = tmp_path / "Temp/plex-main"
    root.mkdir(parents=True)
    (root / "important.txt").write_text("preserve")
    with pytest.raises(ValueError):
        prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0, clean=True)
    (root / MARKER).write_text(
        json.dumps({"installationId": "another", "purpose": "plex-transcoding"})
    )
    with pytest.raises(ValueError):
        prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0, clean=True)
    assert (root / "important.txt").read_text() == "preserve"


def test_cleanup_does_not_follow_links(tmp_path):
    prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0)
    root = tmp_path / "Temp/plex-main"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "movie.mkv").write_text("original")
    sessions = root / "work/Transcode/Sessions"
    sessions.mkdir(parents=True)
    try:
        (sessions / "plex-transcode-abcdefgh").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit test symlinks")
    prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=0, clean=True)
    assert (outside / "movie.mkv").read_text() == "original"


def test_old_default_preferences_migrate_but_custom_path_is_preserved():
    old = b'<Preferences MachineIdentifier="same" PlexOnlineToken="secret"/>'
    updated = preferences(old, True)
    assert b'TranscoderTempDirectory="/transcode"' in updated
    assert b'MachineIdentifier="same"' in updated and b'PlexOnlineToken="secret"' in updated
    custom = preferences(b'<Preferences TranscoderTempDirectory="/custom"/>', True)
    assert b'TranscoderTempDirectory="/custom"' in custom


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    policy = PlexInstallPolicy(
        hostId="local",
        bindAddress="192.168.1.10",
        image="lscr.io/linuxserver/plex@sha256:" + "a" * 64,
        initImage="sha256:" + "b" * 64,
        storage={
            k: {"kind": k, "label": k, "path": str(tmp_path / k)} for k in ["movies", "appdata"]
        },
        hostMountSnapshot=str(tmp_path / "snapshot"),
        requiredMounts={str(tmp_path): "verified"},
        requiredFilesystemUuids={},
        storageMarkers={str(tmp_path / "marker"): "verified"},
    )
    spec = PlexInstallation(moviesStorageIds=["movies"], appdataStorageId="appdata")
    plan = installation_plan(policy, spec)
    plan["container"]["HostConfig"]["Mounts"] = [
        m for m in plan["container"]["HostConfig"]["Mounts"] if m["Target"] != "/transcode"
    ]
    plan["container"]["Env"] = [v for v in plan["container"]["Env"] if not v.startswith("TMPDIR=")]
    plan["installation"].pop("tempStorageId")
    image = "sha256:" + "c" * 64
    container = {
        "Id": "original-id",
        "Name": "/" + plan["name"],
        "Image": image,
        "State": {"Running": True},
        "Config": copy.deepcopy(plan["container"]),
    }
    container["Mounts"] = [
        {"Source": m["Source"], "Destination": m["Target"], "RW": not m["ReadOnly"]}
        for m in plan["container"]["HostConfig"]["Mounts"]
    ]
    containers = {"original-id": container}
    guard = PlexPolicy(
        hostId="local",
        container=plan["name"],
        imageId=image,
        installationId="plex-main",
        preferencesPath="/unused",
        mounts=[
            {"source": m["Source"], "target": m["Destination"], "readOnly": not m["RW"]}
            for m in container["Mounts"]
        ],
        storageMarkers=policy.storageMarkers,
        hostMountSnapshot=policy.hostMountSnapshot,
        requiredMounts=policy.requiredMounts,
    )
    policy_file = tmp_path / "policy.json"
    save_json(policy_file, guard.model_dump())
    save_json(tmp_path / "plex-plan.json", plan)
    control = SimpleNamespace(
        policy_file=policy_file,
        policy=lambda: PlexPolicy.model_validate(read_json(policy_file)),
        intent=Mock(return_value=True),
        save_intent=Mock(),
        record=Mock(),
        plex_get=AsyncMock(
            return_value=__import__("xml.etree.ElementTree", fromlist=["Element"]).Element(
                "MediaContainer", size="0"
            )
        ),
    )

    def find(name):
        return containers.get(name) or next(
            x for x in containers.values() if x["Name"] == "/" + name
        )

    async def request(method, path, body=None):
        if path == "/containers/json?all=1":
            return [{"Id": k, "Names": [v["Name"]]} for k, v in containers.items()]
        if path.startswith("/containers/create?"):
            name = path.split("name=")[1]
            containers["new-id"] = {
                "Id": "new-id",
                "Name": "/" + name,
                "Image": image,
                "State": {"Running": False},
                "Config": copy.deepcopy(body),
                "Mounts": [
                    {"Source": m["Source"], "Destination": m["Target"], "RW": not m["ReadOnly"]}
                    for m in body["HostConfig"]["Mounts"]
                ],
            }
            return {"Id": "new-id"}
        name = path.split("/")[2].split("?")[0]
        item = find(name)
        if path.endswith("/json"):
            return copy.deepcopy(item)
        if "/rename?" in path:
            item["Name"] = "/" + path.split("name=")[1]
        if "/stop?" in path:
            item["State"]["Running"] = False
        if method == "DELETE":
            del containers[item["Id"]]
        return {}

    async def inspect(p):
        return copy.deepcopy(find(p.container))

    async def stop(p):
        find(p.container)["State"]["Running"] = False

    async def start(p):
        find(p.container)["State"]["Running"] = True

    control.inspect = AsyncMock(side_effect=inspect)
    app = SimpleNamespace(
        state_dir=tmp_path,
        policy=lambda: policy,
        control=control,
        request=AsyncMock(side_effect=request),
        stop=AsyncMock(side_effect=stop),
        start=AsyncMock(side_effect=start),
        containers=containers,
        plan=plan,
        guard=guard,
    )
    monkeypatch.setattr("agent.plex_transcode.prepare", AsyncMock())
    return app


def test_existing_installation_migrates_once_without_changing_image_media_or_intent(runtime):
    old_media = [
        m
        for m in runtime.plan["container"]["HostConfig"]["Mounts"]
        if m["Target"].startswith("/media/")
    ]
    asyncio.run(migrate(runtime, runtime.guard, runtime.plan))
    plan = read_json(runtime.state_dir / "plex-plan.json")
    assert [
        m for m in plan["container"]["HostConfig"]["Mounts"] if m["Target"].startswith("/media/")
    ] == old_media
    assert plan["container"]["Image"] == runtime.guard.imageId
    assert any(m["Target"] == "/transcode" for m in plan["container"]["HostConfig"]["Mounts"])
    assert runtime.containers["new-id"]["State"]["Running"]
    assert read_json(runtime.state_dir / "plex-transcode-migration.json")["state"] == "complete"
    runtime.start.assert_awaited_once()
    asyncio.run(reconcile(runtime, runtime.control.policy()))
    runtime.start.assert_awaited_once()


def test_active_playback_defers_migration(runtime):
    import xml.etree.ElementTree as ET

    runtime.control.plex_get.return_value = ET.Element("MediaContainer", size="1")
    asyncio.run(reconcile(runtime, runtime.guard))
    runtime.stop.assert_not_awaited()
    assert runtime.transcode_status["state"] == "pending"


def test_playback_started_during_preparation_defers_replacement(runtime):
    import xml.etree.ElementTree as ET

    runtime.control.plex_get.side_effect = [
        ET.Element("MediaContainer", size="0"),  # preferences
        ET.Element("MediaContainer", size="0"),  # initial idle check
        ET.Element("MediaContainer", size="1"),  # playback began during preparation
    ]
    asyncio.run(reconcile(runtime, runtime.guard))
    runtime.stop.assert_not_awaited()
    assert list(runtime.containers) == ["original-id"]
    assert not (runtime.state_dir / "plex-transcode-migration.json").exists()


def test_existing_custom_transcode_setting_skips_automatic_migration(runtime):
    import xml.etree.ElementTree as ET

    prefs = ET.Element("MediaContainer")
    ET.SubElement(prefs, "Setting", id="TranscoderTempDirectory", value="/custom-temp")
    runtime.control.plex_get.return_value = prefs
    asyncio.run(reconcile(runtime, runtime.guard))
    runtime.stop.assert_not_awaited()
    assert runtime.transcode_status["state"] == "custom"
    assert runtime.transcode_status["path"] == "/custom-temp"


def test_failed_start_restores_original_container_and_saved_policy(runtime):
    original_policy = runtime.guard.model_dump()
    original_start = runtime.start.side_effect

    async def fail_once(p):
        if runtime.containers.get("new-id"):
            raise DomainError("synthetic_failure", "Unavailable", 503)
        await original_start(p)

    runtime.start.side_effect = fail_once
    with pytest.raises(DomainError):
        asyncio.run(migrate(runtime, runtime.guard, runtime.plan))
    assert list(runtime.containers) == ["original-id"]
    assert runtime.containers["original-id"]["Name"] == "/" + runtime.guard.container
    assert runtime.containers["original-id"]["State"]["Running"]
    assert (
        read_json(runtime.state_dir / "plex-transcode-migration.json")["originalRestored"] is True
    )
    assert runtime.control.policy().model_dump() == original_policy


def test_interrupted_migration_before_rename_recovers_original_intent(runtime):
    save_json(
        runtime.state_dir / "plex-transcode-migration.json",
        {
            "state": "prepared",
            "oldPolicy": runtime.guard.model_dump(),
            "oldPlan": runtime.plan,
            "oldId": "original-id",
            "nonce": "test-nonce",
            "desiredRunning": True,
        },
    )
    asyncio.run(recover(runtime))
    assert runtime.containers["original-id"]["State"]["Running"]
    runtime.start.assert_not_awaited()
    assert (
        read_json(runtime.state_dir / "plex-transcode-migration.json")["originalRestored"] is True
    )


def test_default_temp_is_outside_media_and_can_be_selected_explicitly(runtime):
    policy = runtime.policy()
    choice = next(iter(temp_choices(policy)))
    spec = PlexInstallation(
        moviesStorageIds=["movies"], appdataStorageId="appdata", tempStorageId=choice
    )
    mount = transcode_mount(policy, spec)
    assert Path(mount["Source"]) == Path(policy.storage["appdata"].path) / "Temp/plex-main/work"
    with pytest.raises(DomainError):
        transcode_mount(policy, spec.model_copy(update={"tempStorageId": "movies"}))


def test_stopped_installation_is_migrated_without_starting_it(runtime):
    runtime.containers["original-id"]["State"]["Running"] = False
    runtime.control.intent.return_value = False
    asyncio.run(migrate(runtime, runtime.guard, runtime.plan))
    runtime.start.assert_not_awaited()
    assert not runtime.containers["new-id"]["State"]["Running"]
    runtime.control.save_intent.assert_called_with(runtime.guard, False)


def test_interruption_after_new_container_creation_is_recoverable(runtime):
    original_start = runtime.start.side_effect

    async def interrupt(p):
        raise KeyboardInterrupt("simulate Core process interruption")

    runtime.start.side_effect = interrupt
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(migrate(runtime, runtime.guard, runtime.plan))
    assert read_json(runtime.state_dir / "plex-transcode-migration.json")["state"] == "prepared"
    assert "new-id" in runtime.containers
    runtime.start.side_effect = original_start
    asyncio.run(recover(runtime))
    assert list(runtime.containers) == ["original-id"]
    assert runtime.containers["original-id"]["State"]["Running"]


def test_low_space_is_a_concrete_error_and_does_not_remove_unrelated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent.plex_transcode_worker.shutil.disk_usage", lambda _: SimpleNamespace(free=128)
    )
    outside = tmp_path / "movie.mkv"
    outside.write_text("original")
    with pytest.raises(OSError) as error:
        prepare(tmp_path, "Temp/plex-main", "plex-main", minimum_free=1024)
    assert error.value.errno == 28
    assert outside.read_text() == "original"


def test_transcode_mount_inside_media_is_rejected(runtime):
    from agent.plex_install import PlexStorageChoice

    policy = runtime.policy()
    policy.storage["bad-temp"] = PlexStorageChoice(
        kind="temp", label="bad", path=str(Path(policy.storage["movies"].path) / "Temp")
    )
    spec = PlexInstallation(
        moviesStorageIds=["movies"], appdataStorageId="appdata", tempStorageId="bad-temp"
    )
    with pytest.raises(DomainError):
        transcode_mount(policy, spec)
