"""Read-only Docker foundation. No transport is opened by MediaHub Core.

Even a read-only bind mount of docker.sock grants Docker API write capability.
Only an explicitly provisioned agent may receive a socket in a later phase.
"""

from typing import Protocol

import httpx


class ReadTransport(Protocol):
    async def get(self, path: str) -> dict | list: ...


class DockerReadError(Exception):
    pass


class UnixDockerTransport:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path

    async def get(self, path: str):
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=self.socket_path),
                base_url="http://docker",
                timeout=5,
            ) as client:
                response = await client.get(path)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise DockerReadError("Container service unavailable") from None


class DockerReader:
    def __init__(self, transport: ReadTransport, instance_label: str):
        self.transport, self.instance_label = transport, instance_label

    def owned(self, labels):
        return (labels or {}).get("org.mediahub.instance") == self.instance_label

    async def list_containers(self):
        items = await self.transport.get("/containers/json?all=1")
        return [
            {"id": i["Id"], "state": i["State"], "image": i["Image"]}
            for i in items
            if self.owned(i.get("Labels"))
        ]

    async def inspect(self, container_id: str):
        if len(container_id) != 64 or any(c not in "0123456789abcdef" for c in container_id):
            raise DockerReadError("Invalid container identifier")
        item = await self.transport.get(f"/containers/{container_id}/json")
        if not self.owned(item.get("Config", {}).get("Labels")):
            raise DockerReadError("Container is not managed by this MediaHub instance")
        # Deliberately exclude Config.Env, commands, arbitrary labels and raw State.Error.
        return {
            "id": item["Id"],
            "imageId": item.get("Image"),
            "status": item.get("State", {}).get("Status", "unknown"),
            "mounts": [
                {"target": m.get("Destination"), "writable": m.get("RW")}
                for m in item.get("Mounts", [])
            ],
            "networks": list(item.get("NetworkSettings", {}).get("Networks", {})),
        }


class RuntimeCommands(Protocol):
    """Contract only: intentionally no executable mutating implementation in Phase 1."""

    async def start(self, container_id: str): ...
    async def stop(self, container_id: str): ...
    async def restart(self, container_id: str): ...
    async def logs(self, container_id: str): ...
