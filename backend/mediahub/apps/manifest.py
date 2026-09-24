from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import Field, field_validator, model_validator
from yaml.tokens import AliasToken, AnchorToken, TagToken

from mediahub.contracts import StrictModel
from mediahub.errors import DomainError

SEMVER = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
CAPABILITIES = Literal[
    "metrics.read",
    "storage.mapped.read",
    "storage.mapped.write",
    "network.vpn",
    "network.port-forwarding",
    "gpu",
    "mock.lifecycle",
]


class Maintainer(StrictModel):
    name: str
    contact: str | None = None


class Image(StrictModel):
    repository: str
    digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")


class Environment(StrictModel):
    literal: str | None = None
    settingRef: str | None = None
    secretRef: str | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if sum(v is not None for v in (self.literal, self.settingRef, self.secretRef)) != 1:
            raise ValueError("Environment requires exactly one literal, settingRef or secretRef")
        return self


class Port(StrictModel):
    id: str
    containerPort: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    exposure: Literal["internal", "proxy-only", "lan"] = "internal"


class Volume(StrictModel):
    slot: str
    target: str
    access: Literal["ro", "rw"] = "ro"

    @field_validator("target")
    @classmethod
    def safe_target(cls, value):
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or value == "/":
            raise ValueError("Volume target must be a non-root absolute container path")
        return value


class Network(StrictModel):
    policy: Literal["isolated", "lan", "vpn-required"] = "isolated"
    role: Literal["gateway", "client"] = "client"
    shareWith: str | None = None


class Resources(StrictModel):
    memoryMiB: int = Field(default=256, ge=64, le=262144)


class SecretFile(StrictModel):
    secret: str
    target: str


class Service(StrictModel):
    image: str
    network: Network = Network()
    resources: Resources = Resources()
    ports: list[Port] = []
    volumes: list[Volume] = []
    environment: dict[str, Environment] = {}
    secretFiles: list[SecretFile] = []


class StorageRequirement(StrictModel):
    id: str
    type: Literal[
        "appdata",
        "downloads",
        "incomplete_downloads",
        "completed_downloads",
        "movies",
        "tv",
        "backups",
        "temp",
        "custom",
    ]
    access: Literal["ro", "rw"]
    required: bool = True


class Secret(StrictModel):
    id: str
    kind: Literal["file", "text"]
    required: bool = True


class Dependency(StrictModel):
    id: str
    version: str

    @field_validator("version")
    @classmethod
    def valid_range(cls, value):
        from packaging.specifiers import SpecifierSet

        SpecifierSet(value)
        return value


class Check(StrictModel):
    id: str
    type: Literal["adapter"] = "adapter"
    check: str
    intervalSeconds: int = Field(default=15, ge=1)
    timeoutSeconds: int = Field(default=5, ge=1)


class UpdateSource(StrictModel):
    type: Literal["catalog", "none"]
    channel: str = "stable"
    package: str | None = None
    signingIdentity: str | None = None


class Adapter(StrictModel):
    id: str
    protocolVersion: Literal[1] = 1


class ConfigField(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    type: Literal["text", "select", "password"] = "text"
    secret: bool = False
    required: bool = False
    options: list[str] = []
    default: str | None = None

    @model_validator(mode="after")
    def secret_policy(self):
        if self.secret and (self.default is not None or self.type != "password"):
            raise ValueError("Secrets must be password fields without defaults")
        if self.type == "password" and not self.secret:
            raise ValueError("Password fields must be marked secret")
        return self


class DeviceRequirement(StrictModel):
    """Concrete selectors belong to installation config, never a shared catalog."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    type: Literal["usb", "block"]
    selectorRef: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    required: bool = True
    missingHealth: Literal["degraded", "critical"] = "critical"
    mountRequired: bool = False
    writeRequired: bool = False

    @model_validator(mode="after")
    def mount_policy(self):
        if self.writeRequired and not self.mountRequired:
            raise ValueError("writeRequired also requires mountRequired")
        if self.type != "block" and (self.mountRequired or self.writeRequired):
            raise ValueError("Mount requirements only apply to block devices")
        return self


class Manifest(StrictModel):
    schemaVersion: Literal[1]
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$")
    name: str = Field(min_length=1, max_length=80)
    description: str
    category: str
    version: str = Field(pattern=SEMVER)
    maintainer: Maintainer
    icon: str
    repository: str | None = None
    homepage: str | None = None
    coreCompatibility: str = ">=0.1.0.dev0,<0.2.0"
    settingsSchema: str | None = None
    images: dict[str, Image]
    services: dict[str, Service]
    storageRequirements: list[StorageRequirement]
    secrets: list[Secret]
    dependencies: list[Dependency]
    optionalDependencies: list[Dependency] = []
    healthChecks: list[Check]
    capabilities: list[CAPABILITIES]
    updateSource: UpdateSource
    adapter: Adapter
    availability: Literal["coming-soon", "development", "available"] = "development"
    requiredRuntime: Literal["none", "docker"] = "none"
    recommendedIsolation: Literal["shared-host", "dedicated-host"] = "shared-host"
    hostCapabilities: list[str] = []
    configFields: list[ConfigField] = []
    requiredDevices: list[DeviceRequirement] = []

    @model_validator(mode="after")
    def references(self):
        from packaging.specifiers import SpecifierSet

        SpecifierSet(self.coreCompatibility)
        if len({device.id for device in self.requiredDevices}) != len(self.requiredDevices):
            raise ValueError("Device requirement identifiers must be unique")
        slots = {s.id: s for s in self.storageRequirements}
        if self.availability == "available" and any(
            image.digest is None for image in self.images.values()
        ):
            raise ValueError("Available apps require pinned image digests")
        if len({field.name for field in self.configFields}) != len(self.configFields):
            raise ValueError("Configuration field names must be unique")
        secrets = {s.id for s in self.secrets}
        if len(slots) != len(self.storageRequirements) or len(secrets) != len(self.secrets):
            raise ValueError("Duplicate storage or secret identifier")
        for name, service in self.services.items():
            if service.image not in self.images:
                raise ValueError(f"Service {name} references an unknown image")
            if service.network.shareWith is not None:
                if (
                    service.network.shareWith not in self.services
                    or service.network.shareWith == name
                ):
                    raise ValueError("Invalid shared network service")
            for volume in service.volumes:
                if volume.slot not in slots:
                    raise ValueError("Volume references an unknown storage slot")
                if volume.access == "rw" and slots[volume.slot].access == "ro":
                    raise ValueError("Volume cannot escalate read-only storage")
            for env in service.environment.values():
                if env.secretRef and env.secretRef not in secrets:
                    raise ValueError("Unknown secret reference")
            if any(f.secret not in secrets for f in service.secretFiles):
                raise ValueError("Unknown secret file reference")
        return self


class UniqueSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in seen:
                raise ValueError("Manifest mappings require unique string keys")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def parse_manifest(path: Path) -> Manifest:
    try:
        if path.stat().st_size > 128 * 1024:
            raise ValueError("Manifest exceeds 128 KiB")
        source = path.read_text(encoding="utf-8")
        if any(
            isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in yaml.scan(source)
        ):
            raise ValueError("YAML aliases, anchors and tags are not allowed")
        return Manifest.model_validate(yaml.load(source, Loader=UniqueSafeLoader))
    except (ValueError, OSError, yaml.YAMLError) as error:
        # Pydantic errors may contain supplied input. Do not log their raw representation.
        if hasattr(error, "errors"):
            details = "; ".join(
                ".".join(map(str, e["loc"])) + ": " + e["msg"]
                for e in error.errors(include_input=False, include_url=False)
            )
        else:
            details = "Invalid YAML, unsupported tokens or unreadable manifest"
        raise DomainError("invalid_manifest", details) from None
