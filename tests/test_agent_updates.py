import asyncio
import hashlib
import io
import json
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub import agent_update_worker as worker
from mediahub.agent_updates import AgentUpdates, SSHSetup
from mediahub.errors import DomainError


def test_pairing_identity_is_required_and_ambiguous_matches_rejected():
    row = {"Id": "one", "Config": {"Env": ["MEDIAHUB_AGENT_TOKEN_FILE=/state/token"]}}
    assert worker.select_agent([row], "digest", lambda *args: "digest") == row
    with pytest.raises(ValueError):
        worker.select_agent([row], "other", lambda *args: "digest")
    with pytest.raises(ValueError):
        worker.select_agent([row, row], "digest", lambda *args: "digest")


@pytest.mark.parametrize(
    "name,kind", [("../escape", "file"), ("/escape", "file"), ("mediahub-source/link", "link")]
)
def test_archive_rejects_unsafe_members(tmp_path, name, kind):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo(name)
        if kind == "link":
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
        output.addfile(member)
    with pytest.raises(ValueError):
        worker.extract(archive, tmp_path / "out")


def test_worker_rejects_multi_file_compose():
    row = {
        "Config": {
            "Labels": {
                "com.docker.compose.service": "agent",
                "com.docker.compose.project": "test",
                "com.docker.compose.project.config_files": "/one,/two",
            }
        }
    }
    with pytest.raises(ValueError):
        worker.plan(row, {"services": {"agent": {}}})


@pytest.mark.parametrize("accepted,build_fails", [(True, False), (False, False), (False, True)])
def test_worker_only_replaces_agent_and_rolls_back_without_verification(
    tmp_path, monkeypatch, accepted, build_fails
):
    monkeypatch.setitem(
        sys.modules, "fcntl", SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)
    )
    monkeypatch.setattr(worker.os, "umask", lambda *args: None)
    root = tmp_path / "job"
    root.mkdir()
    config_path = tmp_path / "compose.json"
    config = {
        "services": {
            "agent": {"image": "old-agent", "volumes": ["data:/state"]},
            "vpn": {"image": "vpn:original"},
            "torrent": {"image": "qbit:original"},
        }
    }
    original = json.dumps(config).encode()
    config_path.write_bytes(original)
    archive = root / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("mediahub-source/docker/Agent.Dockerfile")
        member.size = 4
        output.addfile(member, io.BytesIO(b"test"))
    manifest = {
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "commit": "a" * 40,
        "tokenDigest": "match",
    }
    (root / "manifest.json").write_text(json.dumps(manifest))
    if accepted:
        (root / "accepted").write_text("a" * 40)
    row = {
        "Id": "agent-id",
        "Config": {
            "Env": ["MEDIAHUB_AGENT_TOKEN_FILE=/state/token"],
            "Labels": {
                "com.docker.compose.service": "agent",
                "com.docker.compose.project": "test",
                "com.docker.compose.project.config_files": str(config_path),
            },
        },
    }
    commands = []

    def run(*args):
        commands.append(args)
        if args[:3] == ("docker", "ps", "-q"):
            return "agent-id"
        if args[:2] == ("docker", "inspect"):
            return json.dumps([row])
        if args[:2] == ("docker", "exec"):
            return "match"
        if "config" in args:
            return json.dumps(config)
        if args[:3] == ("docker", "image", "inspect"):
            return "sha256:new-image"
        return ""

    monkeypatch.setattr(worker, "run", run)

    def build(*args, **kwargs):
        if build_fails:
            raise RuntimeError("build failed")

    monkeypatch.setattr(worker.subprocess, "run", build)
    clock = iter(range(0, 10000, 200)) if not accepted else iter(range(10000))
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(worker.time, "sleep", lambda *args: None)
    worker.main(root)
    state = json.loads((root / "status.json").read_text())
    assert state["state"] == (
        "failed" if build_fails else "succeeded" if accepted else "rolled_back"
    )
    current = json.loads(config_path.read_text())
    assert current["services"]["vpn"] == config["services"]["vpn"]
    assert current["services"]["torrent"] == config["services"]["torrent"]
    ups = [args for args in commands if "up" in args]
    assert len(ups) == (0 if build_fails else 1 if accepted else 2)
    assert all(args[-1] == "agent" and "--no-deps" in args for args in ups)
    if not accepted:
        assert config_path.read_bytes() == original
    else:
        assert current["services"]["agent"]["image"] == "sha256:new-image"
    assert (root / "compose.backup").read_bytes() == original


def test_check_uses_remote_commit_not_core_version(logged_in, monkeypatch):
    updater = logged_in.app.state.services.agent_updates
    remote = SimpleNamespace(
        request=AsyncMock(return_value={"version": "0.4.3", "sourceCommit": "b" * 40})
    )
    monkeypatch.setattr(
        updater, "binding", lambda: ("remote", remote, SimpleNamespace(host="192.168.1.20"))
    )

    async def check(provider, *args):
        assert provider.commit == "b" * 40
        return {"latestCommit": "c" * 40, "updateAvailable": True}

    monkeypatch.setattr("mediahub.agent_updates.GitHubSourceProvider.check", check)
    result = asyncio.run(updater.check())
    assert result["installedVersion"] == "b" * 40
    assert result["host"] == "192.168.1.20"
    assert not result["installReady"]


def test_ssh_preparation_requires_https(logged_in):
    response = logged_in.post(
        "/api/v1/updates/seedbox-agent/prepare",
        json={"port": 22, "fingerprint": "SHA256:" + "a" * 43, "password": "not-a-real-password"},
    )
    assert response.status_code == 403
    assert "not-a-real-password" not in response.text


def test_start_requires_prepared_credentials_and_does_not_launch(logged_in, monkeypatch):
    updater = logged_in.app.state.services.agent_updates
    monkeypatch.setattr(updater, "check", AsyncMock(return_value={"updateAvailable": True}))
    monkeypatch.setattr(updater, "binding", lambda: ("remote", None, None))
    with pytest.raises(DomainError, match="Prepare"):
        asyncio.run(updater.start())
    assert updater.operation()["state"] == "idle"


def test_prepared_credentials_are_host_bound_and_expire(logged_in, monkeypatch):
    updater = logged_in.app.state.services.agent_updates
    secret = SSHSetup(password="private", fingerprint="SHA256:" + "a" * 43)
    updater.prepared = ("remote", 100, secret)
    monkeypatch.setattr("mediahub.agent_updates.time.monotonic", lambda: 99)
    assert updater.ready("remote")
    assert not updater.ready("other")
    monkeypatch.setattr("mediahub.agent_updates.time.monotonic", lambda: 101)
    assert not updater.ready("remote")
    assert updater.prepared is None
    assert "private" not in json.dumps(updater.operation())


def test_check_all_includes_agent_update(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    monkeypatch.setattr(
        svc.updates, "check_platform", AsyncMock(return_value={"updateAvailable": False})
    )
    monkeypatch.setattr(
        svc.agent_updates,
        "check",
        AsyncMock(
            return_value={
                "installedVersion": "old",
                "latestCommit": "a" * 40,
                "updateAvailable": True,
            }
        ),
    )
    summary = asyncio.run(svc.updates.check_all())
    item = next(row for row in summary["items"] if row["id"] == "seedbox-agent")
    assert item["latestVersion"] == "a" * 40
    assert item["updateAvailable"]
    assert summary["count"] >= 1


def test_remembered_ssh_is_encrypted_bound_to_host_and_survives_restart(logged_in, monkeypatch):
    from mediahub.agent_updates import SSH_KEY
    from mediahub.db import Setting
    from sqlalchemy import select

    svc = logged_in.app.state.services
    updater = svc.agent_updates
    address = SimpleNamespace(host="192.168.1.20")
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", None, address))
    from unittest.mock import Mock

    connection = Mock()
    monkeypatch.setattr(updater, "connect", lambda *args: connection)
    setup = SSHSetup(
        password="example-private-password", fingerprint="SHA256:" + "a" * 43, remember=True
    )
    result = updater.prepare(setup)
    assert result["credentialsStored"]
    assert "example-private-password" not in json.dumps(result)
    with svc.sessions() as db:
        stored = db.scalar(select(Setting).where(Setting.key == SSH_KEY)).value
        assert "example-private-password" not in json.dumps(stored)
        assert "fingerprint" not in stored
    restarted = AgentUpdates(svc)
    restored = restarted.saved_setup("seedbox", address)
    assert restored.password.get_secret_value() == "example-private-password"
    assert restored.fingerprint == setup.fingerprint
    assert restarted.saved_setup("other", address) is None
    assert restarted.saved_setup("seedbox", SimpleNamespace(host="192.168.1.21")) is None
    restarted.forget_setup()
    assert restarted.saved_setup("seedbox", address) is None


def test_failed_ssh_verification_does_not_save_password(logged_in, monkeypatch):
    updater = logged_in.app.state.services.agent_updates
    address = SimpleNamespace(host="192.168.1.20")
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", None, address))

    def fail(*args):
        raise DomainError("agent_ssh_failed", "Rejected", 409)

    monkeypatch.setattr(updater, "connect", fail)
    with pytest.raises(DomainError):
        updater.prepare(SSHSetup(password="wrong", fingerprint="SHA256:" + "a" * 43, remember=True))
    assert updater.saved_setup("seedbox", address) is None


def test_saved_access_enables_update_without_new_password(logged_in, monkeypatch):
    updater = logged_in.app.state.services.agent_updates
    address = SimpleNamespace(host="192.168.1.20")
    remote = SimpleNamespace(request=AsyncMock(return_value={"version": "0.4.3"}))
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", remote, address))
    updater.save_setup(
        "seedbox",
        address,
        SSHSetup(password="saved-private", fingerprint="SHA256:" + "a" * 43, remember=True),
    )
    monkeypatch.setattr(
        "mediahub.agent_updates.GitHubSourceProvider.check",
        AsyncMock(return_value={"latestCommit": "a" * 40, "updateAvailable": True}),
    )
    checked = asyncio.run(updater.check())
    assert checked["installReady"] and checked["credentialsStored"]
    assert "saved-private" not in json.dumps(checked)
    from unittest.mock import Mock

    thread = Mock()
    monkeypatch.setattr("mediahub.agent_updates.threading.Thread", thread)
    job = asyncio.run(updater.start())
    assert job["state"] == "running"
    assert thread.call_args.kwargs["args"][-1].password.get_secret_value() == "saved-private"
    thread.return_value.start.assert_called_once()
    assert "saved-private" not in json.dumps(updater.operation())
    assert updater.saved_setup("seedbox", address) is not None
