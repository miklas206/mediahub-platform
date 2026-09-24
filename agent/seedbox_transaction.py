"""Durable, secret-free installation ledger with explicitly owned rollback.

Drivers must scope all operations to the reviewed installation, return no secrets,
and remove only resources this transaction created. Network disconnects never
cancel the worker; process death is surfaced as requiring reconciliation.
"""

import asyncio
import copy
import json
import os
import time
from pathlib import Path

from mediahub.errors import DomainError

STEPS = (
    "preflight",
    "persist_plan",
    "prepare_directories",
    "store_secrets",
    "create_vpn",
    "start_vpn",
    "verify_vpn",
    "verify_external_ip",
    "establish_forwarded_port",
    "create_qbittorrent",
    "verify_namespace",
    "verify_storage",
    "start_qbittorrent",
    "verify_api",
    "verify_egress",
    "verify_listen_port",
    "mark_installed",
)
TRANSITIONS = {
    "NotInstalled": {"Configuring"},
    "Configuring": {"ReadyForPreflight"},
    "ReadyForPreflight": {"Configuring", "PreflightFailed", "Installing"},
    "PreflightFailed": {"Configuring", "ReadyForPreflight"},
    "Installing": {"Verifying", "Failed", "PreflightFailed", "ManualIntervention"},
    "Verifying": {"Healthy", "Failed", "ManualIntervention"},
    "Failed": {"RollbackRequired", "ManualIntervention"},
    "RollbackRequired": {"RollbackComplete", "ManualIntervention"},
    "RollbackComplete": {"Configuring", "ReadyForPreflight"},
    "ManualIntervention": {"RollbackRequired"},
    "Healthy": set(),
}
LEGACY_STATES = {
    "Blocked": "PreflightFailed",
    "RollingBack": "RollbackRequired",
    "ManualInterventionRequired": "ManualIntervention",
}


class InstallTransaction:
    def __init__(self, path: Path, driver):
        self.path, self.driver = path, driver
        self.lock = asyncio.Lock()
        self.job = None
        self.state = {
            "state": "NotInstalled",
            "steps": [],
            "attempt": 0,
            "failedStep": None,
            "dataPreserved": True,
        }
        if path.exists():
            if path.is_symlink() or path.stat().st_size > 65536:
                raise ValueError("Invalid installation ledger")
            saved = json.loads(path.read_text())
            if isinstance(saved, dict):
                saved["state"] = LEGACY_STATES.get(saved.get("state"), saved.get("state"))
            self._validate(saved)
            self.state = saved
            if saved["state"] in {"Installing", "Verifying", "RollbackRequired", "Failed"}:
                self.state["state"] = "ManualIntervention"
                self.state["message"] = (
                    "Installation interrupted; reconcile owned runtime before retry"
                )
                self.save()

    @staticmethod
    def _validate(state):
        if not isinstance(state, dict) or state.get("state") not in TRANSITIONS:
            raise ValueError("Invalid installation state")
        if not isinstance(state.get("attempt"), int) or state["attempt"] < 0:
            raise ValueError("Invalid attempt")
        if not isinstance(state.get("steps"), list) or len(state["steps"]) > len(STEPS):
            raise ValueError("Invalid installation steps")
        if any(
            row.get("id") not in STEPS
            or row.get("state") not in {"Pending", "Running", "Succeeded", "Failed"}
            for row in state["steps"]
        ):
            raise ValueError("Invalid installation step")

    def save(self):
        # Ledger contains only controlled IDs and fixed messages, never exception text.
        pending = self.path.with_name(self.path.name + ".pending")
        if self.path.is_symlink() or self.path.parent.resolve() != self.path.parent:
            raise ValueError("Unsafe ledger location")
        fd = os.open(
            pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(self.state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        pending.chmod(0o600)
        os.replace(pending, self.path)
        if os.name != "nt":
            fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def public(self):
        return copy.deepcopy(self.state)

    def transition(self, target):
        if target not in TRANSITIONS[self.state["state"]]:
            raise DomainError(
                "invalid_install_transition", "Installation transition is not allowed", 409
            )
        previous = self.state["state"]
        self.state["state"] = target
        try:
            self.save()
        except BaseException:
            self.state["state"] = previous
            raise

    async def configured(self):
        """Caller has validated and persisted a secret-free draft plus private references."""
        async with self.lock:
            if self.state["state"] != "Configuring":
                self.transition("Configuring")
            self.transition("ReadyForPreflight")

    def save_failure_state(self):
        # A full/unavailable ledger disk must not prevent stopping owned runtime.
        try:
            self.save()
            return True
        except OSError:
            self.state.update(
                state="ManualIntervention",
                message="Installation state could not be persisted; inspect before retry",
            )
            return False

    async def start(self, reviewed_digest):
        async with self.lock:
            if self.job and not self.job.done():
                raise DomainError("install_busy", "Installation already in progress", 409)
            if self.state["state"] != "ReadyForPreflight":
                raise DomainError(
                    "install_reconciliation_required",
                    "Inspect existing installation before retry",
                    409,
                )
            # No secret values or caller-controlled strings are placed in the ledger.
            self.state = {
                "state": "Installing",
                "attempt": self.state["attempt"] + 1,
                "steps": [{"id": step, "state": "Pending"} for step in STEPS],
                "failedStep": None,
                "startedAt": time.time(),
                "dataPreserved": True,
            }
            self.save()
            self.job = asyncio.create_task(self.run(reviewed_digest))
            return self.public()

    async def run(self, reviewed_digest):
        changed = False
        step = "preflight"
        try:
            for row in self.state["steps"]:
                step = row["id"]
                row.update(state="Running", startedAt=time.time())
                if step == "verify_api":
                    self.transition("Verifying")
                self.save()
                if step == "preflight":
                    await self.driver.preflight(reviewed_digest)
                else:
                    # From this point, even a partially completed call needs rollback.
                    changed = True
                    await self.driver.execute(step)
                row.update(state="Succeeded", finishedAt=time.time())
                self.save()
            self.state.update(
                finishedAt=time.time(), message="Installation and all safety checks verified"
            )
            self.transition("Healthy")
        except asyncio.CancelledError:
            # No blind recreation following restart: driver must reconcile ownership.
            self.state.update(
                state="ManualIntervention",
                failedStep=step,
                message="Installation interrupted; reconcile before retry",
            )
            self.save_failure_state()
            raise
        except Exception:
            next(row for row in self.state["steps"] if row["id"] == step)["state"] = "Failed"
            self.state.update(
                state="Failed" if changed else "PreflightFailed",
                failedStep=step,
                message="Installation safety check failed",
                finishedAt=time.time(),
            )
            self.save_failure_state()
            if changed:
                await self._rollback()

    async def _rollback(self):
        self.state["state"] = "RollbackRequired"
        persistence_ok = self.save_failure_state()
        try:
            await self.driver.rollback_owned_runtime()
        except Exception:
            self.state.update(
                state="ManualIntervention",
                message="Owned runtime cleanup needs operator inspection; data retained",
            )
        else:
            self.state.update(
                state="RollbackComplete",
                message="New runtime removed; data and private configuration retained",
            )
        if not persistence_ok:
            self.state.update(
                state="ManualIntervention",
                message="Runtime cleanup attempted; persistent state needs inspection",
            )
        self.save_failure_state()

    async def rollback(self):
        async with self.lock:
            if self.job and not self.job.done():
                raise DomainError("install_busy", "Wait for the active operation", 409)
            if self.state["state"] not in {"ManualIntervention", "Failed"}:
                raise DomainError(
                    "rollback_not_required", "No failed installation requires rollback", 409
                )
            self.job = asyncio.create_task(self._rollback())
            return {"state": "accepted"}
