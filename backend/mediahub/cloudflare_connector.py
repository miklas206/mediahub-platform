"""Run an explicitly requested tunnel connector on the existing Docker host."""

import os
from pathlib import PurePosixPath

from agent.install_images import pull_latest
from mediahub.errors import DomainError


async def install(manager, tunnel):
    state = manager.state()
    prefix = manager.prefix(state, tunnel)
    runtime = manager.svc.managed_apps
    if not manager.svc.config.managed_apps_docker_socket:
        raise DomainError("connector_runtime", "The MediaHub Docker host is not configured", 409)
    own = await runtime.docker("GET", "/containers/" + os.environ.get("HOSTNAME", "") + "/json")
    if (
        own.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
        != "mediahub-platform"
    ):
        raise DomainError("connector_runtime", "MediaHub host ownership could not be verified", 409)
    data = next(
        (m for m in own.get("Mounts", []) if m["Type"] == "bind" and m["Destination"] == "/data"),
        None,
    )
    trust = next(
        (m for m in own.get("Mounts", []) if m["Type"] == "bind" and m["Destination"] == "/trust"),
        None,
    )
    if not data or not trust:
        raise DomainError(
            "connector_runtime", "MediaHub data and local CA mounts are required", 409
        )
    name = "mediahub-cloudflared-" + tunnel
    existing = await runtime.docker("GET", "/containers/" + name + "/json", missing=True)
    if existing:
        if (
            existing.get("Config", {}).get("Labels", {}).get("org.mediahub.cloudflare.tunnel")
            != tunnel
        ):
            raise DomainError("connector_ownership", "Connector container ownership changed", 409)
        if not existing["State"].get("Running"):
            await runtime.docker("POST", "/containers/" + existing["Id"] + "/start")
        return {"state": "running", "tunnelId": tunnel, "location": "MediaHub host"}
    token = await manager.call("GET", prefix + "/token")
    directory = manager.svc.config.data_dir / "cloudflare-connectors"
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (tunnel + ".token")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    with os.fdopen(descriptor, "w") as stream:
        stream.write(str(token))
    image = await pull_latest(
        manager.svc.config.managed_apps_docker_socket, "cloudflare/cloudflared"
    )
    await runtime.docker(
        "POST",
        "/containers/create?name=" + name,
        body={
            "Image": image["Id"],
            "User": "10001:10001",
            "Labels": {"org.mediahub.cloudflare.tunnel": tunnel},
            "Cmd": ["tunnel", "--no-autoupdate", "run", "--token-file", "/run/token"],
            "HostConfig": {
                "Binds": [
                    str(PurePosixPath(data["Source"]) / "cloudflare-connectors" / path.name)
                    + ":/run/token:ro",
                    trust["Source"] + "/ca.pem:/etc/cloudflared/mediahub-ca.pem:ro",
                ],
                "NetworkMode": "bridge",
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "RestartPolicy": {"Name": "unless-stopped"},
                "LogConfig": {"Type": "none", "Config": {}},
            },
        },
    )
    await runtime.docker("POST", "/containers/" + name + "/start")
    return {"state": "starting", "tunnelId": tunnel, "location": "MediaHub host"}
