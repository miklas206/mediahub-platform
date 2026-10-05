import asyncio
import io
import tarfile
from types import SimpleNamespace

import pytest
from mediahub.errors import DomainError

from agent.plex_runtime import PlexRuntime


def archive(content, kind=tarfile.REGTYPE):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as stream:
        entry = tarfile.TarInfo("Preferences.xml")
        entry.size, entry.type = len(content), kind
        stream.addfile(entry, io.BytesIO(content))
    return output.getvalue()


def test_preferences_are_encrypted_and_not_public(tmp_path):
    runtime = PlexRuntime(None, None, tmp_path)
    secret = b'<Preferences PlexOnlineToken="unit-test-private-token" />'

    async def request(*args, **kwargs):
        if args[1].startswith("/exec/") and args[1].endswith("/json"):
            return {"ExitCode": 0}
        if args[1].endswith("/json"):
            return {"State": {"Running": True}}
        if args[1].endswith("/exec"):
            return {"Id": "test-exec"}
        return b"\x01\0\0\0" + len(secret).to_bytes(4, "big") + secret

    runtime.request = request
    policy = SimpleNamespace(container="test-plex", installationId="plex-test")
    asyncio.run(runtime.checkpoint(policy))
    assert runtime.vault.get("plex-test") == secret
    for path in (tmp_path / "plex-secrets").iterdir():
        assert b"unit-test-private-token" not in path.read_bytes()
    secret = b'<Preferences PlexOnlineToken="rotated-private-token" />'
    asyncio.run(runtime.checkpoint(policy))
    assert runtime.vault.get("plex-test") == secret


@pytest.mark.parametrize(
    "content",
    [
        b"broken XML",
        b"<NotPreferences/>",
        b"",
        b"x" * 131073,
    ],
    ids=["invalid-xml", "wrong-root", "empty", "oversize"],
)
def test_preferences_reject_invalid_runtime_output(tmp_path, content):
    runtime = PlexRuntime(None, None, tmp_path)

    async def request(*args, **kwargs):
        if args[1].startswith("/exec/") and args[1].endswith("/json"):
            return {"ExitCode": 0}
        if args[1].endswith("/json"):
            return {"State": {"Running": True}}
        if args[1].endswith("/exec"):
            return {"Id": "test-exec"}
        return b"\x01\0\0\0" + len(content).to_bytes(4, "big") + content

    runtime.request = request
    with pytest.raises(DomainError):
        asyncio.run(runtime.preferences(SimpleNamespace(container="test-plex")))


def test_restore_tar_has_private_permissions(tmp_path):
    runtime = PlexRuntime(None, None, tmp_path)
    seen = []

    async def request(*args, **kwargs):
        with tarfile.open(fileobj=io.BytesIO(kwargs["payload"])) as stream:
            seen.extend(stream.getmembers())

    runtime.request = request
    asyncio.run(runtime.archive_write("test-helper", {"Preferences.xml": b"test"}, 1000, 1000))
    assert len(seen) == 1
    assert seen[0].mode == 0o600
    assert seen[0].uid == seen[0].gid == 1000


@pytest.mark.parametrize("new_image", [False, True])
def test_update_check_uses_publisher_digest_without_mutation(tmp_path, new_image):
    from unittest.mock import AsyncMock

    installed = "sha256:" + "a" * 64
    latest = "sha256:" + ("b" if new_image else "a") * 64
    image = "lscr.io/linuxserver/plex@" + installed
    policy = SimpleNamespace(imageId="sha256:" + "c" * 64)
    control = SimpleNamespace(
        policy=lambda: policy,
        lock=asyncio.Lock(),
        inspect=AsyncMock(return_value={"Config": {"Image": image}}),
        plex_get=AsyncMock(),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.request = AsyncMock(
        side_effect=[
            {"RepoDigests": [image], "Os": "linux", "Architecture": "amd64"},
            {
                "Descriptor": {
                    "digest": latest,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                },
                "Platforms": [{"os": "linux", "architecture": "amd64"}],
            },
            {
                "Descriptor": {
                    "digest": installed,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                }
            },
        ]
    )
    result = asyncio.run(runtime.update_check())
    assert result["supported"] is True
    assert result["updateAvailable"] is new_image
    assert result["updateSource"] == "container-image"
    assert result["installedVersion"] == installed
    assert result["latestVersion"] == latest
    assert not result["downloadRequested"] and not result["installationRequested"]
    assert all(call.args[0] == "GET" for call in runtime.request.call_args_list)
    assert (
        runtime.request.call_args_list[1].args[1]
        == "/distribution/lscr.io/linuxserver/plex:latest/json"
    )
    control.plex_get.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        "unsupported",
        "unknown-installed",
        "unknown-latest",
        "incompatible",
        "unavailable",
        "manifest-mismatch",
        "missing-platform",
    ],
)
def test_update_check_unknown_or_unsupported_cannot_enable_update(tmp_path, case):
    from unittest.mock import AsyncMock

    image = "lscr.io/linuxserver/plex@sha256:" + "a" * 64
    control = SimpleNamespace(
        policy=lambda: SimpleNamespace(imageId="sha256:" + "c" * 64),
        lock=asyncio.Lock(),
        inspect=AsyncMock(
            return_value={"Config": {"Image": "other:latest" if case == "unsupported" else image}}
        ),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.request = AsyncMock(
        side_effect=[
            {
                "RepoDigests": [] if case == "unknown-installed" else [image],
                "Os": "linux",
                "Architecture": "amd64",
            },
            DomainError("plex_provision_failed", "Unavailable", 503)
            if case == "unavailable"
            else {
                "Descriptor": {
                    "digest": "unknown" if case == "unknown-latest" else "sha256:" + "b" * 64,
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                },
                "Platforms": []
                if case == "missing-platform"
                else [
                    {"os": "linux", "architecture": "arm64" if case == "incompatible" else "amd64"}
                ],
            },
            {
                "Descriptor": {
                    "digest": "sha256:" + "a" * 64,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                }
            },
        ]
    )
    if case in ("unknown-latest", "unavailable"):
        with pytest.raises(DomainError):
            asyncio.run(runtime.update_check())
    else:
        result = asyncio.run(runtime.update_check())
        assert result["supported"] is False
        assert result["updateAvailable"] is False
        assert result["reason"]
    assert all(call.args[0] == "GET" for call in runtime.request.call_args_list)


def test_update_same_image_does_not_stop_restart_or_snapshot(tmp_path):
    from unittest.mock import AsyncMock, Mock

    policy = SimpleNamespace(imageId="sha256:" + "a" * 64)
    control = SimpleNamespace(
        policy=lambda: policy,
        lock=asyncio.Lock(),
        inspect=AsyncMock(return_value={"State": {"Running": True}}),
        storage_verified=AsyncMock(return_value=True),
        save_intent=Mock(),
    )
    runtime = PlexRuntime(control, None, tmp_path)
    runtime.pull_image = AsyncMock(return_value={"Id": policy.imageId})
    runtime.stop = AsyncMock()
    runtime.start = AsyncMock()
    runtime.snapshot_appdata = AsyncMock()
    runtime.request = AsyncMock()
    asyncio.run(runtime._update())
    assert runtime.operation == {"state": "succeeded", "message": "Plex is already up to date"}
    runtime.stop.assert_not_called()
    runtime.start.assert_not_called()
    runtime.snapshot_appdata.assert_not_called()
    runtime.request.assert_not_called()
    control.save_intent.assert_not_called()


def test_concurrent_updates_admit_only_one_background_transaction(tmp_path):
    from unittest.mock import AsyncMock

    async def scenario():
        inspected = 0
        both_entered = asyncio.Event()
        finish = asyncio.Event()

        async def inspect(_):
            nonlocal inspected
            inspected += 1
            if inspected == 2:
                both_entered.set()
            await both_entered.wait()
            return {}

        async def transaction():
            await finish.wait()

        control = SimpleNamespace(policy=lambda: None, inspect=inspect)
        runtime = PlexRuntime(control, None, tmp_path)
        runtime._update = AsyncMock(side_effect=transaction)
        results = await asyncio.gather(runtime.update(), runtime.update(), return_exceptions=True)
        assert (
            sum(
                isinstance(result, DomainError) and result.code == "plex_busy" for result in results
            )
            == 1
        )
        assert sum(isinstance(result, dict) for result in results) == 1
        finish.set()
        await runtime.update_task
        runtime._update.assert_awaited_once()

    asyncio.run(scenario())
