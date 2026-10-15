"""Backfill first-party prerequisites on user-installed releases, including old workers."""

import asyncio
import json
import os
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from mediahub.errors import DomainError
from mediahub.managed_apps import Installation


class AppDependencies:
    def __init__(self, svc):
        self.svc = svc
        self.task = None
        self.message = None

    async def run(self):
        async with self.svc.managed_apps.lock:
            await self._run()
        monitor = getattr(self.svc, "updates", None)
        if monitor:
            # Refresh local version labels even when GitHub has imposed a
            # cooldown. Preparation can outlive the initial release check.
            await monitor.refresh_managed_versions("failed" if self.message else "ready")

    async def _run(self, update=None):
        config, manager = self.svc.config, self.svc.managed_apps
        if not config.managed_apps_docker_socket or not config.managed_apps_policy_file:
            return
        try:
            own = await manager.docker(
                "GET", "/containers/" + os.environ.get("HOSTNAME", "") + "/json"
            )
            labels = own.get("Config", {}).get("Labels", {})
            if (
                labels.get("com.docker.compose.project") != "mediahub-platform"
                or labels.get("com.docker.compose.service") != "core"
            ):
                raise ValueError()
            mounts = [
                m for m in own["Mounts"] if m["Destination"] == "/data" and m["Type"] == "bind"
            ]
            if len(mounts) != 1:
                raise ValueError()
            root = PurePosixPath(mounts[0]["Source"]).parent
            if not root.is_absolute() or root == PurePosixPath("/") or ".." in root.parts:
                raise ValueError()
            # Only inherit storage already explicitly mounted into this owned Core.
            # Never turn HTTP input into a host bind, nor create missing host paths.
            storage_binds = []
            storage_policy = Path("/state/container-apps.json")
            if storage_policy.is_file():
                approved = json.loads(storage_policy.read_text())
                paths = set(approved.get("requiredMounts", {})) | set(
                    approved.get("requiredFilesystemUuids", {})
                )
                if approved.get("hostMountSnapshot") != "/host-evidence/snapshot.json":
                    raise ValueError()
                paths.add("/host-evidence")
                for path in sorted(paths):
                    candidate = PurePosixPath(path)
                    if (
                        not candidate.is_absolute()
                        or len(candidate.parts) < 3
                        or ".." in candidate.parts
                    ):
                        if path != "/host-evidence":
                            raise ValueError()
                    matching = [
                        m
                        for m in own["Mounts"]
                        if m["Type"] == "bind" and m["Source"] == path and m["Destination"] == path
                    ]
                    if len(matching) != 1:
                        raise ValueError()
                    storage_binds.append(path + ":" + path + ":ro")
            name = "mediahub-app-dependencies"
            previous = await manager.docker("GET", "/containers/" + name + "/json", missing=True)
            if previous:
                if (
                    previous.get("Config", {}).get("Labels", {}).get("org.mediahub.dependencies")
                    != "first-party"
                ):
                    raise ValueError()
                if previous["State"].get("Running"):
                    for _ in range(1800):
                        previous = await manager.docker("GET", "/containers/" + name + "/json")
                        if not previous["State"].get("Running"):
                            break
                        await asyncio.sleep(1)
                    else:
                        raise ValueError()
                await manager.docker("DELETE", "/containers/" + name + "?v=false")
            await manager.docker(
                "POST",
                "/containers/create?name=" + name,
                body={
                    "Image": own["Image"],
                    "User": "0:0",
                    "Env": ["DOCKER_CONFIG=/tmp/docker-config"],
                    "Entrypoint": ["python"],
                    "Cmd": ["/app/scripts/prepare_local_apps.py", "--root", str(root)]
                    + self.lan_argument()
                    + (
                        [
                            "--app",
                            update["kind"],
                            "--app-source",
                            str(root / "data" / update["source"]),
                            "--app-commit",
                            update["commit"],
                            "--app-repository",
                            update["repository"],
                        ]
                        if update
                        else []
                    ),
                    "Labels": {
                        "org.mediahub.dependencies": "first-party",
                        **({"org.mediahub.app-update": update["operationId"]} if update else {}),
                    },
                    "Healthcheck": {"Test": ["NONE"]},
                    "HostConfig": {
                        "Binds": [
                            str(root) + ":" + str(root),
                            "/var/run/docker.sock:/var/run/docker.sock",
                        ]
                        + storage_binds,
                        "NetworkMode": "bridge",
                        "Privileged": False,
                        "CapDrop": ["ALL"],
                        "CapAdd": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
                        # LXC bind files can have an unmapped owner. DAC_OVERRIDE
                        # cannot bypass that boundary; inherit Core's approved
                        # groups to read the host evidence (gid 10001).
                        "GroupAdd": own.get("HostConfig", {}).get("GroupAdd", []),
                        "ReadonlyRootfs": True,
                        "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=64m"},
                        "SecurityOpt": ["no-new-privileges:true"],
                        "LogConfig": {"Type": "none", "Config": {}},
                    },
                },
            )
            await manager.docker("POST", "/containers/" + name + "/start")
            for _ in range(1800):
                row = await manager.docker("GET", "/containers/" + name + "/json")
                if not row["State"].get("Running"):
                    if row["State"].get("ExitCode") != 0:
                        raise ValueError()
                    policy = json.loads(config.managed_apps_policy_file.read_text())
                    manager.policy = {
                        key: Installation.model_validate(value) for key, value in policy.items()
                    }
                    self.message = None
                    return
                await asyncio.sleep(1)
            raise ValueError()
        except (DomainError, OSError, ValueError, KeyError, TypeError):
            self.message = "Automatic app preparation failed; existing data was retained"

    def start(self):
        self.message = None
        self.task = asyncio.create_task(self.run())

    def public(self):
        return {
            "state": "preparing"
            if self.task and not self.task.done()
            else "failed"
            if self.message
            else "ready",
            "message": self.message,
        }

    def lan_argument(self):
        try:
            host = str(ip_address(urlsplit(self.svc.config.base_url).hostname or ""))
            return ["--lan-ip", host]
        except ValueError:
            # Public hostnames remain optional. The host helper can obtain the
            # private address from its approved local app installation policy.
            return []

    def require_ready(self):
        if self.task and not self.task.done():
            raise DomainError(
                "dependencies_preparing",
                "Preparing app prerequisites; refresh to follow progress",
                409,
            )
        if self.message:
            raise DomainError("dependencies_failed", self.message, 409)
