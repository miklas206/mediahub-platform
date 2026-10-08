"""Seedbox deployment contract. Pure planning; never executes caller-supplied Compose."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import Field, field_validator, model_validator

from mediahub.contracts import StrictModel


class SeedboxInstallation(StrictModel):
    installationId: str = Field(pattern=r"^[a-z][a-z0-9-]{2,40}$")
    hostId: str = Field(min_length=1, max_length=80)
    downloadsStorageId: str = Field(min_length=1, max_length=80)
    provider: str = Field(default="custom", pattern=r"^[a-z][a-z0-9-]{0,40}$")
    protocol: Literal["wireguard", "openvpn"] = "wireguard"
    region: str | None = Field(default=None, max_length=80)
    credentialRef: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,80}$")
    uid: int = Field(default=1000, ge=1000, le=65535)
    gid: int = Field(default=1000, ge=1000, le=65535)
    webPort: int = Field(default=18080, ge=1024, le=65535)
    vpnMemoryMiB: int = Field(default=256, ge=128, le=512)
    torrentMemoryMiB: int = Field(default=1024, ge=256, le=16384)


class SeedboxExtraStorage(StrictModel):
    """Host-authorized legacy seed location, never supplied by public install requests."""

    logicalId: str = Field(pattern=r"^[a-z][a-z0-9-]{1,60}$")
    displayName: str | None = Field(default=None, min_length=1, max_length=80)
    source: str
    target: str
    nfsSource: str
    storageMarker: str = Field(min_length=1, max_length=120)
    readOnly: bool = True
    allowTorrentDownload: bool = False

    @field_validator("displayName")
    @classmethod
    def display_name(cls, value):
        if value is not None and (not value.isprintable() or value.strip() != value):
            raise ValueError("Storage display name must be printable and trimmed")
        return value

    @model_validator(mode="after")
    def torrent_download_requires_write_access(self):
        if self.allowTorrentDownload and self.readOnly:
            raise ValueError("Torrent download destinations must be writable")
        return self

    @field_validator("source", "target")
    @classmethod
    def scoped_path(cls, value):
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or "\x00" in value:
            raise ValueError("Expected absolute storage path")
        if len(path.parts) < 3:
            raise ValueError("Additional storage must be narrowly scoped")
        if str(path) != value:
            raise ValueError("Storage path must be normalized")
        return value


class SeedboxRuntimePaths(StrictModel):
    """Resolved by trusted host policy, NOT accepted as arbitrary API install input."""

    downloads: str
    appdata: str
    vpnState: str
    vpnConfig: str
    dnsConfig: str
    extraStorage: list[SeedboxExtraStorage] = Field(default_factory=list, max_length=16)
    vpnImage: str = Field(pattern=r"^qmcgaw/gluetun@sha256:[a-f0-9]{64}$")
    torrentImage: str = Field(pattern=r"^lscr.io/linuxserver/qbittorrent@sha256:[a-f0-9]{64}$")

    @field_validator("downloads", "appdata", "vpnState", "vpnConfig", "dnsConfig")
    @classmethod
    def path_shape(cls, value):
        path = PurePosixPath(value)
        if not path.is_absolute() or str(path) == "/" or ".." in path.parts or "\x00" in value:
            raise ValueError("Expected non-root absolute host path")
        return value

    @model_validator(mode="after")
    def separate_storage(self):
        paths = [
            PurePosixPath(getattr(self, key))
            for key in ("downloads", "appdata", "vpnState", "vpnConfig", "dnsConfig")
        ]
        for index, path in enumerate(paths):
            for other in paths[index + 1 :]:
                if path == other or path in other.parents or other in path.parents:
                    raise ValueError("Runtime paths must not overlap")
        sources = list(paths)
        targets = [PurePosixPath(p) for p in ("/config", "/downloads", "/etc")]
        for mapping in self.extraStorage:
            source, target = PurePosixPath(mapping.source), PurePosixPath(mapping.target)
            for value, existing in ((source, sources), (target, targets)):
                if any(
                    value == old or value in old.parents or old in value.parents for old in existing
                ):
                    raise ValueError("Additional storage must not overlap runtime mounts")
                existing.append(value)
            if target.parts[1] in {
                "proc",
                "sys",
                "dev",
                "run",
                "usr",
                "bin",
                "sbin",
                "lib",
                "lib64",
                "root",
                "tmp",
                "var",
            }:
                raise ValueError("Additional storage cannot cover system paths")
        return self


def compose_plan(spec: SeedboxInstallation, paths: SeedboxRuntimePaths):
    """Secrets referenced as files only. All services initially stopped by executor.

    A plan is not proof of VPN protection. Executor must verify mount/source/marker,
    provision private config, start only VPN, validate its tunnel, then enable qbit.
    restart=no intentionally prevents Docker bypassing those gates after reboot.
    """

    def bind(source, target, readonly=False):
        return {
            "type": "bind",
            "source": source,
            "target": target,
            "read_only": readonly,
            "bind": {"create_host_path": False},
        }

    shared = {
        "restart": "no",
        "security_opt": ["no-new-privileges:true"],
        "ulimits": {"core": {"soft": 0, "hard": 0}},
        "logging": {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}},
    }
    vpn_env = {
        "VPN_SERVICE_PROVIDER": "custom",
        "VPN_TYPE": spec.protocol,
        "FIREWALL": "on",
        "FIREWALL_INPUT_PORTS": str(spec.webPort),
        "LOG_LEVEL": "warn",
    }
    config_target = "/gluetun/wireguard/wg0.conf"
    if spec.protocol == "openvpn":
        config_target = "/gluetun/custom.conf"
        vpn_env["OPENVPN_CUSTOM_CONFIG"] = config_target
    return {
        "name": "mediahub-" + spec.installationId,
        "services": {
            "vpn": {
                **shared,
                "image": paths.vpnImage,
                "cap_add": ["NET_ADMIN"],
                "devices": ["/dev/net/tun:/dev/net/tun"],
                "mem_limit": f"{spec.vpnMemoryMiB}m",
                "memswap_limit": f"{spec.vpnMemoryMiB}m",
                "cpus": 0.5,
                "environment": vpn_env,
                "ports": [f"127.0.0.1:{spec.webPort}:{spec.webPort}/tcp"],
                "volumes": [
                    bind(paths.vpnState, "/gluetun"),
                    bind(paths.vpnConfig, config_target, True),
                ],
            },
            "torrent": {
                **shared,
                "image": paths.torrentImage,
                "network_mode": "service:vpn",
                "depends_on": {"vpn": {"condition": "service_healthy"}},
                "mem_limit": f"{spec.torrentMemoryMiB}m",
                "memswap_limit": f"{spec.torrentMemoryMiB}m",
                "cpus": 1,
                "environment": {
                    "PUID": str(spec.uid),
                    "PGID": str(spec.gid),
                    "WEBUI_PORT": str(spec.webPort),
                },
                "volumes": [
                    bind(paths.appdata, "/config"),
                    bind(paths.downloads, "/downloads"),
                    bind(paths.dnsConfig, "/etc/resolv.conf", True),
                    *[bind(m.source, m.target, m.readOnly) for m in paths.extraStorage],
                ],
            },
        },
    }


def start_gate(*, mount_verified, device_health, tunnel_verified, requested_service):
    """Fail closed; callers must supply fresh observations, never cached success."""
    if requested_service not in {"vpn", "torrent"}:
        return False
    if not mount_verified or device_health not in {"healthy"}:
        return False
    return requested_service == "vpn" or tunnel_verified is True
