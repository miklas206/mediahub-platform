import asyncio
import json

import pytest
from mediahub.errors import DomainError

from agent.seedbox_transaction import STEPS, InstallTransaction


class Driver:
    def __init__(self, failure=None, rollback_fails=False):
        self.calls, self.failure, self.rollback_fails = [], failure, rollback_fails

    async def preflight(self, digest):
        self.calls.append("preflight")
        if self.failure == "preflight":
            raise ValueError("SECRET_MUST_NOT_APPEAR")

    async def execute(self, step):
        self.calls.append(step)
        if self.failure == step:
            raise ValueError("SECRET_MUST_NOT_APPEAR")

    async def rollback_owned_runtime(self):
        self.calls.append("rollback")
        if self.rollback_fails:
            raise ValueError("SECRET_MUST_NOT_APPEAR")


def test_complete_real_step_progress_persisted(tmp_path):
    async def scenario():
        driver = Driver()
        transaction = InstallTransaction(tmp_path / "install.json", driver)
        await transaction.configured()
        await transaction.start("reviewed")
        await transaction.job
        assert driver.calls == list(STEPS)
        assert transaction.public()["state"] == "Healthy"
        assert all(step["state"] == "Succeeded" for step in transaction.public()["steps"])
        assert InstallTransaction(transaction.path, driver).public()["state"] == "Healthy"
        with pytest.raises(DomainError):
            await transaction.start("reviewed")

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_step", STEPS)
def test_each_stage_fails_with_safe_explicit_state(tmp_path, failed_step):
    async def scenario():
        driver = Driver(failed_step)
        transaction = InstallTransaction(tmp_path / "install.json", driver)
        await transaction.configured()
        await transaction.start("reviewed")
        await transaction.job
        public = transaction.public()
        assert public["state"] == (
            "PreflightFailed" if failed_step == "preflight" else "RollbackComplete"
        )
        assert public["failedStep"] == failed_step
        assert "SECRET_MUST_NOT_APPEAR" not in transaction.path.read_text()
        assert ("rollback" in driver.calls) == (failed_step != "preflight")
        assert not any(
            step["state"] == "Succeeded" for step in public["steps"][STEPS.index(failed_step) + 1 :]
        )
        driver.failure = None
        await transaction.configured()
        await transaction.start("reviewed-again")
        await transaction.job
        assert transaction.public()["state"] == "Healthy"
        assert transaction.public()["attempt"] == 2

    asyncio.run(scenario())


def test_failed_rollback_blocks_retry_until_reconciled(tmp_path):
    async def scenario():
        driver = Driver("start_vpn", True)
        transaction = InstallTransaction(tmp_path / "install.json", driver)
        await transaction.configured()
        await transaction.start("reviewed")
        await transaction.job
        assert transaction.public()["state"] == "ManualIntervention"
        with pytest.raises(DomainError):
            await transaction.start("reviewed")
        driver.rollback_fails = False
        await transaction.rollback()
        await transaction.job
        assert transaction.public()["state"] == "RollbackComplete"

    asyncio.run(scenario())


def test_process_interruption_never_reports_healthy(tmp_path):
    path = tmp_path / "install.json"
    path.write_text(json.dumps({"state": "Installing", "attempt": 1, "steps": []}))
    transaction = InstallTransaction(path, Driver())
    assert transaction.public()["state"] == "ManualIntervention"


def test_public_state_is_not_mutable_reference(tmp_path):
    transaction = InstallTransaction(tmp_path / "install.json", Driver())
    view = transaction.public()
    view["steps"].append({"id": "fake"})
    assert transaction.public()["steps"] == []


def test_ledger_disk_full_cannot_skip_owned_runtime_cleanup(tmp_path):
    async def scenario():
        driver = Driver()
        transaction = InstallTransaction(tmp_path / "install.json", driver)
        original = transaction.save

        def disk_full_after_mutation():
            if "create_vpn" in driver.calls:
                raise OSError("disk full")
            original()

        transaction.save = disk_full_after_mutation
        await transaction.configured()
        await transaction.start("reviewed")
        await transaction.job
        assert driver.calls[-1] == "rollback"
        assert "start_qbittorrent" not in driver.calls
        assert transaction.public()["state"] == "ManualIntervention"

    asyncio.run(scenario())


def test_cannot_install_before_configuration_or_skip_verification(tmp_path):
    async def scenario():
        transaction = InstallTransaction(tmp_path / "install.json", Driver())
        with pytest.raises(DomainError):
            await transaction.start("reviewed")
        with pytest.raises(DomainError):
            transaction.transition("Healthy")
        assert transaction.public()["state"] == "NotInstalled"
        await transaction.configured()
        assert transaction.public()["state"] == "ReadyForPreflight"
        with pytest.raises(DomainError):
            transaction.transition("Healthy")

    asyncio.run(scenario())
