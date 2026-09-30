import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from mediahub.db import Setting, User
from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import (
    DeployConfig,
    DeployRequest,
    FjordHubDeploy,
    PinnedKey,
    SSHAddress,
    clean_line,
    commands,
    fingerprint,
)
from pydantic import ValidationError
from sqlalchemy import select


def request(**changes):
    return DeployRequest.model_validate(
        {
            "host": "192.168.1.126",
            "password": "test-password-only",
            "fingerprint": "SHA256:" + "A" * 43,
            "requestId": str(uuid4()),
            "config": {},
            **changes,
        }
    )


@pytest.mark.parametrize(
    "change",
    [
        {"hostname": "host;id"},
        {"cores": "4;id"},
        {"memory": "0"},
        {"timezone": "UTC\necho bad"},
        {"storage": "a$(id)"},
        {"bridge": "a,ip=dhcp"},
        {"dataPath": "/opt/fjordhub/sub"},
        {"installPath": "/srv/../etc"},
        {"appPort": "8080"},
        {"network": "static", "address": "192.168.1.5/24;id"},
        {"target": "arbitrary"},
        {"script": "echo bad"},
    ],
)
def test_rejects_untrusted_configuration(change):
    with pytest.raises(ValidationError):
        DeployConfig(**change)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "169.254.169.254", "8.8.8.8", "example.com", "192.168.1.1;id"]
)
def test_only_explicit_lan_target(host):
    with pytest.raises(ValidationError):
        SSHAddress(host=host)


def test_same_reviewed_template_and_bash_syntax():
    bash = "C:/Program Files/Git/bin/bash.exe" if Path("C:/").exists() else "/bin/bash"
    for target in ("lxc", "linux"):
        rendered = commands(DeployConfig(target=target))
        assert "@@" not in rendered
        if target == "lxc":
            assert "--cores 4 --memory 10240" in rendered
            assert "--unprivileged 1" in rendered
        subprocess.run([bash, "-n"], input=rendered, text=True, check=True)
        # Frontend test output, if present, must match server commands byte-for-byte.
        browser_script = Path(f".qa/fjordhub-commands/{target}.sh")
        if browser_script.exists():
            assert browser_script.read_text() == rendered


def test_host_identity_must_match():
    key = SimpleNamespace(asbytes=lambda: b"test public key")
    PinnedKey(fingerprint(key)).missing_host_key(None, "192.168.1.126", key)
    with pytest.raises(DomainError, match="fingerprint differs"):
        PinnedKey("SHA256:" + "A" * 43).missing_host_key(None, "192.168.1.126", key)


def test_authenticated_admin_and_csrf_required(client, logged_in, monkeypatch):
    monkeypatch.setattr("mediahub.fjordhub_deploy.FjordHubDeploy.launch", lambda *args: None)
    client.cookies.clear()
    assert client.get("/api/v1/fjordhub/deployment").status_code == 401
    assert client.get("/api/v1/fjordhub/deployment/target").status_code == 401


@pytest.mark.parametrize(
    "source,expected",
    [
        ("192.168.1.126:/downloads", "192.168.1.126"),
        ("10.10.2.8:/media", "10.10.2.8"),
        ("8.8.8.8:/media", None),
        ("127.0.0.1:/media", None),
        ("not-an-address", None),
    ],
)
def test_target_discovery_uses_bound_storage(logged_in, monkeypatch, source, expected):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add(Setting(key="seedbox_installation", value={"hostId": "seedbox-test"}))
    agent = SimpleNamespace(request=AsyncMock(return_value={"storage": {"source": source}}))
    client = MagicMock(return_value=agent)
    monkeypatch.setattr(svc.hosts, "client", client)
    response = logged_in.get("/api/v1/fjordhub/deployment/target?target=lxc")
    assert response.status_code == 200
    assert response.json()["data"]["host"] == expected
    client.assert_called_once_with("seedbox-test")
    agent.request.assert_awaited_once_with("GET", "/v1/seedbox/status")
    # The storage host must never be assumed to be a direct Linux deployment target.
    assert (
        logged_in.get("/api/v1/fjordhub/deployment/target?target=linux").json()["data"]["host"]
        is None
    )


def test_discovery_reuses_success_and_handles_offline_agent(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add(Setting(key="seedbox_installation", value={"hostId": "seedbox-test"}))
    monkeypatch.setattr(
        svc.hosts, "client", MagicMock(side_effect=DomainError("offline", "Offline", 503))
    )
    assert logged_in.get("/api/v1/fjordhub/deployment/target").json()["data"]["host"] is None
    with svc.sessions.begin() as db:
        db.add(
            Setting(
                key="fjordhub.deployment.test",
                value={
                    "state": "succeeded",
                    "host": "10.1.2.3",
                    "config": {"target": "lxc"},
                },
            )
        )
    assert logged_in.get("/api/v1/fjordhub/deployment/target").json()["data"] == {
        "host": "10.1.2.3",
        "source": "previous-installation",
    }


def test_job_idempotency_busy_failure_ack_and_restart(logged_in, monkeypatch):
    monkeypatch.setattr("mediahub.fjordhub_deploy.FjordHubDeploy.launch", lambda *args: None)
    svc = logged_in.app.state.services.fjordhub_deploy
    body = request()
    job = svc.start(body)
    assert svc.start(body)["id"] == job["id"]
    with pytest.raises(DomainError, match="already running"):
        svc.start(request())
    restarted = FjordHubDeploy(svc.sessions)
    assert restarted.latest()["state"] == "interrupted"
    with pytest.raises(DomainError, match="Inspect"):
        restarted.start(request())
    next_job = restarted.start(request(acknowledgedJob=job["id"]))
    assert next_job["id"] != job["id"]
    assert "test-password" not in json.dumps(restarted.latest())


@pytest.mark.parametrize("exit_code, expected", [(0, "succeeded"), (7, "failed"), (-1, "failed")])
def test_worker_streams_output_and_reports_exit(logged_in, monkeypatch, exit_code, expected):
    monkeypatch.setattr("mediahub.fjordhub_deploy.FjordHubDeploy.launch", lambda *args: None)
    monkeypatch.setattr("mediahub.fjordhub_deploy.time.sleep", lambda _: None)
    client = MagicMock()
    monkeypatch.setattr("mediahub.fjordhub_deploy.paramiko.SSHClient", lambda: client)
    channel = client.get_transport.return_value.open_session.return_value.__enter__.return_value
    channel.recv_ready.side_effect = [True, False]
    channel.recv.return_value = b"Created LXC 210\nsecret=hidden\ntest-password-only\n"
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = exit_code
    body = request()
    svc = logged_in.app.state.services.fjordhub_deploy
    job = svc.start(body)
    svc.run(body, job)
    result = svc.latest()
    assert result["state"] == expected
    assert "Created LXC 210" in result["logs"]
    assert "hidden" not in json.dumps(result)
    assert "test-password-only" not in json.dumps(result)
    channel.exec_command.assert_called_once_with("bash -s")
    assert b"--cores 4 --memory 10240" in channel.sendall.call_args.args[0]
    assert client.connect.call_args.kwargs["look_for_keys"] is False
    client.close.assert_called_once()


def test_endpoint_rejects_arbitrary_script_and_missing_csrf(logged_in, monkeypatch):
    monkeypatch.setattr("mediahub.fjordhub_deploy.FjordHubDeploy.launch", lambda *args: None)
    body = json.loads(request().model_dump_json())
    body["password"] = "test-password-only"
    assert (
        logged_in.post("/api/v1/fjordhub/deployment", json={**body, "script": "id"}).status_code
        == 422
    )
    response = logged_in.post("/api/v1/fjordhub/deployment", json=body)
    assert response.status_code == 200
    assert "test-password-only" not in response.text
    del logged_in.headers["X-MediaHub-CSRF"]
    assert logged_in.post("/api/v1/fjordhub/deployment", json=body).status_code == 403


def test_log_bound_and_scrubbing():
    assert (
        clean_line("\x1b[31mSECRET_KEY=hidden password=abc\x00", "abc")
        == "SECRET_KEY=[redacted] password=[redacted]"
    )
    assert len(clean_line("x" * 10000, "")) == 500


def test_non_admin_cannot_deploy_or_probe(logged_in):
    with logged_in.app.state.services.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    assert logged_in.get("/api/v1/fjordhub/deployment").status_code == 403
    assert (
        logged_in.post(
            "/api/v1/fjordhub/deployment/fingerprint", json={"host": "192.168.1.126"}
        ).status_code
        == 403
    )


def test_changed_host_key_prevents_command_dispatch(logged_in, monkeypatch):
    monkeypatch.setattr("mediahub.fjordhub_deploy.FjordHubDeploy.launch", lambda *args: None)
    client = MagicMock()
    client.connect.side_effect = DomainError(
        "ssh_host_key_changed", "SSH fingerprint differs; no commands ran"
    )
    monkeypatch.setattr("mediahub.fjordhub_deploy.paramiko.SSHClient", lambda: client)
    svc = logged_in.app.state.services.fjordhub_deploy
    body = request()
    job = svc.start(body)
    svc.run(body, job)
    assert svc.latest()["state"] == "failed"
    assert "fingerprint differs" in svc.latest()["message"]
    client.get_transport.assert_not_called()
    client.close.assert_called_once()
