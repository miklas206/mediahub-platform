"""Policy-scoped Plex lifecycle. Never accepts container names or paths from callers."""

import asyncio
import contextlib
import ipaddress
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field, field_validator

from agent.install_files import read_json, save_json


class PlexMount(StrictModel):
    source: str
    target: str
    readOnly: bool


class PlexPolicy(StrictModel):
    hostId: str = Field(min_length=1, max_length=80)
    container: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,80}$")
    imageId: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    installationId: str = Field(pattern=r"^[a-z][a-z0-9-]{2,40}$")
    apiUrl: str = "http://127.0.0.1:32400"
    preferencesPath: str
    mounts: list[PlexMount]
    storageMarkers: dict[str, str]
    hostMountSnapshot: str
    requiredMounts: dict[str, str]
    requiredFilesystemUuids: dict[str, str] = Field(default_factory=dict)
    controlStatePath: str | None = None
    apiNetwork: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}$")
    vpnEnabled: bool = False

    @field_validator("apiUrl")
    @classmethod
    def internal_api_only(cls, value):
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        if (
            parsed.scheme != "http"
            or parsed.port != 32400
            or not (address.is_private or address.is_loopback)
            or address.is_unspecified
            or address.is_multicast
            or address.is_link_local
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("Plex API must use a host-policy private IP on port 32400")
        return value.rstrip("/")


class PlexControl:
    def __init__(self, policy_file, socket):
        self.policy_file, self.socket = policy_file, socket
        self.lock = asyncio.Lock()
        self.events = []
        self.monitor_task = None
        self.storage_probe = None
        self.runtime = None

    async def storage_verified(self, policy):
        # A failed device may leave a kernel read blocked. Keep at most one worker.
        if self.storage_probe is None or self.storage_probe.done():
            self.storage_probe = asyncio.create_task(asyncio.to_thread(self.storage_ready, policy))
        try:
            return await asyncio.wait_for(asyncio.shield(self.storage_probe), 5)
        except (TimeoutError, OSError, ValueError):
            return False

    def intent(self, policy):
        if not policy.controlStatePath:
            return False
        state = read_json(Path(policy.controlStatePath))
        if not isinstance(state.get("desiredRunning"), bool):
            raise DomainError("plex_intent_invalid", "Plex lifecycle state is unavailable", 503)
        return state["desiredRunning"]

    def save_intent(self, policy, desired):
        if policy.controlStatePath:
            save_json(Path(policy.controlStatePath), {"desiredRunning": desired})

    async def monitor(self):
        while True:
            try:
                async with self.lock:
                    policy = self.policy()
                    desired = self.intent(policy)
                    data = await self.inspect(policy)
                    running = data["State"].get("Running") is True
                    mounted = await self.storage_verified(policy)
                    vpn_ready = True
                    if desired and mounted and self.runtime and policy.vpnEnabled:
                        vpn_ready = await self.runtime.vpn.reconcile(policy, running)
                    if running and (not mounted or not desired or not vpn_ready):
                        if self.runtime:
                            await self.runtime.stop(policy)
                        else:
                            await self.docker("POST", f"/containers/{policy.container}/stop?t=30")
                        reason = (
                            "storage_blocked"
                            if not mounted
                            else "vpn_blocked"
                            if not vpn_ready
                            else "stopped"
                        )
                        self.record(reason)
                    elif desired and mounted and vpn_ready and not running:
                        if self.runtime:
                            await self.runtime.start(policy)
                        else:
                            await self.docker("POST", f"/containers/{policy.container}/start")
                        self.record("recovered")
                    elif running and self.runtime:
                        await self.runtime.checkpoint(policy)
                        if mounted:
                            await self.runtime.ensure_libraries(policy)
            except (DomainError, OSError, ValueError, KeyError, TypeError):
                # Never act on an unowned runtime or print raw responses/configuration.
                pass
            await asyncio.sleep(5)

    async def close(self):
        if self.monitor_task:
            self.monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.monitor_task

    def record(self, action):
        self.events.append(
            {
                "timestamp": time.time(),
                "type": "plex." + action,
                "severity": "warning" if action == "storage_blocked" else "info",
                "message": "Plex " + action.replace("_", " "),
            }
        )
        self.events = self.events[-100:]

    def policy(self):
        try:
            if not self.policy_file:
                raise ValueError()
            return PlexPolicy.model_validate_json(Path(self.policy_file).read_text())
        except (OSError, ValueError):
            raise DomainError("plex_disabled", "Managed Plex policy is unavailable", 503) from None

    async def docker(self, method, path):
        if not self.socket:
            raise DomainError("runtime_unavailable", "Docker runtime is unavailable", 503)
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.socket)),
                base_url="http://docker",
                timeout=45,
                trust_env=False,
            ) as client:
                response = await client.request(method, path)
                response.raise_for_status()
                return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise DomainError("plex_runtime_failed", "Plex runtime request failed", 503) from None

    async def inspect(self, policy):
        data = await self.docker("GET", f"/containers/{policy.container}/json")
        labels = data.get("Config", {}).get("Labels", {})
        actual = sorted((m["Source"], m["Destination"], not m["RW"]) for m in data["Mounts"])
        expected = sorted((m.source, m.target, m.readOnly) for m in policy.mounts)
        if (
            data.get("Image") != policy.imageId
            or actual != expected
            or labels.get("org.mediahub.installation") != policy.installationId
            or labels.get("org.mediahub.package") != "org.mediahub.plex"
        ):
            raise DomainError(
                "plex_ownership_mismatch", "Plex runtime does not match host policy", 409
            )
        return data

    def storage_ready(self, policy):
        try:
            snapshot = json.loads(Path(policy.hostMountSnapshot).read_text())
            if (
                snapshot.get("scope") != "host-mount-namespace"
                or snapshot.get("available") is not True
                or not 0 <= time.time() - snapshot["observedAt"] <= 30
                or not (policy.requiredMounts or policy.requiredFilesystemUuids)
            ):
                return False
            for path, source in policy.requiredMounts.items():
                rows = [r for r in snapshot["mounts"] if r.get("path") == path]
                if len(rows) != 1 or rows[0].get("source") != source:
                    return False
            for path, uuid in policy.requiredFilesystemUuids.items():
                rows = [r for r in snapshot["mounts"] if r.get("path") == path]
                if len(rows) != 1 or rows[0].get("uuid") != uuid:
                    return False
                if os.name == "posix" and rows[0].get("deviceNumber"):
                    device = os.stat(path).st_dev
                    if rows[0]["deviceNumber"] != f"{os.major(device)}:{os.minor(device)}":
                        return False
            return bool(policy.storageMarkers) and all(
                Path(path).read_text().strip() == value
                for path, value in policy.storageMarkers.items()
            )
        except (OSError, ValueError, TypeError, KeyError):
            return False

    async def plex_connection(self, policy):
        """Resolve only the owned private runtime and keep its token Agent-side."""
        try:
            api_url = policy.apiUrl
            if policy.apiNetwork:
                inspected = (
                    await self.runtime.vpn._container()
                    if policy.vpnEnabled and self.runtime
                    else await self.inspect(policy)
                )
                address = inspected["NetworkSettings"]["Networks"][policy.apiNetwork]["IPAddress"]
                api_url = PlexPolicy.internal_api_only(f"http://{address}:32400")
            if self.runtime:
                token = ET.fromstring(await self.runtime.preferences(policy)).get("PlexOnlineToken")
            else:
                token = ET.parse(policy.preferencesPath).getroot().get("PlexOnlineToken")
            return api_url, token
        except (OSError, ValueError, KeyError, ET.ParseError):
            raise DomainError("plex_api_unavailable", "Plex API is unavailable", 503) from None

    async def plex_get(self, policy, endpoint, method="GET", params=None):
        try:
            api_url, token = await self.plex_connection(policy)
            if not token and endpoint != "/identity":
                raise ValueError()
            # Plex may spend roughly ten seconds publishing a changed manual
            # remote-access port to plex.tv.  Read-only health requests remain
            # tightly bounded, while authenticated mutations get enough time
            # to finish instead of triggering the fail-closed recovery loop.
            async with httpx.AsyncClient(
                timeout=30 if method != "GET" else 8,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    method,
                    api_url + endpoint,
                    headers={"X-Plex-Token": token} if token else {},
                    params=params,
                ) as response:
                    response.raise_for_status()
                    limit = 2 * 1024 * 1024
                    if int(response.headers.get("content-length", "0")) > limit:
                        raise ValueError()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > limit:
                            raise ValueError()
                        content.extend(chunk)
                    return ET.fromstring(content) if content else ET.Element("Empty")
        except (OSError, ValueError, KeyError, ET.ParseError, httpx.HTTPError):
            raise DomainError("plex_api_unavailable", "Plex API is unavailable", 503) from None

    async def update_check(self):
        if self.runtime is not None:
            return await self.runtime.update_check()
        policy = self.policy()
        await self.inspect(policy)
        # Official PMS updater API: download=0 checks only; never apply an update.
        await self.plex_get(policy, "/updater/check?download=0", "PUT")
        status = await self.plex_get(policy, "/updater/status")
        return {
            "supported": False,
            "updateAvailable": False,
            "updateSource": "plex-server",
            "reason": "Plex server releases do not verify a managed container image update",
            "checkRequested": True,
            "downloadRequested": False,
            "installationRequested": False,
            "checkedAt": status.get("checkedAt"),
            "status": status.get("status"),
            "releaseVersions": [r.get("version", "")[:128] for r in status.findall("Release")],
            "message": "Plex update check requested. The pinned container image is unchanged.",
        }

    async def status(self):
        policy = self.policy()
        data = await self.inspect(policy)
        mounted = await self.storage_verified(policy)
        running = data["State"].get("Running") is True
        report = {
            "installationId": policy.installationId,
            "observedAt": time.time(),
            "hostId": policy.hostId,
            "health": "critical",
            "agentOnline": True,
            "dockerHealthy": True,
            "plex": {
                "running": running,
                "version": None,
                "startedAt": data["State"].get("StartedAt"),
                "libraries": [],
                "activeStreams": None,
                "memoryBytes": None,
                "cpuPercent": None,
            },
            "storage": {"mounted": mounted},
            "checks": [],
            "operation": self.runtime.operation if self.runtime else {"state": "idle"},
        }
        if self.runtime and policy.vpnEnabled:
            vpn_status = await self.runtime.vpn.status(policy)
            report["vpn"] = vpn_status["vpn"]
            report["portForwarding"] = vpn_status["portForwarding"]
            if not vpn_status["vpn"]["verified"]:
                report["health"] = "critical"
        if running and mounted:
            try:
                identity = await self.plex_get(policy, "/identity")
                libraries = await self.plex_get(policy, "/library/sections")
                sessions = await self.plex_get(policy, "/status/sessions")
                report["plex"].update(
                    {
                        "version": identity.get("version"),
                        "libraries": [
                            {"id": e.get("key"), "name": e.get("title"), "type": e.get("type")}
                            for e in libraries.findall("Directory")
                        ],
                        "activeStreams": int(sessions.get("size", "0")),
                    }
                )
                if not policy.vpnEnabled or report.get("vpn", {}).get("verified"):
                    report["health"] = "healthy"
                transcodes = sessions.findall(".//TranscodeSession")
                report["plex"]["transcodingStreams"] = sum(
                    s.get("videoDecision") == "transcode" or s.get("audioDecision") == "transcode"
                    for s in transcodes
                )
                report["plex"]["directStreams"] = max(
                    0, report["plex"]["activeStreams"] - report["plex"]["transcodingStreams"]
                )
                for library in report["plex"]["libraries"]:
                    if library["id"] and library["id"].isdigit():
                        with contextlib.suppress(DomainError, ValueError):
                            listing = await self.plex_get(
                                policy,
                                "/library/sections/" + library["id"] + "/all",
                                params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
                            )
                            library["count"] = int(
                                listing.get("totalSize", listing.get("size", "0"))
                            )
            except DomainError:
                pass
            try:
                stats = await self.docker(
                    "GET", f"/containers/{policy.container}/stats?stream=false"
                )
                report["plex"]["memoryBytes"] = stats.get("memory_stats", {}).get("usage")
                cpu, prev = stats["cpu_stats"], stats["precpu_stats"]
                delta = cpu["cpu_usage"]["total_usage"] - prev["cpu_usage"]["total_usage"]
                system = cpu["system_cpu_usage"] - prev["system_cpu_usage"]
                if system > 0:
                    report["plex"]["cpuPercent"] = max(
                        0, delta / system * cpu.get("online_cpus", 1) * 100
                    )
            except (DomainError, KeyError, TypeError):
                pass
        report["checks"] = [
            {"name": "storage", "status": "healthy" if mounted else "critical"},
            {"name": "plex", "status": report["health"]},
        ]
        if policy.vpnEnabled:
            report["checks"].append(
                {
                    "name": "plex-vpn",
                    "status": "healthy" if report.get("vpn", {}).get("verified") else "critical",
                }
            )
        return report

    async def action(self, action):
        if action not in {"start", "stop", "restart"}:
            raise DomainError("unsupported_action", "Unsupported Plex action", 400)
        async with self.lock:
            policy = self.policy()
            await self.inspect(policy)
            if action != "stop" and not await self.storage_verified(policy):
                raise DomainError(
                    "storage_unavailable", "Plex storage is unavailable; start blocked", 409
                )
            suffix = "?t=30" if action in {"stop", "restart"} else ""
            self.save_intent(policy, action != "stop")
            if self.runtime:
                data = await self.inspect(policy)
                if data["State"].get("Running") and action in {"stop", "restart"}:
                    await self.runtime.stop(policy)
                if action in {"start", "restart"} and (
                    action == "restart" or not data["State"].get("Running")
                ):
                    await self.runtime.start(policy)
            else:
                await self.docker("POST", f"/containers/{policy.container}/{action}{suffix}")
            self.record(action)
            return {"state": "accepted", "action": action}
