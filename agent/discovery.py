"""Allowlisted Docker discovery. Raw inspect data never leaves this boundary."""

import re


def sanitize_container(raw: dict) -> dict:
    config = raw.get("Config") or {}
    env = {}
    for entry in config.get("Env") or []:
        name, _, value = entry.partition("=")
        if re.fullmatch(r"[A-Z_][A-Z0-9_]{0,79}", name):
            env[name] = value
    image = config.get("Image", "")
    mounts = [
        {
            "type": m.get("Type"),
            "source": m.get("Source"),
            "target": m.get("Destination"),
            "writable": bool(m.get("RW")),
        }
        for m in raw.get("Mounts", [])
    ]
    host = raw.get("HostConfig") or {}
    network = raw.get("NetworkSettings") or {}
    ports = []
    for target, mappings in (network.get("Ports") or {}).items():
        for mapping in mappings or []:
            port = str(mapping.get("HostPort", ""))
            if port.isdigit():
                ports.append(
                    {
                        "container": target,
                        "hostPort": int(port),
                        "hostIp": mapping.get("HostIp", ""),
                    }
                )
    image_lower = image.lower()
    candidates = []
    for app, tokens in {
        "plex": ["plex"],
        "qbittorrent": ["qbittorrent"],
        "vpn": ["gluetun", "wireguard", "openvpn"],
    }.items():
        if any(token in image_lower.rsplit("/", 1)[-1] for token in tokens):
            candidates.append(
                {
                    "app": app,
                    "confidence": "possible",
                    "reason": "Image name matches a known app pattern",
                }
            )
    protocol = env.get("VPN_TYPE", "").lower()
    if protocol not in {"wireguard", "openvpn"}:
        protocol = None
    return {
        "id": raw.get("Id"),
        "name": str(raw.get("Name", "")).lstrip("/"),
        "image": image,
        "status": (raw.get("State") or {}).get("Status", "unknown"),
        "health": ((raw.get("State") or {}).get("Health") or {}).get("Status", "unknown"),
        "ports": ports,
        "networks": list((network.get("Networks") or {}).keys()),
        "networkMode": host.get("NetworkMode", "unknown"),
        "mounts": mounts,
        "environmentNames": sorted(env),
        "uid": int(env["PUID"]) if env.get("PUID", "").isdigit() else None,
        "gid": int(env["PGID"]) if env.get("PGID", "").isdigit() else None,
        "protocol": protocol,
        "candidates": candidates,
        "version": None,
        "configMounts": [m for m in mounts if m["target"] in {"/config", "/gluetun"}],
        "mediaMounts": [m for m in mounts if m["target"] not in {"/config", "/gluetun"}],
    }


def discovery_report(raw_items: list[dict], fixture: bool = False):
    containers = [sanitize_container(raw) for raw in raw_items]
    by_id = {c["id"]: c for c in containers}
    by_name = {c["name"]: c for c in containers}
    relationships = []
    for container in containers:
        mode = container["networkMode"]
        if mode.startswith("container:"):
            target = mode.split(":", 1)[1]
            shared = by_id.get(target) or by_name.get(target)
            relationships.append(
                {
                    "sourceId": container["id"],
                    "targetId": shared["id"] if shared else target,
                    "type": "shared-network-namespace",
                    "verified": False,
                    "evidence": "Docker HostConfig.NetworkMode; no process/network probe performed",
                }
            )
    return {
        "source": "fixture" if fixture else "docker",
        "containers": containers,
        "relationships": relationships,
        "warning": "Development fixtures — not your server"
        if fixture
        else "Read-only discovery; matches are possible installations, not verified apps",
    }
