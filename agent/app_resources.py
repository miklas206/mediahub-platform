"""Bind resource operations to the Agent's existing approved app installations."""

from pathlib import Path

from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.resource_control import DockerResources


def agent_resources(config, plex, containers):
    async def resolve(package):
        if package == "plex":
            policy = plex.control.policy()
            row = await plex.control.inspect(policy)
            identity = policy.installationId
        else:
            containers.app(package)
            record = containers.record(package)
            if not record:
                raise DomainError("not_installed", "The app is not installed on this Agent.", 409)
            row = await containers.request("GET", "/containers/" + record["name"] + "/json")
            containers.verify(row, record)
            identity = record["container"]["Labels"]["org.mediahub.installation"]
        return {
            "installationId": identity,
            "targets": [{"id": row["Id"], "component": "app", "inspect": row}],
        }

    async def request(method, path, body=None):
        return await containers.request(method, path, body=body)

    async def persist(package, parts):
        binding = await resolve(package)
        path = Path(config.state_dir) / "app-resource-limits.json"
        saved = read_json(path) if path.is_file() else {}
        saved["org.mediahub." + package] = {
            "installationId": binding["installationId"],
            "components": parts,
        }
        save_json(path, saved)

    return DockerResources(request, resolve, persist, config.state_dir)
