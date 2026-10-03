import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from mediahub.db import ExternalIntegration
from mediahub.fjordhub_deploy import DeployConfig
from mediahub.fjordhub_pairing import installer_script, pair_installed
from sqlalchemy import select


def ssh_client(status=0):
    channel = MagicMock()
    channel.__enter__.return_value = channel
    channel.exit_status_ready.return_value = True
    channel.recv_exit_status.return_value = status
    client = MagicMock()
    client.get_transport.return_value.open_session.return_value = channel
    return client, channel


def test_pairing_keeps_bearer_out_of_guest_logs_and_public_records(logged_in, monkeypatch):
    svc = logged_in.app.state.services.integrations
    token = "fh_at_" + "a" * 43
    monkeypatch.setattr("mediahub.fjordhub_pairing.secrets.token_urlsafe", lambda _: "a" * 43)
    client, channel = ssh_client()
    job = {"logs": ["MEDIAHUB_FJORDHUB_URL=http://192.168.1.42:8888"], "actualCtid": "201"}
    assert pair_installed(client, DeployConfig(), job, svc) == "pending_setup"
    payload = channel.sendall.call_args.args[0].decode()
    assert token not in payload
    assert hashlib.sha256(token.encode()).hexdigest() in payload
    assert channel.exec_command.call_args.args[0] == "pct exec 201 -- python3 -"
    rows = svc.list()
    assert len(rows) == 1 and rows[0]["tokenConfigured"]
    assert token not in json.dumps(rows) and token not in json.dumps(job)
    with svc.sessions() as db:
        row = db.scalar(select(ExternalIntegration))
        assert svc.store.get(row.secret_reference).decode() == token
    assert pair_installed(client, DeployConfig(), job, svc) == "existing"
    assert channel.sendall.call_count == 1


def test_pairing_failure_keeps_installation_unpaired(logged_in):
    svc = logged_in.app.state.services.integrations
    client, _ = ssh_client(1)
    with pytest.raises(ValueError):
        pair_installed(
            client,
            DeployConfig(target="linux"),
            {"logs": ["MEDIAHUB_FJORDHUB_URL=http://192.168.1.42:8888"]},
            svc,
        )
    assert svc.list() == []


def test_bootstrap_is_parseable_persistent_bounded_and_rejects_unknown_lxc():
    spec = {"hash": "a" * 64, "prefix": "fh_at_aaaaaa"}
    command, payload = installer_script(
        DeployConfig(target="linux"), "", spec, "mediahub-pair-test"
    )
    compile(payload, "bootstrap", "exec")
    assert command == "python3 -"
    assert b"WantedBy=timers.target" in payload
    assert b"disable" in payload and b"chmod(0o600)" in payload
    with pytest.raises(ValueError):
        installer_script(DeployConfig(), "", spec, "mediahub-pair-test")


def test_detection_upgrade_deduplicates_and_does_not_restore_disconnected(logged_in):
    svc = logged_in.app.state.services.integrations
    origin = "https://192.168.1.42:8888"
    detected = svc.register_detected(origin, False)
    assert detected["snapshot"]["status"] == "detected"
    assert not detected["tokenConfigured"]
    assert svc.register_detected(origin, False)["id"] == detected["id"]
    from pydantic import SecretStr

    body = SimpleNamespace(
        baseUrl=origin, allowHttp=False, name="FjordHub", accessToken=SecretStr("a" * 32)
    )
    paired = svc.save(body)
    assert paired["id"] == detected["id"] and len(svc.list()) == 1
    svc.disconnect(paired["id"])
    assert not svc.register_detected(origin, False)["enabled"]
