"""Observe and control only an explicitly linked, operator-installed GPU sidecar."""

import asyncio
import ipaddress
import re
import time

import httpx
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json

PACKAGE = "org.mediahub.plex-gpu-transcoder"
NAME = "mediahub-plex-gpu-transcoder"


class PlexGPU:
    def __init__(self, runtime):
        self.runtime = runtime
        self.path = runtime.state_dir / "plex-gpu-transcoder.json"
        self.lock = asyncio.Lock()

    def registration(self):
        if not self.path.exists():
            return None
        record = read_json(self.path)
        if not record.get("enabled"):
            return None
        if (record.get("container") != NAME
                or not re.fullmatch(r"sha256:[a-f0-9]{64}", record.get("imageId", ""))):
            raise DomainError("plex_gpu_policy_invalid", "Plex GPU registration is invalid", 409)
        return record

    async def owned(self, record):
        policy = self.runtime.control.policy()
        await self.runtime.control.inspect(policy)
        row = await self.runtime.request("GET", f"/containers/{NAME}/json")
        labels = row.get("Config", {}).get("Labels", {})
        host = row.get("HostConfig", {})
        install = self.runtime.policy()
        if (row.get("Image") != record["imageId"]
                or labels.get("org.mediahub.package") != PACKAGE
                or labels.get("org.mediahub.plex.installation") != policy.installationId
                or record.get("plexInstallationId") != policy.installationId
                or not host.get("ReadonlyRootfs") or host.get("Privileged")
                or row.get("Config", {}).get("User") != f"{install.uid}:{install.gid}"):
            raise DomainError("plex_gpu_ownership", "Plex GPU runtime ownership changed", 409)
        current = await self.runtime.control.inspect(policy)
        media = {(m["Source"], m["Destination"]) for m in current["Mounts"]
                 if m["Destination"].startswith("/media/")}
        granted = {(m["Source"], m["Destination"]) for m in row["Mounts"]
                   if m["Destination"].startswith("/media/") and not m["RW"]}
        if media != granted or any(
            m["Destination"].startswith("/media/") and m["RW"] for m in row["Mounts"]
        ) or any(m["Destination"] == "/var/run/docker.sock" for m in row["Mounts"]):
            raise DomainError("plex_gpu_mounts", "Plex GPU media mappings require reconciliation", 409)
        bindings = host.get("PortBindings", {}).get("8090/tcp", [])
        if (len(bindings) != 1 or bindings[0].get("HostIp") != install.bindAddress
                or not str(bindings[0].get("HostPort", "")).isdigit()):
            raise DomainError("plex_gpu_port", "Plex GPU requires its registered private LAN port", 409)
        address = ipaddress.ip_address(install.bindAddress)
        if not address.is_private or address.is_unspecified or address.is_loopback:
            raise DomainError("plex_gpu_port", "Plex GPU requires a private LAN address", 409)
        port = int(bindings[0]["HostPort"])
        if not 1024 <= port <= 65535:
            raise DomainError("plex_gpu_port", "Plex GPU requires a non-privileged LAN port", 409)
        host_ip = f"[{address}]" if address.version == 6 else str(address)
        url = f"http://{host_ip}:{port}"
        return row, url

    async def status(self):
        record = self.registration()
        if record is None:
            return {"installed": False}
        policy = self.runtime.control.policy()
        row, url = await self.owned(record)
        state = row["State"]
        running = state.get("Running") is True and not state.get("Restarting")
        observed = {}
        if running:
            try:
                async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
                    response = await client.get(url + "/api/status")
                if response.status_code == 200 and len(response.content) <= 131072:
                    observed = response.json()
            except (httpx.HTTPError, ValueError):
                pass
        if not isinstance(observed, dict):
            observed = {}
        gpu = observed.get("gpu") or {}
        if not isinstance(gpu, dict):
            gpu = {}
        active = None
        try:
            if "active" not in observed:
                raise ValueError()
            active = min(32, max(0, int(observed.get("active", 0))))
        except (TypeError, ValueError, OverflowError):
            pass

        def number(key, maximum):
            try:
                value = float(gpu.get(key))
                return value if 0 <= value <= maximum else None
            except (TypeError, ValueError):
                return None

        linked = observed.get("adapterInstalled") is True
        healthy = running and bool(gpu) and linked
        checks = [
            {"name": "Container", "status": "healthy" if running else "unknown",
             "message": "Running" if running else "Stopped"},
            {"name": "NVIDIA GPU", "status": "healthy" if gpu else "degraded",
             "message": "GPU observed" if gpu else "GPU status unavailable"},
            {"name": "Plex connection", "status": "healthy" if linked else "degraded",
             "message": "Connected" if linked else "Waiting for Plex connection"},
        ]
        return {
            "installed": True, "installationId": record["installationId"],
            "hostId": policy.hostId, "observedAt": time.time(), "agentOnline": True,
            "dockerHealthy": state.get("Health", {}).get("Status") == "healthy",
            "state": "running" if running else "stopped", "startedAt": state.get("StartedAt") if running else None,
            "health": "healthy" if healthy else "degraded" if running else "unknown",
            "healthVerified": bool(observed), "version": record.get("version", "unknown"),
            "url": url, "checks": checks,
            "gpu": {
                "name": str(gpu.get("name", ""))[:120], "linked": linked,
                "encoderPercent": number("encoder", 100),
                "memoryUsedMiB": number("memoryUsed", 1048576),
                "memoryTotalMiB": number("memoryTotal", 1048576),
                "temperature": number("temperature", 150),
                "activeJobs": active,
            },
        }

    async def action(self, action):
        if action not in {"start", "stop", "restart"}:
            raise DomainError("unsupported_action", "Unsupported Plex GPU action", 400)
        async with self.lock:
            record = self.registration()
            if record is None:
                raise DomainError("plex_gpu_not_installed", "Install and link Plex GPU first", 409)
            row, _ = await self.owned(record)
            if action != "stop" and not await self.runtime.control.storage_verified(self.runtime.control.policy()):
                raise DomainError("storage_unavailable", "Plex storage is unavailable", 409)
            endpoint = "stop?t=10" if action == "stop" else "restart?t=10" if action == "restart" else "start"
            running = row["State"].get("Running")
            if action == "restart" or action == "start" and not running or action == "stop" and running:
                await self.runtime.request("POST", f"/containers/{NAME}/{endpoint}")
            record["desiredRunning"] = action != "stop"
            save_json(self.path, record)
            return {"state": "accepted", "action": action}

    async def logs(self):
        report = await self.status()
        return {"entries": [{"timestamp": time.time(), "hostId": report.get("hostId", "local"),
                "app": PACKAGE, "severity": "info", "type": "plex_gpu.status",
                "message": "GPU container " + report.get("state", "not installed")}]}
