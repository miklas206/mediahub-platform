"""Scoped live diagnostics; never starts/stops containers or returns runtime secrets."""

import asyncio
import ipaddress
import json
import time
import uuid
from pathlib import Path

import httpx
from mediahub.apps.seedbox import SeedboxInstallation

from agent.seedbox_install import policy_host_mounts_verified, policy_mounts_verified


def overall_health(checks):
    if any(c["status"] == "critical" for c in checks):
        return "critical"
    if any(c["status"] != "healthy" for c in checks):
        return "degraded"
    return "healthy"


class SeedboxStatus:
    def __init__(self, installer, socket):
        self.installer, self.socket = installer, socket
        self.lock = asyncio.Lock()
        self.cached = None
        self.mount_probe = None

    async def report(self, devices):
        async with self.lock:
            if self.cached and time.time() - self.cached["observedAt"] < 10:
                return self.cached
            report = await self._collect(devices)
            self.cached = report
            return report

    async def _collect(self, devices):
        policy = self.installer.policy()
        saved = json.loads((Path(policy.workRoot) / "installation.json").read_text())
        spec = SeedboxInstallation.model_validate(saved["installation"])
        mounted = policy_host_mounts_verified(policy)
        # Check the host first: don't touch retained/stale container NFS binds.
        if mounted:
            if self.mount_probe is None or self.mount_probe.done():
                self.mount_probe = asyncio.create_task(
                    asyncio.to_thread(policy_mounts_verified, policy)
                )
            try:
                mounted = await asyncio.wait_for(asyncio.shield(self.mount_probe), 5)
            except (TimeoutError, OSError, ValueError):
                mounted = False
        report = {
            "observedAt": time.time(),
            "installationId": spec.installationId,
            "hostId": spec.hostId,
            "agentOnline": True,
            "dockerHealthy": False,
            "vpn": {
                "verified": False,
                "externalIp": None,
                "provider": spec.provider,
                "protocol": spec.protocol,
                "connectedSince": None,
                "lastVerified": None,
            },
            "qBittorrent": {
                "healthy": False,
                "version": None,
                "running": False,
                "apiAuthenticated": False,
                "bindingVerified": False,
                "namespaceVerified": False,
            },
            "storage": {
                "mounted": mounted,
                "appWritable": None,
                "logicalId": spec.downloadsStorageId,
                "source": policy.nfsSource,
                "filesystem": "nfs4" if mounted else None,
                "verifiedAt": None,
                "totalBytes": None,
                "usedBytes": None,
                "freeBytes": None,
            },
            "devices": devices,
            "checks": [],
            "deviceChecks": devices["checks"],
            "deviceInventory": devices["sources"]["block"]["devices"],
            "host": {},
        }
        try:
            snapshot = json.loads(Path(policy.hostMountSnapshot).read_text())
            if 0 <= time.time() - snapshot["observedAt"] <= 30:
                report["host"] = snapshot.get("host", {})
                report["storage"]["verifiedAt"] = snapshot["observedAt"]
        except (OSError, ValueError, TypeError, KeyError):
            pass

        def check(name, status):
            report["checks"].append({"name": name, "status": status})

        try:
            if not self.socket:
                raise ValueError("No Docker access")
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.socket)),
                base_url="http://docker",
                timeout=12,
                trust_env=False,
            ) as docker:
                (await docker.get("/version")).raise_for_status()
                report["dockerHealthy"] = True

                async def inspect(service):
                    r = await docker.get(
                        "/containers/mediahub-" + spec.installationId + "-" + service + "-1/json"
                    )
                    r.raise_for_status()
                    data = r.json()
                    labels = data["Config"].get("Labels", {})
                    if (
                        labels.get("com.docker.compose.project")
                        != "mediahub-" + spec.installationId
                        or labels.get("com.docker.compose.service") != service
                    ):
                        raise ValueError("Container ownership mismatch")
                    return data

                async def execute(container, command, user="0"):
                    r = await docker.post(
                        "/containers/" + container["Id"] + "/exec",
                        json={
                            "AttachStdout": True,
                            "AttachStderr": False,
                            "Tty": True,
                            "User": user,
                            "Cmd": command,
                        },
                    )
                    r.raise_for_status()
                    identifier = r.json()["Id"]
                    r = await docker.post(
                        "/exec/" + identifier + "/start", json={"Detach": False, "Tty": True}
                    )
                    r.raise_for_status()
                    status = await docker.get("/exec/" + identifier + "/json")
                    status.raise_for_status()
                    if status.json().get("ExitCode") != 0 or len(r.content) > 16384:
                        raise ValueError("Diagnostic failed")
                    return r.text.strip()

                vpn = await inspect("vpn")
                if vpn["State"]["Running"]:
                    route = await execute(vpn, ["ip", "route", "get", "1.1.1.1"])
                    if "dev tun0" in route:
                        external = await execute(
                            vpn, ["wget", "-q", "-T", "8", "-O", "-", "https://api.ipify.org"]
                        )
                        if ipaddress.ip_address(external).is_global:
                            report["vpn"].update(
                                verified=True,
                                externalIp=external,
                                connectedSince=vpn["State"]["StartedAt"],
                                lastVerified=time.time(),
                            )
                torrent = await inspect("torrent")
                report["qBittorrent"]["running"] = torrent["State"]["Running"]
                namespace_ok = torrent["HostConfig"]["NetworkMode"] == "container:" + vpn["Id"]
                if torrent["State"]["Running"] and namespace_ok:
                    namespace_ok = await execute(
                        vpn, ["readlink", "/proc/self/ns/net"]
                    ) == await execute(torrent, ["readlink", "/proc/self/ns/net"])
                    if not namespace_ok:
                        raise ValueError("Stale network namespace")
                    cred = json.loads(Path(policy.workRoot, "secrets/qbit.json").read_text())
                    base = "http://127.0.0.1:" + str(spec.webPort)
                    async with httpx.AsyncClient(
                        base_url=base, timeout=5, trust_env=False, headers={"Referer": base + "/"}
                    ) as qbit:
                        r = await qbit.post("/api/v2/auth/login", data=cred)
                        r.raise_for_status()
                        version = await qbit.get("/api/v2/app/version")
                        version.raise_for_status()
                        prefs = await qbit.get("/api/v2/app/preferences")
                        prefs.raise_for_status()
                        if prefs.json().get("current_network_interface") != "tun0":
                            raise ValueError("qBittorrent interface not bound")
                        transfer = await qbit.get("/api/v2/transfer/info")
                        transfer.raise_for_status()
                        torrents = await qbit.get("/api/v2/torrents/info")
                        torrents.raise_for_status()
                        rows = torrents.json()
                        report["qBittorrent"] = {
                            "healthy": True,
                            "running": True,
                            "apiAuthenticated": True,
                            "bindingVerified": True,
                            "namespaceVerified": True,
                            "version": version.text,
                            "downloadSpeed": transfer.json()["dl_info_speed"],
                            "uploadSpeed": transfer.json()["up_info_speed"],
                            "torrents": len(rows),
                            "downloading": sum(
                                r["state"] in ("downloading", "forcedDL", "metaDL") for r in rows
                            ),
                            "seeding": sum(
                                r["state"] in ("uploading", "stalledUP", "forcedUP") for r in rows
                            ),
                            "paused": sum(
                                r["state"].startswith(("paused", "stopped")) for r in rows
                            ),
                            "errors": sum(r["state"] in ("error", "missingFiles") for r in rows),
                        }
                    if mounted:
                        report["storage"]["appWritable"] = False
                        # Only a unique disposable probe in the authorized downloads mount.
                        probe = "/downloads/.mediahub-write-probe-" + uuid.uuid4().hex
                        await execute(
                            torrent,
                            [
                                "sh",
                                "-c",
                                "umask 077; set -eu; p=" + probe + "; set -C; "
                                'printf mediahub > "$p"; test "$(cat "$p")" = mediahub; rm -- "$p"',
                            ],
                            str(spec.uid) + ":" + str(spec.gid),
                        )
                        report["storage"]["appWritable"] = True
                        capacity = (
                            (await execute(torrent, ["df", "-Pk", "/downloads"]))
                            .splitlines()[-1]
                            .split()
                        )
                        report["storage"].update(
                            totalBytes=int(capacity[1]) * 1024,
                            usedBytes=int(capacity[2]) * 1024,
                            freeBytes=int(capacity[3]) * 1024,
                        )
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
            # Raw errors may contain Docker environment or API credentials: never return them.
            pass
        check("agent", "healthy")
        check("docker", "healthy" if report["dockerHealthy"] else "critical")
        check("storage-mounted", "healthy" if mounted else "critical")
        writable = report["storage"]["appWritable"]
        check(
            "storage-app-writable",
            "healthy" if writable is True else "critical" if writable is False else "unknown",
        )
        check("vpn-verified", "healthy" if report["vpn"]["verified"] else "critical")
        check("qbittorrent", "healthy" if report["qBittorrent"]["healthy"] else "degraded")
        check("required-devices", devices["health"])
        report["health"] = overall_health(report["checks"])
        return report
