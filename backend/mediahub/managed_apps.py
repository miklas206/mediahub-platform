"""Explicit operator-owned app registrations and data-preserving Docker removal.

An address alone never grants lifecycle control. The read-only operator policy
binds each installation to Compose labels and optional owned runtime labels.
"""

import asyncio
import hashlib
import io
import json
import tarfile
import tomllib
from pathlib import Path
from urllib.parse import quote

import httpx
from pydantic import Field, field_validator
from sqlalchemy import select

from mediahub.contracts import Health, HealthCheck, StrictModel
from mediahub.db import InstalledApp
from mediahub.errors import DomainError

PACKAGES = {"org.mediahub.mediaseed": "MediaSeed", "org.mediahub.mediavpn": "MediaVPN"}


class Installation(StrictModel):
    installationId: str = Field(pattern=r"^[a-zA-Z0-9_-]{16,60}$")
    project: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,80}$")
    runtimeLabels: dict[str, str] = Field(default_factory=dict)
    integrationUrl: str | None = None
    integrationTokenFile: Path | None = None
    managementTokenFile: Path | None = None
    installFile: Path | None = None

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
            # One-shot initialization is expected to exit. With MediaVPN the
            # original isolated client is deliberately stopped; the owned
            # VPN-bound replacement is the active torrent service instead.
            active_clone = any(
                row.get("Config", {}).get("Labels", {}).get("org.mediahub.mediavpn.seedbox") == "mediaseed"
                and row.get("State", {}).get("Running")
                for row in rows
            )
            rows = [row for row in rows if row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
                    not in ({"client-init", "qbittorrent"} if active_clone else {"client-init"})]
            has_app = any(row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "app" for row in rows)
            checks = []
            for row in rows:
                state = row.get("State", {})
                service = row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") or "runtime"
                health = state.get("Health", {}).get("Status")
                status = "unhealthy" if health == "unhealthy" or state.get("Dead") else (
                    "degraded" if state.get("Restarting") or health == "starting" else
                    "healthy" if state.get("Running") else "unknown"
                )
                checks.append(HealthCheck(name=service, status=status,
                    message="Container unhealthy" if status == "unhealthy" else
                    "Container starting or restarting" if status == "degraded" else
                    "Container running" if state.get("Running") else "Container stopped"))
            running = has_app and bool(checks) and all(check.status == "healthy" for check in checks)
            overall = "healthy" if running else "unhealthy" if any(check.status == "unhealthy" for check in checks) else "degraded" if any(check.status == "degraded" for check in checks) else "unknown"
            return Health(
                status=overall,
                summary="App containers running" if running else "Check app runtime",
                checks=checks,
            )
        except DomainError:
            return Health(status="unknown", summary="App runtime unavailable", checks=[])

    async def updateCheck(self):
        from mediahub.platform_source import GitHubSourceProvider

        kind = self.package.rsplit(".", 1)[-1]
        root = Path(__file__).resolve().parents[2]
        bundled = root / "bundled" / kind / "pyproject.toml"
        if not bundled.is_file():
            bundled = root / "docker/bundled" / kind / "pyproject.toml"
        try:
            latest = tomllib.loads(bundled.read_text())["project"]["version"]
            rows = await self.manager.containers(self.package)
            versions = [row.get("Config", {}).get("Labels", {}).get("org.mediahub.app.version") for row in rows
                        if row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service") == "app"
                        and row.get("State", {}).get("Running")]
            installed = versions[0] if len(versions) == 1 else None
            dependencies = getattr(self.manager.svc, "app_dependencies", None)
            state = dependencies.public() if dependencies else {}
            monitor = getattr(self.manager.svc, "updates", None)
            upstream = await GitHubSourceProvider(
                installed or latest,
                metadata_cache=getattr(monitor, "github_metadata", None),
            ).check("miklas206/" + kind, self.manager.svc.release_credentials.token())
            return {"supported": False, "updateAvailable": False,
                    "installedVersion": installed, "latestVersion": upstream["latestVersion"],
                    "bundledVersion": latest, "repository": "miklas206/" + kind,
                    "checkStatus": "failed" if state.get("state") == "failed" else "checked" if installed == latest else "unchecked",
                    "message": state.get("message") if state.get("state") == "failed" else
                    "A newer app version exists on GitHub; it must be included in a MediaHub Core update before installation." if upstream["latestVersion"] != latest else
                    "This app is updated automatically with MediaHub Core. Retry app preparation if its bundled update is missing."}
        except DomainError:
            raise
        except (OSError, ValueError, KeyError):
            return {"supported": False, "checkStatus": "failed", "message": "Bundled app version could not be verified"}


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

    async def docker(self, method, path, missing=False, body=None):
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
                response = await client.request(method, path, json=body)
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
                running = bool(rows) and all(row.get("State", {}).get("Running") for row in rows)
                if not app and running and not (saved and saved["state"] == "succeeded"):
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
                    if not saved and rows and app.state != "uninstalled":
                        app.state = "running" if running else "stopped"
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
            if policy.managementTokenFile and getattr(self.svc, "shared_vpn", None):
                gateway = await self.svc.shared_vpn.vpn()
                if gateway.get("enabled") and gateway.get("peers"):
                    raise DomainError(
                        "app_dependency",
                        "Disconnect Plex and Jellyfin from shared VPN before removing MediaVPN",
                        409,
                    )
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
        identity = hashlib.sha256(
            json.dumps(
                sorted(
                    [
                        (row["Id"], row.get("Config", {}).get("Labels"), row.get("Mounts", []))
                        for row in rows
                    ],
                    key=lambda row: row[0],
                ),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return rows, policy.installationId + ":" + identity[:16]

    @staticmethod
    def matches_snapshot(rows, saved):
        """Already removed containers may be absent; replacements require new consent."""
        expected = {row["Id"]: row for row in saved["containers"]}
        return all(
            row["Id"] in expected
            and row.get("Config", {}).get("Labels")
            == expected[row["Id"]].get("Config", {}).get("Labels")
            and row.get("Mounts", []) == expected[row["Id"]].get("Mounts", [])
            for row in rows
        )

    async def status(self, package):
        saved = self.saved(package)
        if saved and saved["state"] == "failed":
            rows, confirmation = await self.preflight(package)
            if not self.matches_snapshot(rows, saved):
                return {
                    "state": "ready",
                    "installationId": confirmation,
                    "mode": "runtime",
                    "message": "Installation changed; review removal again",
                }
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
            active = self.tasks.get(package)
            if active and not active.done():
                raise DomainError("operation_busy", "Another app operation is running", 409)
            rows, confirmation = await self.preflight(package)
            retry_snapshot = (
                saved and saved["state"] == "failed" and self.matches_snapshot(rows, saved)
            )
            if retry_snapshot:
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
            if saved and saved["state"] == "failed":
                # Include volumes from any already removed containers in final preservation checks.
                volumes.update(saved["volumes"])
            job = {
                "state": "accepted",
                "progress": 0,
                "phase": "preparing",
                "installationId": self.policy[package].installationId,
                "confirmation": confirmation,
                "containers": rows,
                "volumes": sorted(volumes),
                "message": "Afinstallation er startet. Data bevares.",
            }
            if retry_snapshot:
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

    async def controller_settings(self, identifier):
        """Read the fixed non-secret settings file even when the owned app is stopped."""
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(
                    uds=str(self.svc.config.managed_apps_docker_socket)
                ),
                base_url="http://docker",
                timeout=10,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "GET",
                    "/containers/" + identifier + "/archive",
                    params={"path": "/data/seedbox.json"},
                ) as response:
                    if response.status_code == 404:
                        return None
                    response.raise_for_status()
                    content = bytearray()
                    async for block in response.aiter_bytes():
                        content.extend(block)
                        if len(content) > 32768:
                            raise ValueError("Settings archive too large")
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
                entries = archive.getmembers()
                if (
                    len(entries) != 1
                    or entries[0].name != "seedbox.json"
                    or not entries[0].isfile()
                    or entries[0].size > 4096
                ):
                    raise ValueError("Invalid settings archive")
                settings = json.loads(archive.extractfile(entries[0]).read())
                if not isinstance(settings, dict) or type(settings.get("enabled")) is not bool:
                    raise ValueError("Invalid settings")
                return settings
        except (httpx.HTTPError, ValueError, OSError, tarfile.TarError):
            raise DomainError(
                "controller_unverified",
                "Stopped torrent controller settings could not be verified; no app containers were removed",
                409,
            ) from None

    async def controller_inactive(self, rows):
        policy = self.policy["org.mediahub.mediavpn"]
        controller = next(
            (
                row
                for row in rows
                if row.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
                == "app"
                and row.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
                == policy.project
            ),
            None,
        )
        if controller is None or controller.get("State", {}).get("Running") is not False:
            return False
        settings = await self.controller_settings(controller["Id"])
        actual = await self.docker("GET", "/containers/" + controller["Id"] + "/json", missing=True)
        if (
            not actual
            or actual.get("State", {}).get("Running") is not False
            or actual.get("Config", {}).get("Labels") != controller["Config"]["Labels"]
        ):
            raise DomainError("installation_changed", "Installation changed during removal", 409)
        if settings is not None and settings["enabled"]:
            raise DomainError(
                "controller_start_required",
                "Start MediaVPN and disconnect MediaSeed before removal; stopped torrent control is still enabled",
                409,
            )
        # A missing settings file is the controller's documented disabled default.
        return True

    async def run(self, package, job):
        async with self.lock:
            try:
                job.update(state="running", progress=5, phase="preparing")
                self.save(package, job)
                # Revalidate before any writes, including the controller disconnect.
                current, _ = await self.preflight(package)
                if not self.matches_snapshot(current, job):
                    raise DomainError(
                        "installation_changed", "Installation changed during removal", 409
                    )
                has_client = any(
                    row.get("Config", {}).get("Labels", {}).get("org.mediahub.mediavpn.seedbox")
                    == "mediaseed"
                    for row in current
                )
                # An enabled controller may be waiting for VPN health and have
                # no client yet. Fence it before deleting its source containers.
                vpn_rows = (
                    await self.containers("org.mediahub.mediavpn")
                    if package == "org.mediahub.mediaseed"
                    and "org.mediahub.mediavpn" in self.policy
                    else []
                )
                inactive = bool(vpn_rows) and await self.controller_inactive(vpn_rows)
                if (has_client or vpn_rows) and not inactive:
                    await self.disconnect_client(self.policy[package])
                job.update(progress=10, phase="removing")
                self.save(package, job)
                for index, row in enumerate(job["containers"]):
                    identifier = row["Id"]
                    actual = await self.docker(
                        "GET", "/containers/" + identifier + "/json", missing=True
                    )
                    if actual is None:
                        job["progress"] = 10 + round(
                            70 * (index + 1) / max(1, len(job["containers"]))
                        )
                        self.save(package, job)
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
                    job["progress"] = 10 + round(70 * (index + 1) / max(1, len(job["containers"])))
                    self.save(package, job)
                job.update(progress=90, phase="verifying")
                self.save(package, job)
                if await self.containers(package):
                    raise DomainError(
                        "removal_unverified", "App containers remain after removal", 409
                    )
                for volume in job["volumes"]:
                    await self.docker("GET", "/volumes/" + quote(volume, safe=""))
                with self.svc.sessions.begin() as db:
                    app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
                    if app:
                        app.state = "uninstalled"
                (
                    self.svc.config.data_dir
                    / ("managed-install-" + package.rsplit(".", 1)[-1] + ".json")
                ).unlink(missing_ok=True)
                self.svc.events.record(
                    "app.uninstalled", package, "Managed runtime removed; persistent data preserved"
                )
                job.update(
                    state="succeeded",
                    progress=100,
                    phase="complete",
                    dataPreserved=True,
                    message="Appen er afinstalleret. Data er bevaret.",
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
