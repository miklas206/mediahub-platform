import asyncio
import contextlib
import hashlib
import ipaddress
import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from mediahub.apps.containers import CONTAINER_APPS, ContainerInstallation, container_slots
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field, field_validator

from agent.install_files import read_json, save_json
from agent.plex_control import PlexControl


class ContainerStorage(StrictModel):
    label: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern=r"^(appdata|movies|tv|downloads)$")
    path: str

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        path = Path(value)
        if not path.is_absolute() or path == Path(path.anchor) or ".." in path.parts:
            raise ValueError("Expected an absolute non-root storage path")
        return value


class ContainerPolicy(StrictModel):
    hostId: str = Field(min_length=1, max_length=80)
    bindAddress: str
    uid: int = Field(default=1000, ge=1, le=65535)
    gid: int = Field(default=1000, ge=1, le=65535)
    storage: dict[str, ContainerStorage]
    hostMountSnapshot: str
    requiredMounts: dict[str, str] = Field(default_factory=dict)
    requiredFilesystemUuids: dict[str, str] = Field(default_factory=dict)
    storageMarkers: dict[str, str]

    @field_validator("bindAddress")
    @classmethod
    def private_address(cls, value):
        address = ipaddress.ip_address(value)
        if (
            address.version != 4
            or not address.is_private
            or address.is_loopback
            or address.is_unspecified
            or address.is_multicast
            or address.is_link_local
        ):
            raise ValueError("Choose an explicit private LAN IPv4 address")
        return value


class ContainerApps:
    def __init__(self, policy_file, socket, state_dir):
        self.policy_file, self.socket = policy_file, socket
        self.state_dir = Path(state_dir)
        self.locks = {app: asyncio.Lock() for app in CONTAINER_APPS}
        self.network_lock = asyncio.Lock()
        self.tasks = {}
        self.operations = {}
        self.storage_control = PlexControl(None, socket)

    def policy(self):
        try:
            if not self.policy_file:
                raise ValueError()
            return ContainerPolicy.model_validate(read_json(Path(self.policy_file)))
        except (OSError, ValueError, TypeError):
            raise DomainError(
                "container_install_disabled",
                "Container app host policy has not been configured",
                409,
            ) from None

    def app(self, app):
        if app not in CONTAINER_APPS:
            raise DomainError("not_found", "Container app not found", 404)
        return CONTAINER_APPS[app]

    def record_path(self, app):
        self.app(app)
        return self.state_dir / ("container-app-" + app + ".json")

    def record(self, app):
        try:
            return read_json(self.record_path(app))
        except FileNotFoundError:
            return None

    async def request(self, method, path, body=None, missing=False):
        if not self.socket:
            raise DomainError("runtime_unavailable", "Docker socket is not configured", 503)
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.socket)),
                base_url="http://docker",
                timeout=httpx.Timeout(
                    600 if path.startswith("/images/create") else 60 if method != "GET" else 10,
                    connect=5,
                ),
                trust_env=False,
            ) as client:
                async with client.stream(method, path, json=body) as response:
                    if missing and response.status_code == 404:
                        return None
                    response.raise_for_status()
                    if path.startswith("/images/create"):
                        async for line in response.aiter_lines():
                            if len(line) > 262144 or (line and json.loads(line).get("error")):
                                raise ValueError()
                        return {}
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 4 * 1024**2:
                            raise ValueError()
                    return json.loads(content) if content else {}
        except (httpx.HTTPError, ValueError):
            raise DomainError(
                "container_runtime_failed",
                "Container runtime operation failed; persistent data retained",
                503,
            ) from None

    async def options(self, app):
        definition, policy = self.app(app), self.policy()
        return {
            "hostId": policy.hostId,
            "name": definition["name"],
            "port": definition["port"],
            "slots": [
                {"id": slot, "required": required, "readOnly": read_only}
                for slot, (_, read_only, required) in container_slots(app).items()
            ],
            "storage": [
                {"id": key, "label": choice.label, "kind": choice.kind}
                for key, choice in policy.storage.items()
            ],
        }

    async def build_plan(self, spec):
        policy, definition = self.policy(), self.app(spec.app)
        if spec.hostId != policy.hostId:
            raise DomainError("container_host_mismatch", "Host does not match approved policy", 409)
        if not await self.storage_control.storage_verified(policy):
            raise DomainError("storage_unverified", "Approved storage is not verified mounted", 409)
        slots = container_slots(spec.app)
        if set(spec.storageIds) - slots.keys():
            raise DomainError("invalid_mapping", "Unknown storage slot", 400)
        mounts = []
        roots = [Path(root) for root in (*policy.requiredMounts, *policy.requiredFilesystemUuids)]
        for slot, (target, read_only, required) in slots.items():
            identifier = spec.storageIds.get(slot)
            if not identifier and not required:
                continue
            choice = policy.storage.get(identifier)
            if not choice or choice.kind != slot:
                raise DomainError("invalid_mapping", "Choose approved storage for " + slot, 400)
            path = Path(choice.path)
            if (
                path.resolve() != path
                or not path.is_dir()
                or not any(path == root or root in path.parents for root in roots)
            ):
                raise DomainError(
                    "unsafe_storage", "Storage must be an existing verified directory", 409
                )
            if not os.access(path, os.R_OK | (0 if read_only else os.W_OK)):
                raise DomainError("storage_denied", "Storage permissions are insufficient", 409)
            if slot == "appdata":
                path = path / ("mediahub-" + spec.app)
                if path.exists() and (path.resolve() != path or not path.is_dir()):
                    raise DomainError(
                        "unsafe_storage", "App configuration directory is unsafe", 409
                    )
            mounts.append(
                {"Type": "bind", "Source": str(path), "Target": target, "ReadOnly": read_only}
            )
        config = next(Path(mount["Source"]) for mount in mounts if mount["Target"] == "/config")
        for mount in mounts:
            path = Path(mount["Source"])
            if path != config and (path in config.parents or config in path.parents):
                raise DomainError(
                    "storage_overlap", "App configuration and media must be separate", 409
                )
        if spec.app == "jellyfin":
            mounts.append(
                {
                    "Type": "bind",
                    "Source": str(config / "cache"),
                    "Target": "/cache",
                    "ReadOnly": False,
                }
            )
        port = str(definition["port"]) + "/tcp"
        name = "mediahub-" + spec.app
        environment = ["TZ=" + spec.timezone]
        linuxserver = definition["repository"].startswith("linuxserver/")
        if spec.app == "autobrr":
            environment += ["AUTOBRR__HOST=0.0.0.0", "AUTOBRR__PORT=7474"]
        container = {
            "Image": definition["repository"] + "@" + definition["digest"],
            "User": f"{policy.uid}:{policy.gid}",
            "Env": environment,
            "ExposedPorts": {port: {}},
            "Labels": {
                "org.mediahub.package": "org.mediahub." + spec.app,
                "org.mediahub.installation": name,
            },
            "HostConfig": {
                "Mounts": mounts,
                "NetworkMode": "mediahub-apps",
                "PortBindings": {
                    port: [{"HostIp": policy.bindAddress, "HostPort": str(definition["port"])}]
                },
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "RestartPolicy": {"Name": "no"},
                "Memory": 2 * 1024**3 if spec.app == "jellyfin" else 1024**3,
                "MemorySwap": 2 * 1024**3 if spec.app == "jellyfin" else 1024**3,
                "PidsLimit": 512,
                "LogConfig": {"Type": "none", "Config": {}},
                "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
            },
        }
        if linuxserver:
            container["HostConfig"]["Tmpfs"] = {
                "/run": f"rw,exec,nosuid,nodev,size=64m,uid={policy.uid},gid={policy.gid}"
            }
        digest = hashlib.sha256(
            json.dumps({"spec": spec.model_dump(), "container": container}, sort_keys=True).encode()
        ).hexdigest()
        return {
            "name": name,
            "container": container,
            "planDigest": digest,
            "installation": spec.model_dump(),
            "url": f"http://{policy.bindAddress}:{definition['port']}",
        }

    async def plan(self, spec):
        plan = await self.build_plan(spec)
        return {
            "planDigest": plan["planDigest"],
            "installation": plan["installation"],
            "url": plan["url"],
            "dataPreserved": True,
            "mounts": [
                {"target": mount["Target"], "readOnly": mount["ReadOnly"]}
                for mount in plan["container"]["HostConfig"]["Mounts"]
            ],
        }

    async def install(self, body):
        app = body.installation.app
        if self.locks[app].locked():
            raise DomainError("operation_busy", "A container operation is running", 409)
        async with self.locks[app]:
            if app in self.tasks and not self.tasks[app].done():
                raise DomainError("operation_busy", "An installation is already running", 409)
            plan = await self.build_plan(body.installation)
            if plan["planDigest"] != body.confirmedPlanDigest:
                raise DomainError("plan_changed", "Preview the updated plan before installing", 409)
            existing = await self.request("GET", f"/containers/{plan['name']}/json", missing=True)
            if existing:
                record = self.record(app)
                if not record or record["planDigest"] != plan["planDigest"]:
                    raise DomainError("container_conflict", "Container name is already in use", 409)
                self.verify(existing, record)
                record["desiredRunning"] = True
                save_json(self.record_path(app), record)
                if not existing["State"].get("Running"):
                    await self.request("POST", f"/containers/{plan['name']}/start")
                self.operations.pop(app, None)
                return {"state": "installed", "url": plan["url"], "dataPreserved": True}
            self.operations[app] = {
                "state": "installing",
                "message": "Downloading and starting container",
            }
            self.tasks[app] = asyncio.create_task(self.provision(app, plan))
            return {"state": "accepted", "url": plan["url"], "dataPreserved": True}

    async def provision(self, app, plan):
        try:
            async with self.locks[app]:
                policy = self.policy()
                await self.request(
                    "POST", "/images/create?fromImage=" + quote(plan["container"]["Image"], safe="")
                )
                image = await self.request(
                    "GET", "/images/" + quote(plan["container"]["Image"], safe="") + "/json"
                )
                plan["imageId"] = image["Id"]
                current = await self.build_plan(
                    ContainerInstallation.model_validate(plan["installation"])
                )
                if current["planDigest"] != plan["planDigest"]:
                    raise DomainError(
                        "plan_changed", "Approved installation policy changed during download", 409
                    )
                if not await self.storage_control.storage_verified(policy):
                    raise DomainError("storage_unverified", "Storage verification expired", 409)
                async with self.network_lock:
                    network = await self.request("GET", "/networks/mediahub-apps", missing=True)
                    if network is None:
                        await self.request(
                            "POST",
                            "/networks/create",
                            {
                                "Name": "mediahub-apps",
                                "Driver": "bridge",
                                "Labels": {"org.mediahub.network": "apps"},
                                "CheckDuplicate": True,
                            },
                        )
                    elif (
                        network.get("Labels", {}).get("org.mediahub.network") != "apps"
                        or network.get("Driver") != "bridge"
                        or network.get("Internal") is not False
                    ):
                        raise DomainError("network_conflict", "Container network is not owned", 409)
                for mount in plan["container"]["HostConfig"]["Mounts"]:
                    if mount["Target"] not in {"/config", "/cache"}:
                        continue
                    path = Path(mount["Source"])
                    if path.resolve() != path:
                        raise DomainError("unsafe_storage", "Configuration path changed", 409)
                    path.mkdir(mode=0o700, exist_ok=True)
                    if os.name == "posix" and os.geteuid() == 0:
                        os.chown(path, policy.uid, policy.gid)
                    elif os.name == "posix" and path.stat().st_uid != policy.uid:
                        raise DomainError(
                            "storage_owner", "Configuration owner must match app UID", 409
                        )
                plan["desiredRunning"] = False
                save_json(self.record_path(app), plan)
                await self.request(
                    "POST", "/containers/create?name=" + plan["name"], plan["container"]
                )
                inspected = await self.request("GET", f"/containers/{plan['name']}/json")
                self.verify(inspected, plan)
                plan["desiredRunning"] = True
                save_json(self.record_path(app), plan)
                await self.request("POST", f"/containers/{plan['name']}/start")
                self.operations[app] = {"state": "installed", "message": "Container started"}
        except Exception:
            self.operations[app] = {
                "state": "failed",
                "message": "Installation failed; persistent data retained",
            }

    def verify(self, inspected, record):
        expected = record["container"]
        mounts = sorted(
            (mount["Source"], mount["Target"], mount["ReadOnly"])
            for mount in expected["HostConfig"]["Mounts"]
        )
        actual = sorted(
            (mount["Source"], mount["Destination"], not mount["RW"])
            for mount in inspected.get("Mounts", [])
        )
        labels = inspected.get("Config", {}).get("Labels", {})
        if (
            any(labels.get(key) != value for key, value in expected["Labels"].items())
            or inspected.get("Image") != record.get("imageId")
            or mounts != actual
            or inspected.get("Config", {}).get("User") != expected["User"]
            or inspected.get("HostConfig", {}).get("Privileged") is not False
            or inspected.get("HostConfig", {}).get("NetworkMode") != "mediahub-apps"
            or inspected.get("HostConfig", {}).get("CapDrop") != ["ALL"]
            or (inspected.get("HostConfig", {}).get("CapAdd") or [])
            or (inspected.get("HostConfig", {}).get("Tmpfs") or {})
            != expected["HostConfig"].get("Tmpfs", {})
            or inspected.get("HostConfig", {}).get("SecurityOpt") != ["no-new-privileges:true"]
            or inspected.get("HostConfig", {}).get("PortBindings")
            != expected["HostConfig"]["PortBindings"]
        ):
            raise DomainError("ownership_mismatch", "Container no longer matches installation", 409)

    async def status(self, app):
        self.app(app)
        record = self.record(app)
        operation = self.operations.get(app, {})
        state = operation.get("state", "not-installed")
        health, url = "unknown", record.get("url") if record else None
        if record and state not in {"installing", "failed"}:
            inspected = await self.request(
                "GET", f"/containers/{record['name']}/json", missing=True
            )
            if inspected:
                self.verify(inspected, record)
                state = "running" if inspected.get("State", {}).get("Running") else "stopped"
                health = "unknown" if state == "running" else "degraded"
            else:
                state = "removed"
        return {
            "health": health,
            "state": state,
            "installationId": "mediahub-" + app,
            "observedAt": time.time(),
            "hostId": self.policy().hostId,
            "agentOnline": True,
            "dockerHealthy": state in {"running", "stopped"},
            "url": url,
            "checks": [],
            "operation": operation,
            "dataPreserved": True,
            "healthVerified": False,
        }

    async def action(self, app, action, confirmation=None):
        self.app(app)
        if self.locks[app].locked():
            raise DomainError("operation_busy", "A container operation is running", 409)
        if action not in {"start", "stop", "restart", "uninstall"}:
            raise DomainError("unsupported_action", "Unsupported container action", 400)
        async with self.locks[app]:
            record = self.record(app)
            if not record:
                if action == "uninstall" and confirmation == "mediahub-" + app:
                    self.operations.pop(app, None)
                    return {"state": "succeeded", "dataPreserved": True}
                raise DomainError("not_installed", "Install the app first", 409)
            if action == "uninstall" and confirmation != record["name"]:
                raise DomainError("confirmation_required", "Confirm the installation name", 409)
            inspected = await self.request(
                "GET", f"/containers/{record['name']}/json", missing=True
            )
            if inspected is None:
                if action == "uninstall":
                    return {"state": "succeeded", "dataPreserved": True}
                raise DomainError("not_installed", "Container is missing", 409)
            self.verify(inspected, record)
            if action in {"start", "restart"}:
                if not await self.storage_control.storage_verified(self.policy()):
                    raise DomainError("storage_unverified", "Storage is not verified mounted", 409)
            record["desiredRunning"] = action in {"start", "restart"}
            save_json(self.record_path(app), record)
            if action == "uninstall":
                if inspected["State"].get("Running"):
                    await self.request("POST", f"/containers/{record['name']}/stop?t=30")
                await self.request("DELETE", f"/containers/{record['name']}?force=false&v=false")
                self.operations.pop(app, None)
                return {"state": "succeeded", "dataPreserved": True}
            if (action == "start" and inspected["State"].get("Running")) or (
                action == "stop" and not inspected["State"].get("Running")
            ):
                return {"state": "accepted", "dataPreserved": True}
            await self.request("POST", f"/containers/{record['name']}/{action}?t=30")
            self.operations.pop(app, None)
            return {"state": "accepted", "dataPreserved": True}

    async def monitor(self):
        while True:
            for app in CONTAINER_APPS:
                if self.locks[app].locked():
                    continue
                try:
                    async with self.locks[app]:
                        record = self.record(app)
                        if not record:
                            continue
                        inspected = await self.request(
                            "GET", f"/containers/{record['name']}/json", missing=True
                        )
                        if inspected is None:
                            continue
                        self.verify(inspected, record)
                        ready = await self.storage_control.storage_verified(self.policy())
                        running = inspected["State"].get("Running")
                        desired = record.get("desiredRunning") is True
                        if running and (not ready or not desired):
                            await self.request("POST", f"/containers/{record['name']}/stop?t=30")
                        elif not running and ready and desired:
                            await self.request("POST", f"/containers/{record['name']}/start")
                except (DomainError, OSError, ValueError, KeyError, TypeError):
                    pass
            await asyncio.sleep(5)

    async def close(self):
        for task in self.tasks.values():
            if not task.done():
                task.cancel()
        for task in self.tasks.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
