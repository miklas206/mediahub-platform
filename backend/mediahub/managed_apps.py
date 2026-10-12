"""Explicit operator-owned app registrations and data-preserving Docker removal.

An address alone never grants lifecycle control. The read-only operator policy
binds each installation to Compose labels and optional owned runtime labels.
"""

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import Field, field_validator
from sqlalchemy import select

from mediahub.contracts import Health, StrictModel
from mediahub.db import InstalledApp
from mediahub.errors import DomainError

PACKAGES = {"org.mediahub.mediaseed": "MediaSeed", "org.mediahub.mediavpn": "MediaVPN"}


class Installation(StrictModel):
    installationId: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,60}$")
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,80}$")
    runtimeLabels: dict[str, str] = Field(default_factory=dict)
    integrationUrl: str | None = None
    integrationTokenFile: Path | None = None

    @field_validator("runtimeLabels")
    @classmethod
    def owned_labels(cls, labels):
        if any(
            key not in {"org.mediahub.mediavpn.seedbox", "org.mediahub.mediavpn.owner"}
            or value not in {"mediaseed", "mediavpn"}
            for key, value in labels.items()
        ):
            raise ValueError("Unsupported runtime ownership labels")
        return labels

    @field_validator("integrationUrl")
    @classmethod
    def private_integration(cls, value):
        from mediahub.mediaseed_api import app_origin

        if value and not app_origin(value):
            raise ValueError("Integration requires an explicit private origin")
        return value.rstrip("/") if value else value


class ManagedAdapter:
    managed = True

    def __init__(self, manager, package):
        self.manager, self.package = manager, package

    async def health(self):
        try:
            rows = await self.manager.containers(self.package)
            running = bool(rows) and all(
                row.get("State", {}).get("Running")
                and row.get("State", {}).get("Health", {}).get("Status", "healthy") == "healthy"
                for row in rows
            )
            return Health(
                status="healthy" if running else "unknown",
                summary="App containers running" if running else "Check app runtime",
                checks=[],
            )
        except DomainError:
            return Health(status="unknown", summary="App runtime unavailable", checks=[])

    async def updateCheck(self):
        return {"supported": False, "reason": "Managed app updates require an explicit release"}


class ManagedApps:
    def __init__(self, svc):
        self.svc = svc
        self.policy = {}
        self.lock = asyncio.Lock()
        self.tasks = {}
        policy_file = svc.config.managed_apps_policy_file
        if policy_file:
            raw = json.loads(policy_file.read_text())
            if not isinstance(raw, dict) or set(raw) - PACKAGES.keys():
                raise ValueError("Unsupported managed app policy")
            self.policy = {key: Installation.model_validate(value) for key, value in raw.items()}
            if len({entry.project for entry in self.policy.values()}) != len(self.policy):
                raise ValueError("Managed Compose projects must be distinct")
            for package, policy in self.policy.items():
                expected = (
                    {"org.mediahub.mediavpn.seedbox": "mediaseed"}
                    if package.endswith("mediaseed")
                    else {"org.mediahub.mediavpn.owner": "mediavpn"}
                )
                if policy.runtimeLabels and policy.runtimeLabels != expected:
                    raise ValueError("Runtime ownership does not match the managed app")
                if (
                    package.endswith("mediaseed")
                    and policy.runtimeLabels
                    and not (policy.integrationUrl and policy.integrationTokenFile)
                ):
                    raise ValueError("Managed torrent removal requires its controller integration")

    def journal(self, package):
        return self.svc.config.data_dir / (
            "managed-removal-" + package.rsplit(".", 1)[-1] + ".json"
        )

    def saved(self, package):
        path = self.journal(package)
        if not path.exists():
            return None
        value = json.loads(path.read_text())
        return value if value.get("installationId") == self.policy[package].installationId else None

    def save(self, package, value):
        from agent.install_files import save_json

        save_json(self.journal(package), value)

    async def docker(self, method, path, missing=False):
        socket = self.svc.config.managed_apps_docker_socket
        if not socket:
            raise DomainError(
                "runtime_unavailable", "Managed Docker runtime is not configured", 503
            )
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(socket)),
                base_url="http://docker",
                timeout=45,
                trust_env=False,
            ) as client:
                response = await client.request(method, path)
            if missing and response.status_code == 404:
                return None
            if response.status_code == 304 and method == "POST" and "/stop?" in path:
                return {}
            response.raise_for_status()
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise DomainError(
                "runtime_unavailable", "Managed app runtime operation failed", 503
            ) from None

    async def containers(self, package):
        policy = self.policy[package]
        selectors = [{"com.docker.compose.project": policy.project}]
        if policy.runtimeLabels:
            selectors.append(policy.runtimeLabels)
        found = {}
        for labels in selectors:
            filters = quote(
                json.dumps({"label": [key + "=" + value for key, value in labels.items()]})
            )
            rows = await self.docker("GET", "/containers/json?all=1&filters=" + filters)
            for row in rows:
                identifier = row["Id"]
                inspected = await self.docker("GET", "/containers/" + identifier + "/json")
                actual = inspected.get("Config", {}).get("Labels") or {}
                if not all(actual.get(key) == value for key, value in labels.items()):
                    raise DomainError(
                        "installation_changed", "App container ownership changed", 409
                    )
                if inspected.get("HostConfig", {}).get("AutoRemove"):
                    raise DomainError(
                        "unsafe_runtime", "Automatic container removal is not supported", 409
                    )
                found[identifier] = {
                    "Id": identifier,
                    "Name": inspected.get("Name"),
                    "Config": {"Labels": actual},
                    "State": inspected.get("State", {}),
                    "Mounts": inspected.get("Mounts", []),
                }
        return list(found.values())

    async def initialize(self):
        for package in self.policy:
            saved = self.saved(package)
            try:
                rows = await self.containers(package)
            except DomainError:
                rows = []
            with self.svc.sessions.begin() as db:
                app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
                if not app and rows and not (saved and saved["state"] == "succeeded"):
                    app = InstalledApp(
                        package_id=package,
                        name=PACKAGES[package],
                        version="managed",
                        state="running",
                        is_mock=False,
                    )
                    db.add(app)
                    db.flush()
                if app:
                    self.svc.apps.adapters[app.id] = ManagedAdapter(self, package)
                    if not saved and rows:
                        app.state = "running"
                    if saved and saved["state"] in {"accepted", "running", "failed"}:
                        app.state = "removing"
                    elif saved and saved["state"] == "succeeded":
                        app.state = "uninstalled"
            if saved and saved["state"] in {"accepted", "running"}:
                self.tasks[package] = asyncio.create_task(self.run(package, saved))

    async def preflight(self, package):
        rows = await self.containers(package)
        policy = self.policy[package]
        if package.endswith("mediavpn"):
            filters = quote(json.dumps({"label": ["org.mediahub.mediavpn.seedbox=mediaseed"]}))
            clients = await self.docker("GET", "/containers/json?all=1&filters=" + filters)
            if clients:
                raise DomainError(
                    "app_dependency",
                    "Frakobl MediaVPN under VPN i MediaSeed først. Derefter kan MediaVPN afinstalleres uden at fjerne MediaSeed.",
                    409,
                )
        owned = {row["Id"] for row in rows}
        others = await self.docker("GET", "/containers/json?all=1")
        for other in others:
            if other["Id"] in owned:
                continue
            inspected = await self.docker("GET", "/containers/" + other["Id"] + "/json")
            mode = inspected.get("HostConfig", {}).get("NetworkMode", "")
            if mode.startswith("container:") and any(
                row["Id"].startswith(mode[10:]) or row.get("Name", "").lstrip("/") == mode[10:]
                for row in rows
            ):
                raise DomainError(
                    "app_dependency",
                    "Another app uses this runtime. Disconnect it before removal.",
                    409,
                )
        identity = hashlib.sha256(json.dumps(sorted(owned)).encode()).hexdigest()
        return rows, policy.installationId + ":" + identity[:16]

    async def status(self, package):
        saved = self.saved(package)
        if saved:
            return {
                **{
                    key: value
                    for key, value in saved.items()
                    if key not in {"containers", "volumes", "confirmation"}
                },
                "installationId": saved["confirmation"],
            }
        rows, confirmation = await self.preflight(package)
        if not rows:
            raise DomainError(
                "installation_missing", "Managed installation is no longer present", 409
            )
        return {
            "state": "ready",
            "installationId": confirmation,
            "mode": "runtime",
            "message": "Appens containere fjernes, og aktive overførsler stopper. Downloads, appdata, credentials og VPN-profiler bevares.",
        }

    async def remove(self, package, confirmed):
        async with self.lock:
            saved = self.saved(package)
            if saved and saved["state"] in {"accepted", "running", "succeeded"}:
                if confirmed != saved.get("confirmation"):
                    raise DomainError(
                        "confirmation_required", "Exact installation confirmation required", 409
                    )
                return await self.status(package)
            rows, confirmation = await self.preflight(package)
            if saved and saved["state"] == "failed":
                confirmation = saved["confirmation"]
            if confirmed != confirmation or not (rows or saved):
                raise DomainError(
                    "installation_changed", "Installation changed; review removal again", 409
                )
            volumes = {
                mount["Name"]
                for row in rows
                for mount in row.get("Mounts", [])
                if mount["Type"] == "volume"
            }
            job = {
                "state": "accepted",
                "installationId": self.policy[package].installationId,
                "confirmation": confirmation,
                "containers": rows,
                "volumes": sorted(volumes),
                "message": "Afinstallation er startet. Data bevares.",
            }
            if saved:
                job["containers"] = saved["containers"]
                job["volumes"] = saved["volumes"]
            self.save(package, job)
            self.tasks[package] = asyncio.create_task(self.run(package, job))
            return await self.status(package)

    async def disconnect_client(self, policy):
        if not policy.integrationUrl:
            return
        try:
            token = policy.integrationTokenFile.read_text().strip()
            async with httpx.AsyncClient(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                headers = {"X-MediaSeed-Key": token}
                response = await client.get(
                    policy.integrationUrl + "/api/integration/status", headers=headers
                )
                response.raise_for_status()
                profile = response.json().get("profileId")
                response = await client.put(
                    policy.integrationUrl + "/api/integration/settings",
                    headers=headers,
                    json={"enabled": False, "profileId": profile},
                )
                response.raise_for_status()
                if response.json().get("enabled") is not False:
                    raise ValueError()
        except (OSError, httpx.HTTPError, ValueError):
            raise DomainError(
                "integration_unavailable",
                "Torrent controller could not be disconnected; no app containers were removed",
                409,
            ) from None

    async def run(self, package, job):
        async with self.lock:
            try:
                job["state"] = "running"
                self.save(package, job)
                # Revalidate before any writes, including the controller disconnect.
                current, _ = await self.preflight(package)
                expected = {row["Id"] for row in job["containers"]}
                if any(row["Id"] not in expected for row in current):
                    raise DomainError(
                        "installation_changed", "Installation changed during removal", 409
                    )
                if any(
                    row.get("Config", {}).get("Labels", {}).get("org.mediahub.mediavpn.seedbox") == "mediaseed"
                    for row in current
                ):
                    await self.disconnect_client(self.policy[package])
                for row in job["containers"]:
                    identifier = row["Id"]
                    actual = await self.docker(
                        "GET", "/containers/" + identifier + "/json", missing=True
                    )
                    if actual is None:
                        continue
                    if actual.get("Config", {}).get("Labels") != row.get("Config", {}).get(
                        "Labels"
                    ):
                        raise DomainError(
                            "installation_changed", "App container ownership changed", 409
                        )
                    await self.docker("POST", "/containers/" + identifier + "/stop?t=20")
                    await self.docker(
                        "DELETE", "/containers/" + identifier + "?force=false&v=false"
                    )
                if await self.containers(package):
                    raise DomainError(
                        "removal_unverified", "App containers remain after removal", 409
                    )
                for volume in job["volumes"]:
                    await self.docker("GET", "/volumes/" + quote(volume, safe=""))
                job.update(
                    state="succeeded",
                    dataPreserved=True,
                    message="Appen er afinstalleret. Data er bevaret.",
                )
                with self.svc.sessions.begin() as db:
                    app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
                    if app:
                        app.state = "uninstalled"
                self.svc.events.record(
                    "app.uninstalled", package, "Managed runtime removed; persistent data preserved"
                )
            except DomainError as error:
                job.update(state="failed", message=error.message)
            except Exception:
                job.update(
                    state="failed",
                    message="Removal could not be verified. Review the app runtime before retrying.",
                )
            self.save(package, job)

    async def close(self):
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


def unavailable(svc, package, removed_only=False):
    with svc.sessions() as db:
        app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
        states = {"uninstalled"} if removed_only else {"removing", "uninstalled"}
        return bool(app and app.state in states)
