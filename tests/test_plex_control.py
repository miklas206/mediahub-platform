import asyncio
import json
import time

import pytest
from mediahub.errors import DomainError

from agent.plex_control import PlexControl, PlexPolicy


@pytest.fixture
def policy(tmp_path):
    marker = tmp_path / "marker"
    marker.write_text("test-filesystem")
    snapshot = tmp_path / "mounts.json"
    snapshot.write_text(
        json.dumps(
            {
                "scope": "host-mount-namespace",
                "available": True,
                "observedAt": time.time(),
                "mounts": [{"path": "/data", "source": "/dev/test"}],
            }
        )
    )
    return PlexPolicy(
        hostId="local",
        container="mediahub-plex",
        imageId="sha256:" + "a" * 64,
        installationId="plex-test",
        preferencesPath=str(tmp_path / "preferences.xml"),
        mounts=[],
        storageMarkers={str(marker): "test-filesystem"},
        hostMountSnapshot=str(snapshot),
        requiredMounts={"/data": "/dev/test"},
    )


def test_marker_alone_cannot_allow_local_fallback(policy):
    control = PlexControl(None, None)
    assert control.storage_ready(policy)
    snapshot = policy.hostMountSnapshot
    from pathlib import Path

    data = json.loads(Path(snapshot).read_text())
    data["mounts"] = []
    Path(snapshot).write_text(json.dumps(data))
    assert not control.storage_ready(policy)


@pytest.mark.parametrize("change", ["stale", "source", "missing", "scope", "duplicate"])
def test_mount_evidence_fails_closed(policy, change):
    from pathlib import Path

    snapshot = Path(policy.hostMountSnapshot)
    data = json.loads(snapshot.read_text())
    if change == "stale":
        data["observedAt"] -= 31
    if change == "source":
        data["mounts"][0]["source"] = "/dev/systemdisk"
    if change == "missing":
        data["available"] = False
    if change == "scope":
        data["scope"] = "container"
    if change == "duplicate":
        data["mounts"] *= 2
    snapshot.write_text(json.dumps(data))
    assert not PlexControl(None, None).storage_ready(policy)


def test_wrong_runtime_not_controlled(policy):
    control = PlexControl(None, None)

    async def docker(*args):
        return {"Config": {"Labels": {}}, "Image": policy.imageId, "Mounts": []}

    control.docker = docker
    with pytest.raises(DomainError) as error:
        asyncio.run(control.inspect(policy))
    assert error.value.code == "plex_ownership_mismatch"


def test_no_arbitrary_lifecycle_action():
    with pytest.raises(DomainError) as error:
        asyncio.run(PlexControl(None, None).action("delete"))
    assert error.value.code == "unsupported_action"


def test_stable_filesystem_identity_survives_device_letter_change(policy):
    from pathlib import Path

    snapshot = Path(policy.hostMountSnapshot)
    data = json.loads(snapshot.read_text())
    data["mounts"][0].update(source="/dev/sdz1", uuid="verified-filesystem")
    snapshot.write_text(json.dumps(data))
    policy.requiredMounts = {}
    policy.requiredFilesystemUuids = {"/data": "verified-filesystem"}
    assert PlexControl(None, None).storage_ready(policy)
    data["mounts"][0]["uuid"] = "system-filesystem"
    snapshot.write_text(json.dumps(data))
    assert not PlexControl(None, None).storage_ready(policy)


@pytest.mark.parametrize("action", ["start", "restart"])
def test_storage_failure_blocks_start_actions(policy, action):
    control = PlexControl(None, None)
    control.policy = lambda: policy
    control.storage_ready = lambda _: False
    calls = []

    async def inspect(_):
        return {}

    async def docker(method, path):
        calls.append((method, path))

    control.inspect = inspect
    control.docker = docker
    with pytest.raises(DomainError) as error:
        asyncio.run(control.action(action))
    assert error.value.code == "storage_unavailable"
    assert calls == []


def test_stop_remains_available_when_storage_fails(policy):
    control = PlexControl(None, None)
    control.policy = lambda: policy
    control.storage_ready = lambda _: False
    calls = []

    async def inspect(_):
        return {}

    async def docker(method, path):
        calls.append((method, path))

    control.inspect = inspect
    control.docker = docker
    result = asyncio.run(control.action("stop"))
    assert result["state"] == "accepted"
    assert calls == [("POST", "/containers/mediahub-plex/stop?t=30")]


def test_agent_shutdown_leaves_plex_and_vpn_running():
    async def scenario():
        control = PlexControl(None, None)
        calls = []
        entered = asyncio.Event()

        async def monitor():
            entered.set()
            await asyncio.Event().wait()

        async def mutation(*args):
            calls.append(args)

        control.docker = mutation
        control.runtime = type("Runtime", (), {"stop": mutation})()
        control.monitor_task = asyncio.create_task(monitor())
        await entered.wait()
        await control.close()
        assert control.monitor_task.cancelled()
        assert calls == []

    asyncio.run(scenario())


def test_update_check_never_returns_download_url_or_token(policy):
    import xml.etree.ElementTree as ET

    control = PlexControl(None, None)
    control.policy = lambda: policy
    calls = []

    async def inspect(_):
        return {}

    async def plex_get(_, endpoint, method="GET"):
        calls.append((method, endpoint))
        return ET.fromstring(
            '<MediaContainer status="checked"><Release version="1.2" downloadURL="https://example.invalid/?token=SECRET_TEST"/></MediaContainer>'
        )

    control.inspect = inspect
    control.plex_get = plex_get
    result = asyncio.run(control.update_check())
    assert calls == [("PUT", "/updater/check?download=0"), ("GET", "/updater/status")]
    assert result["releaseVersions"] == ["1.2"]
    assert not result["downloadRequested"]
    assert not result["installationRequested"]
    assert "SECRET_TEST" not in json.dumps(result)
