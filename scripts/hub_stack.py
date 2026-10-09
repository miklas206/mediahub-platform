import copy
import ipaddress
from pathlib import Path


def hub_stack(compose: dict, root: Path) -> tuple[dict, dict]:
    if compose.get("name") != "mediahub-platform":
        raise ValueError("Only a MediaHub installation can be migrated")
    services = compose.get("services", {})
    if set(services) != {"core", "agent"}:
        raise ValueError("Expected an unmodified Core/Agent installation")
    result = copy.deepcopy(compose)
    hub = result["services"]["core"]
    runtime = result["services"].pop("agent")
    ports = hub.pop("ports")
    if not ports or len(ports) > 2:
        raise ValueError("Expected explicit hub HTTPS bindings")
    for binding in ports:
        if not isinstance(binding, str):
            raise ValueError("Expected explicit hub HTTPS bindings")
        address, port, target = binding.split(":")
        if not ipaddress.IPv4Address(address).is_private or port not in {"443", "18765"} or target != "18765":
            raise ValueError("Expected explicit private hub HTTPS bindings")
    mounts = {}
    for volume in [*hub["volumes"], *runtime["volumes"]]:
        if not isinstance(volume, str):
            raise ValueError("Only explicit bind mounts are supported")
        parts = volume.split(":")
        if len(parts) not in {2, 3} or not parts[0].startswith("/"):
            raise ValueError("Only absolute bind mounts are supported")
        target = parts[1]
        if target == "/tls" and volume in runtime["volumes"]:
            continue
        mounts[target] = volume
    hub["volumes"] = list(mounts.values())
    hub["group_add"] = list(dict.fromkeys([*hub.get("group_add", []), *runtime.get("group_add", [])]))
    hub["environment"].update(runtime["environment"])
    hub["environment"]["MEDIAHUB_RUNTIME_MODE"] = "embedded"
    hub["environment"].pop("MEDIAHUB_AGENT_TLS_CERT", None)
    hub["environment"].pop("MEDIAHUB_AGENT_TLS_KEY", None)
    hub["user"] = "10001"
    hub["mem_limit"] = "1g"
    hub["memswap_limit"] = "1g"
    result["services"]["proxy"] = {
        "image": "traefik:v3.3",
        "command": [
            "--entrypoints.hub.address=:18765",
            "--providers.file.filename=/etc/traefik/hub.json",
            "--api.dashboard=false",
            "--global.sendanonymoususage=false",
        ],
        "ports": ports,
        "volumes": [f"{root}/hub-proxy.json:/etc/traefik/hub.json:ro"],
        "networks": ["lan"],
        "restart": "unless-stopped",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "read_only": True,
        "mem_limit": "128m",
        "logging": copy.deepcopy(hub.get("logging", {})),
    }
    routing = {
        "tcp": {
            "routers": {"hub": {
                "entryPoints": ["hub"], "rule": "HostSNI(`*`)",
                "service": "hub", "tls": {"passthrough": True},
            }},
            "services": {"hub": {"loadBalancer": {"servers": [{"address": "core:18765"}]}}},
        },
    }
    return result, routing