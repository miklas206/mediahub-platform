import asyncio
import os
import platform
import time
from ipaddress import ip_address
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import select

from mediahub.config import Config
from mediahub.contracts import StorageInput, StrictModel
from mediahub.db import InstallationState, PendingImport, Setting, StorageLocation
from mediahub.errors import DomainError


class NetworkSettings(StrictModel):
    listen_host: str = "127.0.0.1"
    port: int = Field(default=18765, ge=1024, le=65535)
    base_url: str = "http://127.0.0.1:18765"
    allowed_origins: list[str] = ["http://127.0.0.1:18765"]
    trusted_proxies: list[str] = []

    @model_validator(mode="after")
    def validate(self):
        ip_address(self.listen_host)
        Config(
            base_url=self.base_url,
            allowed_origins=self.allowed_origins,
            trusted_proxies=self.trusted_proxies,
            browser_tls_cert=None,
            browser_tls_key=None,
            _env_file=None,
        )
        return self


class PlannedStorage(StorageInput):
    action: Literal["existing", "create"] = "existing"
    confirmed_path: str | None = None


class Draft(StrictModel):
    step: int = Field(default=0, ge=0, le=9)
    installation_type: Literal["new", "import"] = "new"
    storage: list[PlannedStorage] = Field(default_factory=list, max_length=50)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    selected_apps: list[str] = Field(default_factory=list, max_length=20)
    selected_imports: list[str] = Field(default_factory=list, max_length=200)


class SaveDraft(StrictModel):
    revision: int = Field(ge=0)
    draft: Draft


class SetupService:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()
        self.bootstrap_attempts = []
        with svc.sessions.begin() as db:
            if db.scalar(select(InstallationState)) is None:
                network = NetworkSettings(
                    base_url=svc.config.base_url,
                    allowed_origins=svc.config.allowed_origins,
                    trusted_proxies=svc.config.trusted_proxies,
                )
                storage = [
                    PlannedStorage(**item.model_dump()) for item in svc.config.setup_storage
                ]
                db.add(InstallationState(draft=Draft(network=network, storage=storage).model_dump()))

    def state(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(InstallationState))
            return {
                "setup_required": not row.setup_completed,
                "setup_completed": row.setup_completed,
                "setup_version": row.setup_version,
                "revision": row.revision,
                "draft": row.draft,
            }

    def bootstrap(self, username, password):
        clock = time.monotonic()
        self.bootstrap_attempts = [t for t in self.bootstrap_attempts if t > clock - 60]
        if len(self.bootstrap_attempts) >= 5:
            raise DomainError(
                "rate_limited", "Too many setup attempts; try again in one minute", 429
            )
        self.bootstrap_attempts.append(clock)
        if not self.svc.auth.needs_setup():
            raise DomainError(
                "already_initialized", "Administrator already exists; sign in instead", 409
            )
        self.svc.auth.create_admin(username, password)
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(InstallationState))
            draft = Draft.model_validate(row.draft)
            draft.step = 3
            row.draft = draft.model_dump()
            row.revision += 1

    def save(self, body: SaveDraft):
        if self.lock.locked():
            raise DomainError("setup_busy", "Setup is currently applying", 409)
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(InstallationState))
            if row.setup_completed:
                raise DomainError("setup_complete", "Setup has already completed", 409)
            if row.revision != body.revision:
                raise DomainError(
                    "revision_conflict", "Setup changed in another session; reload to continue", 409
                )
            for app in body.draft.selected_apps:
                self.svc.catalog.get(app)
            if len({s.name for s in body.draft.storage}) != len(body.draft.storage):
                raise DomainError("duplicate_storage", "Storage names must be unique")
            row.draft = body.draft.model_dump()
            row.revision += 1
            for record in db.scalars(select(PendingImport)):
                if record.source_id in body.draft.selected_imports:
                    record.status = "selected"
                elif record.status == "selected":
                    record.status = "discovered"
        return self.state()

    async def checks(self):
        runtime = await self.svc.agent.status()
        snapshot = self.svc.snapshot
        return {
            "core": [
                {"name": "Hostname", "state": "passed", "message": platform.node()},
                {
                    "name": "Operating system",
                    "state": "passed",
                    "message": platform.system() + " / " + platform.machine(),
                },
                {
                    "name": "CPU / RAM",
                    "state": "passed",
                    "message": f"{snapshot['cpu']['cores']} cores / {round(snapshot['ram']['totalBytes'] / 1024**3, 1)} GiB",
                },
                {
                    "name": "Core data directory",
                    "state": "passed" if os.access(self.svc.config.data_dir, os.W_OK) else "failed",
                    "message": "New Core database/config directory",
                },
                {
                    "name": "Disk capacity",
                    "state": "passed" if snapshot["disk"]["freeBytes"] > 1024**3 else "warning",
                    "message": f"{round(snapshot['disk']['freeBytes'] / 1024**3, 1)} GiB available",
                },
                {
                    "name": "Internet connectivity",
                    "state": "warning",
                    "message": "Not probed automatically. Core setup works offline; image downloads need connectivity later.",
                },
            ],
            "runtime": [
                {
                    "name": "Agent",
                    "state": "passed" if runtime["connected"] else "warning",
                    "message": runtime.get("version") or runtime.get("message", "Unavailable"),
                },
                {
                    "name": "Docker engine",
                    "state": "passed" if runtime.get("docker", {}).get("available") else "warning",
                    "message": "Required for future app installation, not for Core setup",
                },
                {
                    "name": "Compose",
                    "state": "passed"
                    if runtime.get("docker", {}).get("composeAvailable")
                    else "warning",
                    "message": runtime.get("docker", {}).get("composeVersion") or "Not detected",
                },
            ],
            "agent": runtime,
        }

    async def review(self):
        state = self.state()
        draft = Draft.model_validate(state["draft"])
        errors, warnings, storage = [], [], []
        if self.svc.auth.needs_setup():
            errors.append("An administrator is required")
        if not ip_address(draft.network.listen_host).is_loopback:
            warnings.append(
                "Broad/LAN binding: authentication does not encrypt HTTP. Configure safe external access yourself."
            )
        warnings.append(
            "Network settings are saved as pending; activation requires an explicit server restart with --saved-network."
        )
        if draft.network.port == 18767:
            errors.append("The chosen Core port conflicts with the default agent port")
        seen = set()
        with self.svc.sessions() as db:
            existing = [(r.name, r.path) for r in db.scalars(select(StorageLocation))]
        for item in draft.storage:
            if any(name == item.name and path != item.path for name, path in existing):
                errors.append(f"Storage name already belongs to another path: {item.name}")
            try:
                details = await self.svc.agent.request(
                    "POST", "/v1/directories/inspect", {"path": item.path}
                )
                if details["path"] in seen:
                    errors.append(f"Duplicate storage path: {item.name}")
                seen.add(details["path"])
                if item.action == "existing" and not details["readable"]:
                    errors.append(f"Storage is missing or unreadable: {item.name}")
                if item.action == "create" and item.confirmed_path != details["path"]:
                    errors.append(f"Exact new folder path must be confirmed: {item.name}")
                if item.action == "create" and details["exists"]:
                    warnings.append(f"Folder already exists and will not be modified: {item.name}")
                if not details["writable"] and item.action == "existing":
                    warnings.append(f"Storage is read-only: {item.name}")
                storage.append({**item.model_dump(), "inspection": details})
            except DomainError as error:
                errors.append(item.name + ": " + error.message)
        imports = await self.svc.imports.preview(draft.selected_imports)
        warnings.extend(
            f"Import blocked: {i['detected_app']}" for i in imports if i["status"] == "blocked"
        )
        for app in draft.selected_apps:
            warnings.append(
                self.svc.catalog.get(app).name + " is coming soon; no installation will execute"
            )
        return {
            "revision": state["revision"],
            "draft": draft.model_dump(),
            "storage": storage,
            "imports": imports,
            "errors": errors,
            "warnings": warnings,
            "canApply": not errors,
            "actions": [
                "Save Core configuration",
                "Create only explicitly confirmed new directories",
                "Save pending import plans",
                "Mark setup complete",
            ],
            "willMigrate": False,
        }

    async def apply(self, revision):
        async with self.lock:
            state = self.state()
            if state["setup_completed"]:
                return {"completed": True, "alreadyApplied": True}
            if state["revision"] != revision:
                raise DomainError(
                    "revision_conflict", "Review the current setup before applying", 409
                )
            review = await self.review()
            if not review["canApply"]:
                raise DomainError("setup_blocked", "Resolve the errors shown in Setup Review")
            draft = Draft.model_validate(state["draft"])
            for item in review["storage"]:
                if item["action"] == "create" and not item["inspection"]["exists"]:
                    await self.svc.agent.request(
                        "POST",
                        "/v1/directories/create",
                        {"path": item["path"], "confirmed_path": item["confirmed_path"]},
                    )
            # Creating directories is deliberately non-destructive. If an interrupted apply leaves
            # a directory behind, retry validates and reuses it; it never rolls back by deleting it.
            with self.svc.sessions.begin() as db:
                for item in draft.storage:
                    row = db.scalar(
                        select(StorageLocation).where(StorageLocation.path == item.path)
                    )
                    if row is None:
                        db.add(StorageLocation(name=item.name, kind=item.kind, path=item.path))
                setting = db.scalar(select(Setting).where(Setting.key == "network_pending"))
                if setting:
                    setting.value = draft.network.model_dump()
                else:
                    db.add(Setting(key="network_pending", value=draft.network.model_dump()))
                for plan in review["imports"]:
                    record = db.scalar(
                        select(PendingImport).where(PendingImport.source_id == plan["source_id"])
                    )
                    if record is None:
                        record = PendingImport(
                            **{
                                k: plan[k]
                                for k in [
                                    "source_type",
                                    "source_id",
                                    "detected_app",
                                    "target_app",
                                    "source_paths",
                                    "target_storage_mappings",
                                    "status",
                                    "findings",
                                ]
                            }
                        )
                        db.add(record)
                    else:
                        record.status, record.findings = plan["status"], plan["findings"]
                row = db.scalar(select(InstallationState))
                row.setup_completed = True
                row.draft = {**draft.model_dump(), "step": 9}
                row.revision += 1
            self.svc.events.record(
                "setup.completed",
                "core",
                "Setup completed; no app installation or migration executed",
            )
            return {"completed": True, "willMigrate": False, "networkRestartRequired": True}
