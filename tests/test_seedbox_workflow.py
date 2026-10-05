import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.apps.seedbox_credentials import QBitInitialSettings, SeedboxCredentials
from mediahub.apps.seedbox_wizard import ClientImport, VPNImport, WizardAdvance, WizardExecute
from mediahub.errors import DomainError
from test_seedbox_credentials import profile  # noqa: F401
from test_seedbox_plan import spec

from agent.install_files import save_json
from agent.seedbox_provision import client_config_archive
from agent.seedbox_workflow import SeedboxWorkflow


def workflow(tmp_path):
    save_json(tmp_path / "installation.json", {"installation": spec().model_dump()})
    policy = SimpleNamespace(workRoot=str(tmp_path))
    control = SimpleNamespace(
        job=None,
        installer=SimpleNamespace(policy=lambda: policy, plan=lambda _: {"blockers": []}),
        initialize=lambda: None,
        lifecycle=SimpleNamespace(
            lock=asyncio.Lock(), state={"desiredRunning": False}, persist=lambda: None
        ),
    )
    result = SeedboxWorkflow(control)
    result.initialize()
    return result


def test_import_is_encrypted_and_resume_returns_flags_only(tmp_path, profile):  # noqa: F811
    async def run():
        item = workflow(tmp_path)
        # Test profile provider must agree with supported production adapter.
        item.draft["installation"]["provider"] = "protonvpn"
        item.save()
        password = "test-only-strong-password-123"
        await item.import_vpn(VPNImport(revision=1, vpnConfig=profile))
        public = await item.import_client(
            ClientImport(revision=2, webUsername="test", webPassword=password)
        )
        assert public["vpnConfigured"] and public["clientConfigured"]
        assert profile not in json.dumps(public) and password not in json.dumps(public)
        assert item.credentials().webPassword.get_secret_value() == password
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert password.encode() not in path.read_bytes()
                assert profile.encode() not in path.read_bytes()
        resumed = SeedboxWorkflow(item.control)
        assert resumed.public() == public
        with pytest.raises(DomainError, match="reload"):
            await resumed.advance(WizardAdvance(revision=0, direction="next"))

    asyncio.run(run())


def test_cannot_skip_credentials_or_install_or_edit_locked_config(tmp_path):
    async def run():
        item = workflow(tmp_path)
        item.draft["step"] = 4
        item.save()
        with pytest.raises(DomainError):
            await item.advance(WizardAdvance(revision=1, direction="next"))
        with pytest.raises(DomainError):
            await item.install(WizardExecute(revision=1, reviewedPlanDigest="a" * 64))
        item.draft["step"] = 10
        item.save()
        with pytest.raises(DomainError):
            await item.import_client(
                ClientImport(
                    revision=2, webUsername="test", webPassword="test-only-strong-password"
                )
            )
        with pytest.raises(DomainError):
            await item.install(WizardExecute(revision=2, reviewedPlanDigest="a" * 64))

    asyncio.run(run())


def test_preflight_failure_is_durable_and_redacted(tmp_path):
    async def run():
        item = workflow(tmp_path)
        item.draft.update(step=9, portForwardingAcknowledged=True)
        item.save()
        item.driver = lambda: SimpleNamespace(
            preflight=AsyncMock(side_effect=ValueError("SECRET_SENTINEL"))
        )
        assert await item.preflight(WizardExecute(revision=1, reviewedPlanDigest="a" * 64)) == {
            "state": "accepted"
        }
        await item.control.job
        public = item.public()
        assert public["transaction"]["state"] == "PreflightFailed"
        assert public["step"] == 9
        assert "SECRET_SENTINEL" not in json.dumps(public)

    asyncio.run(run())


def test_interrupted_install_blocks_blind_retry(tmp_path):
    item = workflow(tmp_path)
    item.ledger("Installing")
    assert item.public()["transaction"]["state"] == "ManualIntervention"
    with pytest.raises(DomainError):
        item.check(0)


def test_rotation_failure_is_public_without_private_recovery_reference(tmp_path):
    item = workflow(tmp_path)
    item.ledger("Healthy")
    save_json(
        tmp_path / "credential-rotation.json",
        {
            "state": "ManualIntervention",
            "kind": "client",
            "failedStep": "verify_new_client_credential",
            "stagedReference": "private-recovery-reference",
        },
    )
    public = item.public()
    assert public["transaction"]["state"] == "Healthy"
    assert public["rotation"] == {
        "state": "ManualIntervention",
        "kind": "client",
        "failedStep": "verify_new_client_credential",
    }
    assert "private-recovery-reference" not in json.dumps(public)


def test_early_rotation_failure_is_public_and_redacted(tmp_path, monkeypatch):
    async def run():
        item = workflow(tmp_path)
        item.control.status = SimpleNamespace(cached="stale")
        item.store.stage(
            "seedbox-runtime",
            SeedboxCredentials(
                vpnConfig="test-profile", webUsername="tester", webPassword="old-test-password-123"
            ),
        )
        monkeypatch.setattr(
            "agent.seedbox_workflow.rotate",
            AsyncMock(side_effect=ValueError("SECRET_SENTINEL")),
        )
        assert await item.rotation(
            ClientImport(revision=0, webUsername="tester", webPassword="new-test-password-123"),
            "client",
        ) == {"state": "accepted"}
        assert item.public()["operation"]["state"] == "running"
        await item.control.job
        public = item.public()
        assert public["operation"]["state"] == "failed"
        assert "SECRET_SENTINEL" not in json.dumps(public)
        assert item.control.status.cached is None

    asyncio.run(run())


def test_active_rotation_is_not_marked_interrupted(tmp_path):
    async def run():
        item = workflow(tmp_path)
        save_json(
            tmp_path / "credential-rotation.json",
            {"state": "Applying", "kind": "client", "stagedReference": "private-reference"},
        )
        item.control.job = asyncio.create_task(asyncio.sleep(0))
        assert item.public()["rotation"]["state"] == "Applying"
        await item.control.job

    asyncio.run(run())


def test_interrupted_rotation_is_reported_as_manual_intervention(tmp_path):
    item = workflow(tmp_path)
    save_json(
        tmp_path / "credential-rotation.json",
        {"state": "Applying", "kind": "client", "stagedReference": "private-reference"},
    )
    assert item.public()["rotation"]["state"] == "ManualIntervention"
    assert json.loads((tmp_path / "credential-rotation.json").read_text())["state"] == (
        "ManualIntervention"
    )


def test_client_archive_contains_verifier_not_password_and_no_paths_outside_config(profile):  # noqa: F811
    import io
    import tarfile

    password = "only-a-test-password-12345"
    value = client_config_archive(
        spec(),
        QBitInitialSettings(),
        SeedboxCredentials(vpnConfig=profile, webUsername="tester", webPassword=password),
    )
    assert password.encode() not in value and profile.encode() not in value
    with tarfile.open(fileobj=io.BytesIO(value)) as archive:
        assert archive.getnames() == ["qBittorrent", "qBittorrent/qBittorrent.conf"]
        member = archive.getmember("qBittorrent/qBittorrent.conf")
        assert member.mode == 0o600 and member.uid == spec().uid
        text = archive.extractfile(member).read().decode()
        assert "Password_PBKDF2" in text and "Interface=tun0" in text
        assert "LocalHostAuth=true" in text


def test_wizard_is_admin_and_https_only(logged_in):
    result = logged_in.get("/api/v1/seedbox/wizard")
    assert result.status_code == 403 and "https_required" in result.text
    result = logged_in.post(
        "/api/v1/seedbox/wizard/client",
        json={"revision": 0, "webUsername": "tester", "webPassword": "test-only-private-password"},
    )
    assert result.status_code == 403
    assert "test-only-private-password" not in result.text
