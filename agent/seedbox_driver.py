"""Installation-scoped Docker driver. Never accepts shell commands or paths from HTTP."""

import asyncio
import ipaddress
import json
import time
import uuid
from pathlib import Path

import httpx
from mediahub.apps.seedbox import SeedboxInstallation, compose_plan

from agent.forwarding_rules import owned_ports
from agent.port_forwarding import PortLeaseError
from agent.port_listener import ListeningPortError
from agent.ram_secrets import RuntimeSecrets
from agent.seedbox_install import policy_host_mounts_verified, policy_mounts_verified


class ScopedDriver:
    def __init__(self, installer, socket, devices):
        self.installer, self.socket, self.devices = installer, socket, devices
        self.mount_probe = None

    def binding(self):
        policy = self.installer.policy()
        saved = json.loads((Path(policy.workRoot) / "installation.json").read_text())
        spec = SeedboxInstallation.model_validate(saved["installation"])
        if spec.hostId != policy.hostId or spec.downloadsStorageId != policy.downloadsStorageId:
            raise ValueError("Installation ownership mismatch")
        return policy, spec

    async def request(self, method, path, **kwargs):
        if not self.socket:
            raise ValueError("Docker unavailable")
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(self.socket)),
            base_url="http://docker",
            trust_env=False,
            timeout=15,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

    async def container(self, service):
        if service not in {"vpn", "torrent"}:
            raise ValueError("Invalid component")
        policy, spec = self.binding()
        project = "mediahub-" + spec.installationId
        item = (await self.request("GET", f"/containers/{project}-{service}-1/json")).json()
        labels = item["Config"].get("Labels", {})
        if (
            labels.get("com.docker.compose.project") != project
            or labels.get("com.docker.compose.service") != service
        ):
            raise ValueError("Container ownership mismatch")
        image = policy.paths.vpnImage if service == "vpn" else policy.paths.torrentImage
        if item["Config"]["Image"] != image:
            raise ValueError("Unreviewed container image")
        if item["HostConfig"].get("RestartPolicy", {}).get("Name") not in {"no", ""}:
            raise ValueError("Docker restart policy bypasses startup gates")
        if item["HostConfig"].get("Privileged") or item["HostConfig"].get("PidMode") == "host":
            raise ValueError("Unexpected host privileges")
        expected = compose_plan(spec, policy.paths)["services"][service]["volumes"]
        expected_mounts = {(m["source"], m["target"], not m["read_only"]) for m in expected}
        actual_mounts = {(m["Source"], m["Destination"], m["RW"]) for m in item.get("Mounts", [])}
        if actual_mounts != expected_mounts or any(
            m["Type"] != "bind" for m in item.get("Mounts", [])
        ):
            raise ValueError("Runtime mount mapping differs from authorized storage")
        return item

    async def execute(self, item, command, *, max_output=16384):
        response = await self.request(
            "POST",
            "/containers/" + item["Id"] + "/exec",
            json={"AttachStdout": True, "AttachStderr": False, "Tty": True, "Cmd": command},
        )
        identifier = response.json()["Id"]
        result = await self.request(
            "POST", f"/exec/{identifier}/start", json={"Detach": False, "Tty": True}
        )
        status = (await self.request("GET", f"/exec/{identifier}/json")).json()
        if status.get("ExitCode") != 0 or len(result.content) > max_output:
            raise ValueError("Component verification failed")
        return result.text.strip()

    async def storage_guard(self):
        policy, _ = self.binding()
        if not policy_host_mounts_verified(policy):
            raise ValueError("Fresh host mount verification required")
        # Never touch an NFS bind if the host no longer reports the mount.
        if self.mount_probe is None or self.mount_probe.done():
            self.mount_probe = asyncio.create_task(
                asyncio.to_thread(policy_mounts_verified, policy)
            )
        # A hard NFS mount can leave one kernel I/O operation waiting. Never launch
        # another thread each retry while that operation remains blocked.
        verified = await asyncio.wait_for(asyncio.shield(self.mount_probe), 5)
        if not verified:
            raise ValueError("Storage source or marker mismatch")

    async def device_guard(self):
        if self.devices()["health"] != "healthy":
            raise ValueError("Required devices unavailable")

    async def write_probe(self, minimum_free_bytes=0):
        if type(minimum_free_bytes) is not int or not 0 <= minimum_free_bytes <= 1024**4:
            raise ValueError("Invalid free-space requirement")
        await self.storage_guard()
        policy, spec = self.binding()
        # Ephemeral, no network, no capabilities, only this installation's test mount.
        name = "mediahub-probe-" + uuid.uuid4().hex
        probe = "/downloads/." + name
        body = {
            "Image": policy.paths.torrentImage,
            "User": f"{spec.uid}:{spec.gid}",
            "Entrypoint": ["/bin/sh", "-c"],
            "Cmd": [
                "umask 077; set -eu; p="
                + probe
                + "; set -C; "
                + (
                    "test \"$(df -Pk /downloads | awk 'NR==2 {print $4}')\" -ge "
                    + str((minimum_free_bytes + 1023) // 1024)
                    + "; "
                    if minimum_free_bytes
                    else ""
                )
                + 'printf mediahub > "$p"; test "$(cat "$p")" = mediahub; rm -- "$p"'
            ],
            "Labels": {"mediahub.probe": spec.installationId},
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 64 * 1024 * 1024,
                "PidsLimit": 16,
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": policy.paths.downloads,
                        "Target": "/downloads",
                        "ReadOnly": False,
                    }
                ],
            },
        }
        response = await self.request(
            "POST", "/containers/create", params={"name": name}, json=body
        )
        identifier = response.json()["Id"]
        try:
            await self.request("POST", f"/containers/{identifier}/start")
            response = await self.request(
                "POST", f"/containers/{identifier}/wait", params={"condition": "not-running"}
            )
            if response.json().get("StatusCode") != 0:
                raise ValueError("App UID storage write probe failed")
        finally:
            # Only the just-created probe; never remove volumes or user data.
            await self.request(
                "DELETE", f"/containers/{identifier}", params={"force": "true", "v": "false"}
            )
        await self.storage_guard()

    async def stop_torrent(self):
        item = await self.container("torrent")
        if item["State"]["Running"]:
            await self.request("POST", "/containers/" + item["Id"] + "/stop", params={"t": 5})

    async def stop_vpn(self):
        item = await self.container("vpn")
        if item["State"]["Running"]:
            await self.request("POST", "/containers/" + item["Id"] + "/stop", params={"t": 5})
        policy, _ = self.binding()
        RuntimeSecrets(Path(policy.workRoot)).clear()

    async def port_forward_identity(self):
        _, spec = self.binding()
        if spec.provider != "protonvpn" or spec.protocol != "wireguard":
            raise ValueError("Port forwarding provider unsupported")
        vpn = await self.container("vpn")
        if not vpn["State"]["Running"]:
            raise ValueError("VPN stopped")
        address = await self.verified_ip(vpn)
        return (vpn["Id"], vpn["State"]["StartedAt"], address)

    async def request_forwarded_port(self):
        await self.port_forward_identity()
        policy, spec = self.binding()
        vpn = await self.container("vpn")
        name = "mediahub-pmp-" + uuid.uuid4().hex
        # Pinned existing Python image, VPN namespace only, no volumes/credentials.
        body = {
            "Image": policy.paths.torrentImage,
            "User": "0:0",
            "Tty": True,
            "Entrypoint": ["python3", "-c", Path(__file__).with_name("natpmp.py").read_text()],
            "Labels": {"mediahub.probe": spec.installationId},
            "HostConfig": {
                "NetworkMode": "container:" + vpn["Id"],
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "CapAdd": ["NET_RAW"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 64 * 1024 * 1024,
                "MemorySwap": 64 * 1024 * 1024,
                "PidsLimit": 16,
                "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
            },
        }
        identifier = (
            await self.request("POST", "/containers/create", params={"name": name}, json=body)
        ).json()["Id"]
        try:
            await self.request("POST", f"/containers/{identifier}/start")
            status = (await self.request("POST", f"/containers/{identifier}/wait")).json()
            output = (
                await self.request(
                    "GET",
                    f"/containers/{identifier}/logs",
                    params={"stdout": "true", "stderr": "false"},
                )
            ).content
            if len(output) > 1024:
                raise ValueError("Invalid allocation result")
            result = json.loads(output)
            if status.get("StatusCode") != 0:
                raise PortLeaseError(result.get("reason"))
            return result
        finally:
            await self.request(
                "DELETE", f"/containers/{identifier}", params={"force": "true", "v": "false"}
            )

    async def measure_vpn_speed(self):
        identity = await self.port_forward_identity()
        policy, _ = self.binding()
        vpn = await self.container("vpn")
        body = {
            "Image": policy.paths.torrentImage,
            "User": "0:0",
            "Tty": True,
            "Entrypoint": [
                "python3",
                "-c",
                Path(__file__).with_name("vpn_speed_probe.py").read_text(),
            ],
            "HostConfig": {
                "NetworkMode": "container:" + vpn["Id"],
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 64 * 1024**2,
                "PidsLimit": 16,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
            },
        }
        identifier = (await self.request("POST", "/containers/create", json=body)).json()["Id"]
        try:
            await self.request("POST", f"/containers/{identifier}/start")
            status = (
                await self.request("POST", f"/containers/{identifier}/wait", timeout=35)
            ).json()
            output = (
                await self.request(
                    "GET",
                    f"/containers/{identifier}/logs",
                    params={"stdout": "true", "stderr": "false"},
                )
            ).content
            if status.get("StatusCode") != 0 or len(output) > 1024:
                raise ValueError("Speed measurement unavailable")
            result = json.loads(output)
            if any(
                type(result.get(k)) not in (int, float) or not 0 < result[k] < 1e6
                for k in ("downloadMbps", "uploadMbps")
            ):
                raise ValueError("Invalid speed measurement")
            if await self.port_forward_identity() != identity:
                raise ValueError("VPN changed during measurement")
            return result
        finally:
            await self.request(
                "DELETE", f"/containers/{identifier}", params={"force": "true", "v": "false"}
            )

    async def allow_forwarded_port(self, port, previous):
        _, spec = self.binding()
        if (
            type(port) is not int
            or not 1024 <= port <= 65535
            or port in {spec.webPort, 18765, 18766, 18767}
        ):
            raise ValueError("Only a torrent port may be forwarded")
        vpn = await self.container("vpn")
        # Use an owned comment; never flush or replace Gluetun's firewall/kill switch.
        # Recover owned ports after Agent restart; process memory is not authoritative.
        prior = owned_ports(await self.execute(vpn, ["iptables", "-S", "INPUT"]))
        for protocol in ("tcp", "udp"):
            rule = [
                "INPUT",
                "-i",
                "tun0",
                "-p",
                protocol,
                "--dport",
                str(port),
                "-m",
                "comment",
                "--comment",
                "mediahub-torrent-pf",
                "-j",
                "ACCEPT",
            ]
            try:
                await self.execute(vpn, ["iptables", "-C", *rule])
            except ValueError:
                await self.execute(vpn, ["iptables", "-I", *rule])
            for old_protocol, old_port in prior:
                if old_protocol != protocol or old_port == port:
                    continue
                old = rule.copy()
                old[6] = str(old_port)
                try:
                    await self.execute(vpn, ["iptables", "-C", *old])
                except ValueError:
                    continue
                await self.execute(vpn, ["iptables", "-D", *old])

    async def apply_forwarded_port(self, port):
        vpn, torrent = await self.container("vpn"), await self.container("torrent")
        if torrent["HostConfig"]["NetworkMode"] != "container:" + vpn["Id"]:
            raise ValueError("Namespace mismatch")
        policy, spec = self.binding()
        cred = json.loads(Path(policy.workRoot, "secrets/qbit.json").read_text())
        base = f"http://127.0.0.1:{spec.webPort}"
        async with httpx.AsyncClient(
            base_url=base, trust_env=False, timeout=5, headers={"Referer": base + "/"}
        ) as client:
            response = await client.post("/api/v2/auth/login", data=cred)
            if response.status_code not in {200, 204} or (
                response.status_code == 200 and response.text.strip() != "Ok."
            ):
                raise ValueError("qBittorrent authentication failed")
            response = await client.get("/api/v2/app/preferences")
            response.raise_for_status()
            if response.json().get("current_network_interface") != "tun0":
                raise ValueError("VPN binding required")
            response = await client.post(
                "/api/v2/app/setPreferences",
                data={
                    "json": json.dumps({"listen_port": port, "upnp": False, "random_port": False})
                },
            )
            response.raise_for_status()
            response = await client.get("/api/v2/app/preferences")
            response.raise_for_status()
            settings = response.json()
            if settings.get("listen_port") != port or settings.get("upnp") is not False:
                raise ValueError("Forwarded port verification failed")
        # Preferences are not evidence of an actual listening socket. Allow a
        # bounded rebind window after qBittorrent changes its port.
        for attempt in range(8):
            try:
                await self.execute(
                    torrent,
                    [
                        "python3",
                        "-c",
                        Path(__file__).with_name("port_listener.py").read_text(),
                        str(port),
                    ],
                )
                return True
            except ValueError:
                if attempt == 7:
                    raise ListeningPortError("Torrent listening socket not found") from None
                await asyncio.sleep(0.25)

    async def remove_runtime(self):
        # Container identity and ownership checked immediately before each deletion.
        # No filesystem deletes, volume deletion, image pruning or force removal.
        for service in ("torrent", "vpn"):
            item = await self.container(service)
            if item["State"]["Running"]:
                raise ValueError("Runtime must be stopped before removal")
            await self.request(
                "DELETE", "/containers/" + item["Id"], params={"force": "false", "v": "false"}
            )

    async def ensure_runtime(self, services=("vpn", "torrent"), transaction_id=None):
        """Create absent runtime from the trusted planner, never caller-supplied Docker JSON.

        Persistent config/credential provisioning is a separate prerequisite. Existing
        containers are validated, not replaced, and no missing storage path is created.
        """
        if not services or any(service not in {"vpn", "torrent"} for service in services):
            raise ValueError("Invalid runtime components")
        await self.storage_guard()
        await self.device_guard()
        policy, spec = self.binding()
        RuntimeSecrets(Path(policy.workRoot)).materialize()
        if (
            not Path(policy.paths.vpnConfig).is_file()
            or not Path(policy.workRoot, "secrets/qbit.json").is_file()
        ):
            raise ValueError("Private credential files must be provisioned before installation")
        plan = compose_plan(spec, policy.paths)
        project = plan["name"]
        network = project + "_default"
        try:
            net = (await self.request("GET", "/networks/" + network)).json()
            if net.get("Labels", {}).get("com.docker.compose.project") != project:
                raise ValueError("Network ownership mismatch")
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            await self.request(
                "POST",
                "/networks/create",
                json={
                    "Name": network,
                    "Driver": "bridge",
                    "Labels": {"com.docker.compose.project": project},
                },
            )
        for service in services:
            try:
                await self.container(service)
                continue
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise
            row = plan["services"][service]
            host = {
                "RestartPolicy": {"Name": "no"},
                "SecurityOpt": row["security_opt"],
                "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                "MemorySwap": int(row["mem_limit"][:-1]) * 1024 * 1024,
                "Memory": int(row["mem_limit"][:-1]) * 1024 * 1024,
                "NanoCpus": int(row["cpus"] * 1_000_000_000),
                "LogConfig": {
                    "Type": row["logging"]["driver"],
                    "Config": row["logging"]["options"],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": m["source"],
                        "Target": m["target"],
                        "ReadOnly": m["read_only"],
                    }
                    for m in row["volumes"]
                ],
            }
            body = {
                "Image": row["image"],
                "Env": [k + "=" + v for k, v in row["environment"].items()],
                "Labels": {
                    "com.docker.compose.project": project,
                    "com.docker.compose.service": service,
                },
                "HostConfig": host,
            }
            if transaction_id:
                body["Labels"]["mediahub.install.transaction"] = transaction_id
            if service == "vpn":
                host.update(
                    NetworkMode=network,
                    CapAdd=["NET_ADMIN"],
                    Devices=[
                        {
                            "PathOnHost": "/dev/net/tun",
                            "PathInContainer": "/dev/net/tun",
                            "CgroupPermissions": "rwm",
                        }
                    ],
                    PortBindings={
                        f"{spec.webPort}/tcp": [
                            {"HostIp": "127.0.0.1", "HostPort": str(spec.webPort)}
                        ]
                    },
                )
                body["ExposedPorts"] = {f"{spec.webPort}/tcp": {}}
            else:
                host["NetworkMode"] = "container:" + (await self.container("vpn"))["Id"]
            await self.request(
                "POST", "/containers/create", params={"name": f"{project}-{service}-1"}, json=body
            )

    async def start_vpn(self, restart=False):
        item = await self.container("vpn")
        if restart and item["State"]["Running"]:
            await self.stop_vpn()
        if restart or not item["State"]["Running"]:
            policy, _ = self.binding()
            RuntimeSecrets(Path(policy.workRoot)).materialize()
            await self.request("POST", "/containers/" + item["Id"] + "/start")

    async def verified_ip(self, item):
        route = await self.execute(item, ["ip", "route", "get", "1.1.1.1"])
        if "dev tun0" not in route:
            raise ValueError("VPN route not established")
        address = await self.execute(
            item, ["wget", "-q", "-T", "8", "-O", "-", "https://api.ipify.org"]
        )
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Invalid external VPN address")
        return address

    async def verify_vpn(self):
        # Bounded readiness wait, never treat StartedAt or Docker health as tunnel proof.
        deadline = time.monotonic() + 45
        while True:
            try:
                item = await self.container("vpn")
                if not item["State"]["Running"]:
                    raise ValueError("VPN stopped")
                return await self.verified_ip(item)
            except (httpx.HTTPError, ValueError):
                if time.monotonic() >= deadline:
                    raise ValueError("VPN verification timed out") from None
                await asyncio.sleep(2)

    async def start_torrent(self):
        await self.storage_guard()
        vpn, torrent = await self.container("vpn"), await self.container("torrent")
        if torrent["HostConfig"]["NetworkMode"] != "container:" + vpn["Id"]:
            # Recreate is a separate reviewed operation; never guess a replacement config.
            raise ValueError("Container recreation required for changed VPN identity")
        await self.request("POST", "/containers/" + torrent["Id"] + "/start")

    async def verify_torrent(self, vpn_ip):
        vpn, torrent = await self.container("vpn"), await self.container("torrent")
        if torrent["HostConfig"]["NetworkMode"] != "container:" + vpn["Id"] or await self.execute(
            vpn, ["readlink", "/proc/self/ns/net"]
        ) != await self.execute(torrent, ["readlink", "/proc/self/ns/net"]):
            raise ValueError("qBittorrent namespace mismatch")
        policy, spec = self.binding()
        cred = json.loads(Path(policy.workRoot, "secrets/qbit.json").read_text())
        base = f"http://127.0.0.1:{spec.webPort}"
        deadline = time.monotonic() + 30
        while True:
            try:
                async with httpx.AsyncClient(
                    base_url=base, trust_env=False, timeout=5, headers={"Referer": base + "/"}
                ) as qbit:
                    (await qbit.post("/api/v2/auth/login", data=cred)).raise_for_status()
                    response = await qbit.get("/api/v2/app/preferences")
                    response.raise_for_status()
                    if response.json().get("current_network_interface") != "tun0":
                        raise ValueError("qBittorrent VPN binding invalid")
                break
            except httpx.HTTPError:
                if time.monotonic() >= deadline:
                    raise ValueError("qBittorrent API unavailable") from None
                await asyncio.sleep(2)
        if await self.verified_ip(torrent) != vpn_ip:
            raise ValueError("qBittorrent egress mismatch")
