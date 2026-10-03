import asyncio
import hashlib
import io
import json
import os
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


@pytest.mark.skipif(sys.platform == "win32", reason="Requires POSIX directory permissions")
def test_extract_program_is_readable_with_private_worker_umask(tmp_path):
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        member = tarfile.TarInfo("mediahub-source/backend/mediahub/apps/__init__.py")
        member.mode = 0o600
        member.size = 4
        output.addfile(member, io.BytesIO(b"test"))
    target = tmp_path / "private-job"
    target.mkdir(mode=0o700)
    previous = os.umask(0o077)
    try:
        worker.extract(archive, target)
    finally:
        os.umask(previous)
    assert target.stat().st_mode & 0o777 == 0o700
    for path in (target / "mediahub-source").rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o755 if path.is_dir() else 0o644)


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


@pytest.mark.parametrize("connection_fails", [False, True])
def test_saved_fingerprint_only_changes_after_verified_connection(
    logged_in, monkeypatch, connection_fails
):
    updater = logged_in.app.state.services.agent_updates
    address = SimpleNamespace(host="192.168.1.20")
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", None, address))
    updater.save_setup(
        "seedbox",
        address,
        SSHSetup(
            password="saved-private",
            fingerprint="SHA256:" + "a" * 43,
            remember=True,
        ),
    )

    def connect(address, setup):
        assert setup.password.get_secret_value() == "saved-private"
        assert setup.fingerprint == "SHA256:" + "b" * 43
        if connection_fails:
            raise DomainError(
                "ssh_host_key_changed", "SSH fingerprint differs; no commands ran", 409
            )
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(updater, "connect", connect)
    if connection_fails:
        with pytest.raises(DomainError):
            updater.prepare_saved("SHA256:" + "b" * 43, 22)
    else:
        assert updater.prepare_saved("SHA256:" + "b" * 43, 22)["credentialsStored"]
    assert (
        updater.saved_setup("seedbox", address).fingerprint
        == "SHA256:" + ("a" if connection_fails else "b") * 43
    )


@pytest.mark.parametrize("known_error", [False, True])
def test_prelaunch_failure_reports_host_key_error_without_leaking_secrets(
    logged_in, monkeypatch, known_error
):
    updater = logged_in.app.state.services.agent_updates
    monkeypatch.setattr("mediahub.agent_updates.download_source", AsyncMock())
    monkeypatch.setattr("mediahub.agent_updates.normalize_source", lambda *args: "digest")

    def fail(*args):
        if known_error:
            raise DomainError("ssh_host_key_changed", "private-secret", 409)
        raise RuntimeError("https://example.test/?token=private-secret")

    monkeypatch.setattr(updater, "connect", fail)
    job = {"state": "running", "message": "Downloading", "logs": [], "operationId": "test"}
    updater.run(
        job,
        {"repository": "owner/repo", "latestCommit": "a" * 40},
        None,
        None,
        SSHSetup(password="private-secret", fingerprint="SHA256:" + "a" * 43),
    )
    result = updater.operation()
    assert result["state"] == "failed"
    assert result["errorCode"] == ("ssh_host_key_changed" if known_error else "agent_update_failed")
    if known_error:
        assert result["message"] == "SSH fingerprint differs; no commands ran"
        assert result["logs"] == [result["message"]]
    assert "private-secret" not in json.dumps(result)
    assert "example.test" not in json.dumps(result)


def test_saved_fingerprint_change_requires_https_and_valid_fingerprint(logged_in):
    response = logged_in.post(
        "/api/v1/updates/seedbox-agent/prepare-saved",
        json={"fingerprint": "SHA256:" + "a" * 43, "port": 22},
    )
    assert response.status_code == 403
    response = logged_in.post(
        "/api/v1/updates/seedbox-agent/prepare-saved", json={"fingerprint": "untrusted"}
    )
    assert response.status_code == 422


def test_generated_key_is_encrypted_resumable_host_bound_and_public_only(logged_in, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from mediahub.agent_updates import GENERATED_KEY
    from mediahub.db import Setting

    updater = logged_in.app.state.services.agent_updates
    address = SimpleNamespace(host="192.168.50.99")
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", None, address))
    assert not updater.generated_access()["created"]
    first = updater.generated_access(create=True)
    assert updater.generated_access(create=True) == first
    assert updater.generated_access() == first
    assert first["host"] == address.host
    assert "private" not in json.dumps(first)
    assert first["publicKey"].startswith("ssh-ed25519 ")
    assert " >> /root/.ssh/authorized_keys" in first["command"]
    assert "grep -qxF" in first["command"]
    pending = updater.generated_setup("seedbox", address)
    key = serialization.load_ssh_private_key(pending["private_key"].encode(), password=None)
    assert first["publicKey"].startswith(
        key.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )
    with updater.svc.sessions() as db:
        stored = db.scalar(
            __import__("sqlalchemy").select(Setting).where(Setting.key == GENERATED_KEY)
        ).value
        assert "OPENSSH PRIVATE KEY" not in json.dumps(stored)
        assert pending["private_key"] not in json.dumps(stored)
    assert updater.saved_setup("seedbox", address) is None
    monkeypatch.setattr(updater, "binding", lambda: ("another-host", None, address))
    assert not updater.generated_access()["created"]
    with pytest.raises(DomainError):
        updater.prepare_generated("SHA256:" + "a" * 43, 22)


@pytest.mark.parametrize("connection_fails", [False, True])
def test_generated_key_promoted_only_after_pinned_authentication(
    logged_in, monkeypatch, connection_fails
):
    updater = logged_in.app.state.services.agent_updates
    address = SimpleNamespace(host="192.168.50.99")
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", None, address))
    updater.save_setup(
        "seedbox",
        address,
        SSHSetup(
            password="previous-access",
            fingerprint="SHA256:" + "a" * 43,
            remember=True,
        ),
    )
    updater.generated_access(create=True)

    def connect(address, setup):
        assert setup.private_key is not None
        assert setup.fingerprint == "SHA256:" + "b" * 43
        if connection_fails:
            raise DomainError("ssh_host_key_changed", "Rejected", 409)
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(updater, "connect", connect)
    if connection_fails:
        with pytest.raises(DomainError):
            updater.prepare_generated("SHA256:" + "b" * 43, 22)
        assert (
            updater.saved_setup("seedbox", address).password.get_secret_value() == "previous-access"
        )
        assert updater.generated_access()["created"]
    else:
        assert updater.prepare_generated("SHA256:" + "b" * 43, 22)["credentialsStored"]
        assert updater.saved_setup("seedbox", address).private_key is not None
        assert not updater.generated_access()["created"]


def test_generated_access_api_requires_https_and_reuses_key(logged_in, monkeypatch):
    updater = logged_in.app.state.services.agent_updates
    monkeypatch.setattr(
        updater, "binding", lambda: ("seedbox", None, SimpleNamespace(host="10.0.0.42"))
    )
    prefix = "/api/v1/updates/seedbox-agent"
    assert logged_in.post(prefix + "/generated-access").status_code == 403
    assert (
        logged_in.post(
            prefix + "/prepare-generated", json={"fingerprint": "SHA256:" + "a" * 43}
        ).status_code
        == 403
    )
    response = logged_in.post("https://127.0.0.1:18765" + prefix + "/generated-access")
    assert response.status_code == 200
    assert "private_key" not in response.text
    assert logged_in.get(prefix + "/generated-access").json()["data"] == response.json()["data"]


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


def test_private_key_is_encrypted_restored_and_passed_to_ssh(logged_in, monkeypatch):
    from unittest.mock import Mock

    import paramiko
    from mediahub.agent_updates import SSH_KEY_V2
    from mediahub.db import Setting
    from sqlalchemy import select

    key = paramiko.RSAKey.generate(2048)
    output = io.StringIO()
    key.write_private_key(output)
    private = output.getvalue()
    setup = SSHSetup(private_key=private, fingerprint="SHA256:" + "a" * 43, remember=True)
    svc = logged_in.app.state.services
    updater = svc.agent_updates
    address = SimpleNamespace(host="192.168.1.20")
    monkeypatch.setattr(updater, "binding", lambda: ("seedbox", None, address))
    connection = Mock()
    monkeypatch.setattr("mediahub.agent_updates.paramiko.SSHClient", lambda: connection)
    updater.prepare(setup)
    kwargs = connection.connect.call_args.kwargs
    assert kwargs["pkey"].get_base64() == key.get_base64()
    assert kwargs["password"] is None
    assert not kwargs["allow_agent"] and not kwargs["look_for_keys"]
    with svc.sessions() as db:
        stored = db.scalar(select(Setting).where(Setting.key == SSH_KEY_V2)).value
        assert private.splitlines()[1] not in json.dumps(stored)
    restored = AgentUpdates(svc).saved_setup("seedbox", address)
    assert restored.private_key.get_secret_value() == private
    assert restored.password is None
    assert restored.log_line(private.splitlines()[1]) == "[redacted]"
    updater.forget_setup()
    assert updater.saved_setup("seedbox", address) is None


def test_password_on_key_only_host_reports_required_method(monkeypatch):
    from unittest.mock import Mock

    import paramiko

    client = Mock()
    client.connect.side_effect = paramiko.BadAuthenticationType("no password", ["publickey"])
    monkeypatch.setattr("mediahub.agent_updates.paramiko.SSHClient", lambda: client)
    with pytest.raises(DomainError, match="requires SSH key"):
        AgentUpdates.connect(
            SimpleNamespace(host="192.168.1.20"),
            SSHSetup(password="secret", fingerprint="SHA256:" + "a" * 43),
        )
    client.close.assert_called_once()


@pytest.mark.parametrize("credentials", [{}, {"password": "secret", "private_key": "key"}])
def test_ssh_setup_requires_exactly_one_credential(credentials):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SSHSetup(**credentials, fingerprint="SHA256:" + "a" * 43)
