"""Reconcile one bounded LAN-only NAT rule without changing Plex authentication."""

import contextlib
import hashlib
import json
import time
import uuid
from pathlib import Path

from mediahub.errors import DomainError

from agent.install_files import read_json, save_json


async def configure(shared, spec, relay=None, *, enabled=True):
    identity = spec["Labels"]["org.mediahub.installation"]
    config = {"installationId": identity, "enabled": enabled}
    receipt = shared.directory / "plex-lan-nat.json"
    image = relay["Image"] if relay else await shared.build_image()
    if enabled:
        bindings = spec["HostConfig"].get("PortBindings", {}).get("32400/tcp", [])
        if len(bindings) != 1 or bindings[0].get("HostPort") != "32400":
            raise DomainError(
                "plex_lan_nat_unavailable",
                "Local Plex recognition requires one approved private listener on port 32400",
                409,
            )
        network = await shared.request("GET", "/networks/bridge")
        endpoint = relay["NetworkSettings"]["Networks"]["bridge"]
        if network.get("Driver") != "bridge":
            raise DomainError(
                "plex_lan_nat_unavailable",
                "Local Plex recognition requires the owned Docker bridge",
                409,
            )
        config.update(
            binding=bindings[0]["HostIp"],
            target=endpoint["IPAddress"],
            gateway=endpoint["Gateway"],
            bridge=network.get("Options", {}).get("com.docker.network.bridge.name", "docker0"),
        )
    digest = hashlib.sha256(json.dumps([config, image], sort_keys=True).encode()).hexdigest()
    previous = read_json(receipt) if receipt.exists() else {}
    if previous.get("digest") == digest and time.time() - previous.get("checkedAt", 0) < 60:
        return
    code = Path(__file__).with_name("plex_lan_nat_worker.py").read_text()
    helper = None
    try:
        helper = (
            await shared.request(
                "POST",
                "/containers/create?name=mediahub-plex-lan-" + uuid.uuid4().hex[:12],
                {
                    "Image": image,
                    "User": "0:0",
                    "Entrypoint": ["python3", "-c", code, json.dumps(config)],
                    "Labels": {
                        "org.mediahub.plex.role": "lan-classification",
                        "org.mediahub.installation": identity,
                    },
                    "HostConfig": {
                        "NetworkMode": "host",
                        "Privileged": False,
                        "ReadonlyRootfs": True,
                        "CapDrop": ["ALL"],
                        "CapAdd": ["NET_ADMIN"],
                        "SecurityOpt": ["no-new-privileges:true"],
                        "Memory": 64 * 1024**2,
                        "MemorySwap": 64 * 1024**2,
                        "PidsLimit": 16,
                        "Tmpfs": {"/run": "rw,noexec,nosuid,nodev,size=1m"},
                        "LogConfig": {"Type": "none", "Config": {}},
                        "RestartPolicy": {"Name": "no"},
                    },
                },
            )
        )["Id"]
        await shared.request("POST", "/containers/" + helper + "/start")
        result = await shared.request("POST", "/containers/" + helper + "/wait")
        if result.get("StatusCode") != 0:
            raise DomainError(
                "plex_lan_nat_unavailable",
                "Local Plex recognition could not be prepared. Check host LAN addressing and permission to manage the owned Docker NAT rule.",
                409,
            )
        save_json(receipt, {"digest": digest, "checkedAt": time.time(), "enabled": enabled})
    finally:
        if helper:
            with contextlib.suppress(DomainError):
                await shared.request("DELETE", "/containers/" + helper + "?v=false")


async def reconcile(runtime):
    shared = runtime.shared_vpn
    if not shared:
        return False
    receipt = shared.directory / "plex-lan-nat.json"
    enabled = shared.state("plex")["enabled"]
    if not enabled and not receipt.exists():
        return False
    plan = read_json(runtime.state_dir / "plex-plan.json")
    spec = shared.original_spec(shared.state("plex"), plan["container"])
    relay = await shared.owned_relay("plex") if enabled else None
    if enabled and (not relay or not relay["State"].get("Running")):
        raise DomainError(
            "plex_lan_nat_unavailable",
            "Wait for the owned Plex VPN relay before preparing local access",
            409,
        )
    await configure(shared, spec, relay, enabled=enabled)
    return enabled
