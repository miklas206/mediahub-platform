import os

from cryptography.fernet import Fernet
from sqlalchemy import select

from mediahub.apps.containers import CONTAINER_APPS, INSTALLABLE_CONTAINER_APPS
from mediahub.apps.manifest import parse_manifest
from mediahub.db import AppConfiguration
from mediahub.errors import DomainError


class Catalog:
    def __init__(self, config, sessions, agent):
        self.config, self.sessions, self.agent = config, sessions, agent
        self.manifests = {}
        for file in sorted(config.manifest_dir.glob("*/manifest.yaml")):
            manifest = parse_manifest(file)
            if manifest.availability == "development" and not config.dev_mode:
                continue
            self.manifests[manifest.id] = manifest
        key_file = config.data_dir / "secrets.key"
        if not key_file.exists():
            descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(Fernet.generate_key())
        self.cipher = Fernet(key_file.read_bytes())

    def get(self, package_id):
        if package_id not in self.manifests:
            raise DomainError("not_found", "Catalog app not found", 404)
        return self.manifests[package_id]

    def list(self):
        retired = {"org.mediahub." + app for app in CONTAINER_APPS if app not in INSTALLABLE_CONTAINER_APPS}
        return [m.model_dump() for m in self.manifests.values() if m.id not in retired]

    def configuration(self, package_id):
        manifest = self.get(package_id)
        with self.sessions() as db:
            record = db.scalar(
                select(AppConfiguration).where(AppConfiguration.package_id == package_id)
            )
            return {
                "values": {
                    **{
                        f.name: f.default
                        for f in manifest.configFields
                        if not f.secret and f.default is not None
                    },
                    **(record.values if record else {}),
                },
                "secrets": {
                    f.name: {"configured": bool(record and f.name in record.encrypted_secrets)}
                    for f in manifest.configFields
                    if f.secret
                },
            }

    def save(self, package_id, values):
        manifest = self.get(package_id)
        fields = {f.name: f for f in manifest.configFields}
        if set(values) - fields.keys():
            raise DomainError("invalid_configuration", "Configuration contains unknown fields")
        with self.sessions.begin() as db:
            record = db.scalar(
                select(AppConfiguration).where(AppConfiguration.package_id == package_id)
            )
            if record is None:
                record = AppConfiguration(package_id=package_id, values={}, encrypted_secrets={})
                db.add(record)
            public, encrypted = dict(record.values), dict(record.encrypted_secrets)
            for name, value in values.items():
                field = fields[name]
                if not isinstance(value, str) or len(value) > 8192:
                    raise DomainError(
                        "invalid_configuration", "Configuration fields must be bounded text"
                    )
                if field.type == "select" and value not in field.options:
                    raise DomainError(
                        "invalid_configuration", "Select a supported configuration option"
                    )
                if field.secret:
                    if value:
                        encrypted[name] = self.cipher.encrypt(value.encode()).decode()
                else:
                    public[name] = value
            record.values, record.encrypted_secrets = public, encrypted
        return self.configuration(package_id)

    async def plan(self, package_id, mappings, agent=None):
        manifest = self.get(package_id)
        agent = agent or self.agent
        status = await agent.status()
        configured = self.configuration(package_id)
        blockers = ["App lifecycle is not implemented; this plan cannot execute"]
        missing_capabilities = set(manifest.hostCapabilities) - set(status.get("capabilities", []))
        if missing_capabilities:
            blockers.append("Host lacks capabilities: " + ", ".join(sorted(missing_capabilities)))
        if manifest.requiredRuntime == "docker" and not status.get("docker", {}).get("available"):
            blockers.append("A connected Docker runtime is required")
        required_slots = {s.id for s in manifest.storageRequirements if s.required}
        if required_slots - mappings.keys():
            blockers.append(
                "Missing required storage mappings: "
                + ", ".join(sorted(required_slots - mappings.keys()))
            )
        for slot, path in mappings.items():
            if slot not in {s.id for s in manifest.storageRequirements}:
                raise DomainError("invalid_mapping", "Unknown app storage slot")
            try:
                checked = await agent.request("POST", "/v1/directories/inspect", {"path": path})
                if not checked["readable"]:
                    blockers.append(f"Storage {slot} is not readable")
                required = next(s for s in manifest.storageRequirements if s.id == slot)
                if required.access == "rw" and not checked["writable"]:
                    blockers.append(f"Storage {slot} is not writable")
            except DomainError:
                blockers.append(f"Storage {slot} cannot be verified by the agent")
        for field in manifest.configFields:
            present = (
                configured["secrets"].get(field.name, {}).get("configured")
                if field.secret
                else configured["values"].get(field.name)
            )
            if field.required and not present:
                blockers.append(f"Required configuration missing: {field.label}")
        return {
            "packageId": package_id,
            "executable": False,
            "blockers": blockers,
            "containers": list(manifest.services),
            "images": [i.model_dump() for i in manifest.images.values()],
            "ports": [p.model_dump() for s in manifest.services.values() for p in s.ports],
            "mounts": [
                {**v.model_dump(), "source": mappings.get(v.slot)}
                for s in manifest.services.values()
                for v in s.volumes
            ],
            "secrets": configured["secrets"],
            "environment": configured["values"],
            "dependencies": [d.model_dump() for d in manifest.dependencies],
            "networks": {name: s.network.model_dump() for name, s in manifest.services.items()},
        }
