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
