"""Production transaction adapter over the verified, installation-scoped runtime driver."""

import base64
import hashlib
import json
import socket
import uuid
from pathlib import Path

import httpx
from mediahub.apps.seedbox_credentials import VPNProfileRegistry
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.port_forwarding import PortForwarding
from agent.ram_secrets import RuntimeSecrets, verify_ram_directory
from agent.seedbox_driver import ScopedDriver
from agent.seedbox_provision import client_config_archive, provision_initial


class BoundInstallRuntime(ScopedDriver):
    def __init__(self, installer, socket_path, devices, spec):
        super().__init__(installer, socket_path, devices)
        self.spec = spec
        self.forwarding = PortForwarding(self)

    def binding(self):
        policy = self.installer.policy()
        if (
            self.spec.hostId != policy.hostId
            or self.spec.downloadsStorageId != policy.downloadsStorageId
        ):
            raise ValueError("Installation not delegated to this host/storage")
        return policy, self.spec


class ProductionInstallDriver:
    def __init__(self, runtime, settings, credentials, on_healthy):
        self.runtime, self.settings = runtime, settings
        self.credentials, self.on_healthy = credentials, on_healthy
        self.vpn_ip = None
        policy, _ = runtime.binding()
        self.journal = Path(policy.workRoot) / "install-ownership.json"
        self.transaction_id = None

    def review(self):
        policy, spec = self.runtime.binding()
        plan = self.runtime.installer.plan(spec)
        # Bind approval to immutable desired data, not transient mount observations.
        material = {
            "installation": spec.model_dump(),
            "policy": policy.model_dump(),
            "qBittorrent": self.settings.model_dump(),
        }
        plan["digest"] = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        plan["qBittorrent"] = self.settings.model_dump()
        plan["executionStage"] = "transactional-install"
        return plan

    async def preflight(self, digest, *, adoption=False):
        policy, spec = self.runtime.binding()
        if digest != self.review()["digest"]:
            raise DomainError("plan_changed", "Review the current installation plan", 409)
        if spec.provider != "protonvpn" or spec.protocol != "wireguard":
            raise DomainError(
                "unsupported_provider",
                "No approved install adapter for this provider/protocol",
                422,
            )
        credential = self.credentials()
        VPNProfileRegistry().get(spec.protocol).validate(credential.vpnConfig)
        verify_ram_directory(Path(policy.workRoot) / "secrets")
        await self.runtime.storage_guard()
        await self.runtime.device_guard()
        await self.runtime.write_probe(minimum_free_bytes=512 * 1024**2)
        # Docker storage probe runs in the actual host namespace, not a guessed Core path.
        info = (await self.runtime.request("GET", "/info")).json()
        if info.get("MemTotal", 0) < (spec.vpnMemoryMiB + spec.torrentMemoryMiB + 256) * 1024**2:
            raise DomainError(
                "insufficient_memory", "Host memory is below the reviewed runtime budget", 409
            )
        for image in (policy.paths.vpnImage, policy.paths.torrentImage):
            await self.runtime.request("GET", "/images/" + image + "/json")
        for service in ("vpn", "torrent"):
            try:
                await self.runtime.container(service)
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise
                if adoption:
                    raise DomainError(
                        "adoption_incomplete", "Both reviewed containers must exist", 409
                    ) from None
            else:
                if not adoption:
                    raise DomainError(
                        "runtime_conflict", "Existing runtime must be adopted, not overwritten", 409
                    )
        if not adoption:
            # No publishing: reserve/release only to test that loopback is unused.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", spec.webPort))
        return {"state": "passed", "digest": digest}

    async def execute(self, step):
        policy, spec = self.runtime.binding()
        root = Path(policy.workRoot)
        if step == "persist_plan":
            if self.journal.exists():
                previous = read_json(self.journal)
                if previous.get("status") not in {"rolled_back", "removed"}:
                    raise ValueError("Previous transaction requires reconciliation")
            self.transaction_id = uuid.uuid4().hex
            save_json(
                self.journal,
                {
                    "transactionId": self.transaction_id,
                    "installationId": spec.installationId,
                    "status": "installing",
                },
            )
            target = root / "installation.json"
            if target.exists():
                if read_json(target).get("installation") != spec.model_dump():
                    raise ValueError("Existing installation binding differs")
            else:
                save_json(
                    target,
                    {
                        "installation": spec.model_dump(),
                        "review": self.review(),
                        "state": "prepared",
                    },
                )
        elif step == "prepare_directories":
            await self.runtime.storage_guard()
            # Provisioning creates app-private directories only; never the NFS mountpoint.
        elif step == "store_secrets":
            provision_initial(policy, spec, self.settings, self.credentials())
        elif step in {"create_vpn", "create_qbittorrent"}:
            service = "vpn" if step == "create_vpn" else "torrent"
            await self.runtime.ensure_runtime((service,), self.transaction_id)
            if service == "torrent":
                item = await self.runtime.container("torrent")
                if item["State"]["Running"]:
                    raise ValueError("Client must remain stopped during provisioning")
                exists = False
                for path in ("/config/qBittorrent", "/config/qBittorrent/qBittorrent.conf"):
                    try:
                        response = await self.runtime.request(
                            "HEAD", "/containers/" + item["Id"] + "/archive", params={"path": path}
                        )
                    except httpx.HTTPStatusError as error:
                        if error.response.status_code != 404:
                            raise
                    else:
                        metadata = json.loads(
                            base64.b64decode(response.headers["X-Docker-Container-Path-Stat"])
                        )
                        if metadata.get("linkTarget"):
                            raise ValueError("Symlinked client configuration is unsafe")
                        if path.endswith(".conf"):
                            if metadata["mode"] & ~0o777:
                                raise ValueError("Client configuration is not a regular file")
                            exists = True
                        elif not metadata["mode"] & (1 << 31):
                            raise ValueError("Client configuration parent is not a directory")
                if not exists:
                    archive = client_config_archive(spec, self.settings, self.credentials())
                    await self.runtime.request(
                        "PUT",
                        "/containers/" + item["Id"] + "/archive",
                        params={"path": "/config", "noOverwriteDirNonDir": "true"},
                        headers={"Content-Type": "application/x-tar"},
                        content=archive,
                    )
        elif step == "start_vpn":
            await self.runtime.start_vpn()
        elif step == "verify_vpn":
            self.vpn_ip = await self.runtime.verify_vpn()
        elif step == "verify_external_ip":
            if await self.runtime.verified_ip(await self.runtime.container("vpn")) != self.vpn_ip:
                raise ValueError("VPN identity changed during installation")
        elif step == "establish_forwarded_port":
            result = await self.runtime.forwarding.renew(apply=False)
            if result["status"] != "pending_client":
                raise ValueError("Forwarded torrent port not verified")
        elif step == "verify_namespace":
            vpn, torrent = (
                await self.runtime.container("vpn"),
                await self.runtime.container("torrent"),
            )
            if torrent["HostConfig"]["NetworkMode"] != "container:" + vpn["Id"]:
                raise ValueError("Torrent namespace differs from verified VPN")
        elif step == "verify_storage":
            await self.runtime.storage_guard()
            await self.runtime.write_probe()
        elif step == "start_qbittorrent":
            await self.runtime.start_torrent()
        elif step in {"verify_api", "verify_egress"}:
            await self.runtime.verify_torrent(self.vpn_ip)
        elif step == "verify_listen_port":
            result = await self.runtime.forwarding.apply_current()
            if result["status"] != "healthy":
                raise ValueError("Forwarded port not verified in qBittorrent")
        elif step == "mark_installed":
            await self.runtime.storage_guard()
            await self.runtime.verify_torrent(self.vpn_ip)
            await self.on_healthy()
            save_json(
                self.journal,
                {
                    "transactionId": self.transaction_id,
                    "installationId": spec.installationId,
                    "status": "healthy",
                },
            )
        else:
            raise ValueError("Unknown production install step")

    async def rollback_owned_runtime(self):
        if not self.journal.exists():
            return  # Failure before the ownership claim cannot authorize removal.
        record = read_json(self.journal)
        _, spec = self.runtime.binding()
        transaction = record.get("transactionId")
        if (
            record.get("installationId") != spec.installationId
            or not transaction
            or transaction != self.transaction_id
        ):
            raise ValueError("Ownership journal mismatch")
        for service in ("torrent", "vpn"):
            try:
                item = await self.runtime.container(service)
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 404:
                    continue
                raise
            if item["Config"]["Labels"].get("mediahub.install.transaction") != transaction:
                raise ValueError("Refusing to remove a runtime not created by this transaction")
            if item["State"]["Running"]:
                await self.runtime.request(
                    "POST", "/containers/" + item["Id"] + "/stop", params={"t": 5}
                )
            await self.runtime.request(
                "DELETE", "/containers/" + item["Id"], params={"force": "false", "v": "false"}
            )
        RuntimeSecrets(Path(self.runtime.binding()[0].workRoot)).clear()
        save_json(self.journal, {**record, "status": "rolled_back"})

    async def adopt(self):
        await self.preflight(self.review()["digest"], adoption=True)
        ip = await self.runtime.verify_vpn()
        await self.runtime.verify_torrent(ip)
        result = await self.runtime.forwarding.renew()
        if result["status"] != "healthy":
            raise ValueError("Existing runtime forwarding is not verified")
        await self.runtime.storage_guard()
        await self.on_healthy()
        return {"state": "Healthy", "adopted": True, "containersRecreated": False}
