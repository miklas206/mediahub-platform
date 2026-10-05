"""Durable wizard and production execution, serialized with runtime control."""

import asyncio
import contextlib
import json
import re
import uuid
from pathlib import Path

from mediahub.apps.seedbox import SeedboxInstallation
from mediahub.apps.seedbox_credentials import (
    QBitInitialSettings,
    SeedboxCredentials,
    VPNProfileRegistry,
)
from mediahub.apps.seedbox_wizard import STEPS
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

from agent.install_files import read_json, save_json
from agent.seedbox_install_driver import BoundInstallRuntime, ProductionInstallDriver
from agent.seedbox_rotation import RotationError, rotate
from agent.seedbox_secret_store import SeedboxSecretStore
from agent.seedbox_transaction import InstallTransaction


class SeedboxWorkflow:
    def __init__(self, control):
        self.control = control
        self.lock = asyncio.Lock()

    def initialize(self):
        policy = self.control.installer.policy()
        self.root = Path(policy.workRoot)
        self.path = self.root / "wizard.json"
        self.store = SeedboxSecretStore(self.root / "vault")
        if self.path.exists():
            self.draft = read_json(self.path)
        else:
            binding = self.root / "installation.json"
            spec = (
                SeedboxInstallation.model_validate(read_json(binding)["installation"])
                if binding.exists()
                else SeedboxInstallation(
                    installationId="seedbox",
                    hostId=policy.hostId,
                    downloadsStorageId=policy.downloadsStorageId,
                    credentialRef="seedbox-runtime",
                    provider="protonvpn",
                )
            )
            self.draft = {
                "revision": 0,
                "step": 0,
                "installation": spec.model_dump(),
                "qBittorrent": QBitInitialSettings().model_dump(),
                "portForwardingAcknowledged": False,
                "vpnReference": None,
                "clientReference": None,
                "preflight": None,
            }
        self.spec = SeedboxInstallation.model_validate(self.draft["installation"])
        self.settings = QBitInitialSettings.model_validate(self.draft["qBittorrent"])

    def busy(self):
        if self.control.job and not self.control.job.done():
            raise DomainError("operation_busy", "Wait for the current runtime operation", 409)

    def check(self, revision):
        self.initialize()
        self.busy()
        if revision != self.draft["revision"]:
            raise DomainError(
                "revision_conflict", "Configuration changed; reload before continuing", 409
            )
        ledger = self.root / "install-transaction.json"
        if ledger.exists() and read_json(ledger).get("state") in {
            "Installing",
            "Verifying",
            "RollbackRequired",
            "ManualIntervention",
            "Failed",
        }:
            raise DomainError(
                "reconciliation_required",
                "Reconcile the interrupted runtime before changing configuration",
                409,
            )

    def editable(self):
        if self.draft["step"] >= 10:
            raise DomainError(
                "step_locked",
                "Execution configuration is locked; return from preflight before editing",
                409,
            )

    def ledger(self, state):
        save_json(
            self.root / "install-transaction.json",
            {"state": state, "attempt": 0, "steps": [], "failedStep": None, "dataPreserved": True},
        )

    def enable_recovery(self, driver):
        self.control.initialize()
        self.control.driver.forwarding = driver.runtime.forwarding
        self.control.lifecycle.state["desiredRunning"] = True
        self.control.lifecycle.persist()
        self.control.status.cached = None

    def save(self):
        self.draft["revision"] += 1
        save_json(self.path, self.draft)

    def credentials(self):
        if self.draft.get("useRuntimeCredentials"):
            return self.store.load("seedbox-runtime")
        vpn_ref, client_ref = self.draft["vpnReference"], self.draft["clientReference"]
        if not vpn_ref or not client_ref:
            raise DomainError(
                "credentials_required", "VPN and qBittorrent credentials are required", 409
            )
        client = json.loads(self.store.get(client_ref))
        return SeedboxCredentials(vpnConfig=self.store.get(vpn_ref).decode(), **client)

    def driver(self, *, adoption=False):
        runtime = BoundInstallRuntime(
            self.control.installer, self.control.driver.socket, self.control.devices, self.spec
        )

        async def healthy():
            # Recovery is enabled only after the complete transaction is durable.
            pass

        credentials = (lambda: self.store.load("seedbox-runtime")) if adoption else self.credentials
        return ProductionInstallDriver(runtime, self.settings, credentials, healthy)

    def public(self):
        self.initialize()
        ledger = self.root / "install-transaction.json"
        state = read_json(ledger) if ledger.exists() else {"state": "NotInstalled", "steps": []}
        if state["state"] in {"Installing", "Verifying", "RollbackRequired"} and not (
            self.control.job and not self.control.job.done()
        ):
            self.ledger("ManualIntervention")
            state = read_json(ledger)
        rotation_path = self.root / "credential-rotation.json"
        rotation = read_json(rotation_path) if rotation_path.exists() else None
        if (
            rotation
            and rotation["state"] == "Applying"
            and not (self.control.job and not self.control.job.done())
        ):
            rotation["state"] = "ManualIntervention"
            save_json(rotation_path, rotation)
        operation = getattr(self.control, "operation", {"state": "idle", "action": None})
        if (
            rotation
            and str(operation.get("action", "")).startswith("rotate-")
            and (
                rotation["kind"] != operation["action"].removeprefix("rotate-")
                or (operation.get("id") and rotation.get("operationId") != operation["id"])
            )
        ):
            # An earlier journal is recovery history, not this operation's result.
            rotation = None
        # Only named public fields. Vault records and import payloads never leave Agent.
        return {
            key: self.draft[key]
            for key in (
                "revision",
                "step",
                "installation",
                "qBittorrent",
                "portForwardingAcknowledged",
                "preflight",
            )
        } | {
            "busy": bool(self.control.job and not self.control.job.done()),
            "steps": list(STEPS),
            "transaction": {
                "state": state["state"],
                "attempt": state.get("attempt", 0),
                "failedStep": state.get("failedStep"),
                "dataPreserved": True,
                "steps": [
                    {"id": row["id"], "state": row["state"]} for row in state.get("steps", [])
                ],
            },
            "vpnConfigured": bool(
                self.draft.get("useRuntimeCredentials")
                or (
                    self.draft["vpnReference"]
                    and SecretStore.status(self.store, self.draft["vpnReference"])["configured"]
                )
            ),
            "clientConfigured": bool(
                self.draft.get("useRuntimeCredentials")
                or (
                    self.draft["clientReference"]
                    and SecretStore.status(self.store, self.draft["clientReference"])["configured"]
                )
            ),
            "runtimeCredentialConfigured": self.store.status("seedbox-runtime")["configured"],
            "rotation": {
                "state": rotation["state"],
                "kind": rotation["kind"],
                "failedStep": rotation.get("failedStep"),
            }
            if rotation
            else None,
            "operation": getattr(self.control, "operation", {"state": "idle", "action": None}),
        }

    async def rotation(self, body, kind):
        async with self.lock:
            self.check(body.revision)
            self.control.initialize()
            rotation_path = self.root / "credential-rotation.json"
            if rotation_path.exists() and read_json(rotation_path).get("state") in {
                "Applying",
                "ManualIntervention",
            }:
                raise DomainError(
                    "reconciliation_required",
                    "Inspect the interrupted credential rotation before changing credentials",
                    409,
                )

            self.control.operation = {
                "state": "running",
                "action": "rotate-" + kind,
                "id": uuid.uuid4().hex,
            }

            async def run():
                async with self.control.lifecycle.lock:
                    try:
                        stage = "load_current_credential"
                        try:
                            previous = self.store.load("seedbox-runtime")
                            stage = "validate_candidate_credential"
                            updated = SeedboxCredentials(
                                vpnConfig=(
                                    VPNProfileRegistry()
                                    .get(self.spec.protocol)
                                    .validate(body.vpnConfig)
                                    if kind == "vpn"
                                    else previous.vpnConfig
                                ),
                                webUsername=previous.webUsername
                                if kind == "vpn"
                                else body.webUsername,
                                webPassword=previous.webPassword
                                if kind == "vpn"
                                else body.webPassword,
                            )
                        except Exception as error:
                            raise RotationError("rotation_preflight_failed", stage) from error
                        await rotate(self.control, self.store, updated, kind)
                    except Exception as error:
                        preflight = isinstance(error, RotationError) and (
                            error.code == "rotation_preflight_failed"
                        )
                        self.control.operation.update(
                            state="failed",
                            errorCode=error.code
                            if isinstance(error, RotationError)
                            else "rotation_failed",
                            failedStep=error.failed_step
                            if isinstance(error, RotationError)
                            else None,
                            message=(
                                "Rotation preflight failed before runtime changes; inspect the reported step"
                                if preflight
                                else "Rotation needs inspection; private input is retained encrypted"
                            ),
                        )
                    else:
                        self.control.operation.update(
                            state="succeeded",
                            message="Credential rotation and runtime health verified",
                        )
                    finally:
                        self.control.status.cached = None

            self.control.job = asyncio.create_task(run())
            return {"state": "accepted"}

    async def configure(self, body):
        async with self.lock:
            self.check(body.revision)
            self.editable()
            self.control.installer.plan(body.installation)  # Enforces delegated host/paths.
            binding = self.root / "installation.json"
            if (
                binding.exists()
                and SeedboxInstallation.model_validate(read_json(binding)["installation"])
                != body.installation
            ):
                raise DomainError(
                    "binding_conflict",
                    "Existing installation requires controlled reconciliation",
                    409,
                )
            self.draft.update(
                installation=body.installation.model_dump(),
                qBittorrent=body.qBittorrent.model_dump(),
                portForwardingAcknowledged=body.portForwardingAcknowledged,
                preflight=None,
            )
            self.save()
            return self.public()

    async def import_vpn(self, body):
        async with self.lock:
            self.check(body.revision)
            self.editable()
            profile = VPNProfileRegistry().get(self.spec.protocol).validate(body.vpnConfig)
            reference = "wizard-vpn-" + uuid.uuid4().hex
            self.store.put(reference, profile.get_secret_value().encode())
            self.draft.update(vpnReference=reference, preflight=None, useRuntimeCredentials=False)
            self.save()
            return self.public()

    async def import_client(self, body):
        async with self.lock:
            self.check(body.revision)
            self.editable()
            # Apply the shared password policy before writing encrypted input.
            if any(ord(char) < 32 for char in body.webPassword.get_secret_value()):
                raise DomainError("invalid_password", "Control characters are not supported", 422)
            reference = "wizard-client-" + uuid.uuid4().hex
            self.store.put(
                reference,
                json.dumps(
                    {
                        "webUsername": body.webUsername,
                        "webPassword": body.webPassword.get_secret_value(),
                    }
                ).encode(),
            )
            self.draft.update(
                clientReference=reference, preflight=None, useRuntimeCredentials=False
            )
            self.save()
            return self.public()

    async def advance(self, body):
        async with self.lock:
            self.check(body.revision)
            step = self.draft["step"]
            if body.direction == "back":
                if not 0 < step <= 10:
                    raise DomainError(
                        "step_locked", "Execution progress is controlled by the backend", 409
                    )
                self.draft["step"] -= 1
                self.draft["preflight"] = None
            else:
                if step >= 9:
                    raise DomainError(
                        "step_locked", "Run preflight/install; steps cannot be skipped", 409
                    )
                if step in {1, 2}:
                    plan = self.control.installer.plan(self.spec)
                    if plan["blockers"]:
                        raise DomainError(
                            "storage_unavailable", "Verified delegated storage is required", 409
                        )
                if step == 3 and (
                    self.spec.provider != "protonvpn" or self.spec.protocol != "wireguard"
                ):
                    raise DomainError(
                        "unsupported_provider", "Choose an approved provisioning provider", 409
                    )
                if step == 4 and not (
                    self.draft["vpnReference"] or self.draft.get("useRuntimeCredentials")
                ):
                    raise DomainError("vpn_required", "Import VPN configuration first", 409)
                if step == 5 and not self.draft["portForwardingAcknowledged"]:
                    raise DomainError(
                        "nat_pmp_required", "Confirm a P2P profile with NAT-PMP enabled", 409
                    )
                if step == 7:
                    self.credentials()
                self.draft["step"] += 1
            self.ledger("Configuring")
            self.save()
            return self.public()

    async def review(self):
        async with self.lock:
            self.initialize()
            plan = self.driver().review()
            plan["credentialsConfigured"] = bool(
                self.draft["vpnReference"] and self.draft["clientReference"]
            )
            return plan

    async def preflight(self, body):
        async with self.lock:
            self.check(body.revision)
            if self.draft["step"] != 9 or not self.draft["portForwardingAcknowledged"]:
                raise DomainError("step_locked", "Complete configuration and review first", 409)
            self.control.initialize()
            driver = self.driver()

            async def run():
                async with self.control.lifecycle.lock:
                    try:
                        await driver.preflight(body.reviewedPlanDigest)
                    except Exception:
                        self.draft["preflight"] = {
                            "state": "PreflightFailed",
                            "message": "Live safety check failed; review host, storage and private configuration",
                        }
                        self.ledger("PreflightFailed")
                    else:
                        self.draft["preflight"] = {
                            "state": "ReadyForPreflight",
                            "digest": body.reviewedPlanDigest,
                        }
                        self.draft["step"] = 10
                        self.ledger("ReadyForPreflight")
                    self.save()

            self.control.job = asyncio.create_task(run())
            return {"state": "accepted"}

    async def install(self, body):
        async with self.lock:
            self.check(body.revision)
            if (
                self.draft["step"] != 10
                or (self.draft.get("preflight") or {}).get("digest") != body.reviewedPlanDigest
            ):
                raise DomainError(
                    "preflight_required", "Live preflight of this exact plan is required", 409
                )
            driver = self.driver()
            transaction = InstallTransaction(self.root / "install-transaction.json", driver)
            await transaction.configured()
            self.control.initialize()
            self.control.lifecycle.state["desiredRunning"] = False
            self.control.lifecycle.persist()

            async def run():
                async with self.control.lifecycle.lock:
                    try:
                        await transaction.start(body.reviewedPlanDigest)
                        await transaction.job
                        if transaction.public()["state"] == "Healthy":
                            self.draft["step"] = 12
                            self.save()
                            self.enable_recovery(driver)
                        else:
                            self.draft["step"] = 9
                            self.draft["preflight"] = None
                            self.save()
                    except asyncio.CancelledError:
                        if transaction.job and not transaction.job.done():
                            transaction.job.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await transaction.job
                        raise
                    except Exception:
                        self.control.lifecycle.state["desiredRunning"] = False
                        self.control.lifecycle.persist()
                        self.ledger("ManualIntervention")

            self.draft["step"] = 11
            self.save()
            self.control.job = asyncio.create_task(run())
            return {"state": "accepted"}

    async def adopt(self):
        async with self.lock:
            self.initialize()
            self.busy()
            self.control.initialize()
            driver = self.driver(adoption=True)

            async def run():
                async with self.control.lifecycle.lock:
                    try:
                        result = await driver.adopt()
                    except Exception:
                        result = {
                            "state": "ManualIntervention",
                            "message": "Runtime adoption checks did not pass",
                        }
                    save_json(
                        self.root / "install-transaction.json",
                        {**result, "attempt": 0, "steps": [], "dataPreserved": True},
                    )
                    if result["state"] == "Healthy":
                        self.draft["step"] = 12
                        self.draft["useRuntimeCredentials"] = True
                    self.save()
                    if result["state"] == "Healthy":
                        self.enable_recovery(driver)

            self.control.job = asyncio.create_task(run())
            return {"state": "accepted"}

    async def rollback(self):
        async with self.lock:
            self.initialize()
            self.busy()
            self.control.initialize()
            driver = self.driver()
            transaction = InstallTransaction(self.root / "install-transaction.json", driver)
            if transaction.state["state"] not in {"ManualIntervention", "Failed"}:
                raise DomainError(
                    "rollback_not_required",
                    "Only an interrupted installation can be reconciled",
                    409,
                )
            journal = read_json(driver.journal)
            if journal.get("installationId") != self.spec.installationId or not re.fullmatch(
                r"[a-f0-9]{32}", journal.get("transactionId", "")
            ):
                raise DomainError(
                    "ownership_required", "A valid transaction ownership journal is required", 409
                )
            # An explicit reconciliation adopts cleanup authority only for this journal.
            # The driver also checks each container's matching transaction label.
            driver.transaction_id = journal["transactionId"]
            self.control.lifecycle.state["desiredRunning"] = False
            self.control.lifecycle.persist()

            async def run():
                async with self.control.lifecycle.lock:
                    await transaction.rollback()
                    await transaction.job
                    if transaction.public()["state"] == "RollbackComplete":
                        self.draft.update(step=9, preflight=None)
                        self.save()

            self.control.job = asyncio.create_task(run())
            return {"state": "accepted", "dataPreserved": True}
