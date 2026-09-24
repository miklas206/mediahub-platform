"""Pure installation planning against an operator-approved host/storage policy.

Media paths are read-only bind mounts. Plex configuration uses a labelled,
non-swappable tmpfs volume; durable subdirectories have separate writable mounts.
Preferences (including account tokens) are deliberately NOT durable plaintext.
"""

import hashlib
import ipaddress
import json
from pathlib import Path
from typing import Literal

from mediahub.apps.plex import PlexInstallation
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field, field_validator


class PlexStorageChoice(StrictModel):
    label: str
    kind: Literal["movies", "tv", "other", "appdata"]
    path: str

    @field_validator("path")
    @classmethod
    def safe_absolute_path(cls, value):
        path = Path(value)
        if (
            not path.is_absolute()
            or path == Path(path.anchor)
            or ".." in path.parts
            or "\x00" in value
        ):
            raise ValueError("Expected an absolute non-root storage path")
        return value


class PlexInstallPolicy(StrictModel):
    hostId: str
    bindAddress: str
    image: str = Field(pattern=r"^lscr\.io/linuxserver/plex@sha256:[a-f0-9]{64}$")
    initImage: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    storage: dict[str, PlexStorageChoice]
    uid: int = Field(default=1000, ge=1, le=65535)
    gid: int = Field(default=1000, ge=1, le=65535)
    memoryBytes: int = Field(default=2 * 1024**3, ge=512 * 1024**2, le=32 * 1024**3)
    tmpfsNoSwap: bool = True
    reuseEncryptedPreferences: bool = False
    controlNetwork: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}$")
    hostMountSnapshot: str
    requiredMounts: dict[str, str] = Field(default_factory=dict)
    requiredFilesystemUuids: dict[str, str]
    storageMarkers: dict[str, str]

    @field_validator("bindAddress")
    @classmethod
    def private_lan_address(cls, value):
        address = ipaddress.ip_address(value)
        if (
            not address.is_private
            or address.is_loopback
            or address.is_unspecified
            or address.is_multicast
            or address.is_link_local
        ):
            raise ValueError("Plex requires an explicit private LAN address")
        return value


# Plex's account-bearing Preferences.xml stays in RAM; only these directories
# become durable app data. Logs and Crash Reports deliberately remain in RAM.
PERSISTENT_DIRECTORIES = (
    "Cache",
    "Codecs",
    "Media",
    "Metadata",
    "Plug-ins",
    "Plug-in Support",
    "Scanners",
)
PMS_ROOT = "/config/Library/Application Support/Plex Media Server"


def installation_plan(policy: PlexInstallPolicy, spec: PlexInstallation):
    if spec.hostId != policy.hostId:
        raise DomainError("plex_host_mismatch", "Plex host does not match the approved host", 409)
    if not (policy.requiredMounts or policy.requiredFilesystemUuids) or not policy.storageMarkers:
        raise DomainError(
            "plex_storage_guard_missing", "Verified media storage must be configured first", 409
        )
    bindings = []
    for kind, identifiers in (
        ("movies", spec.moviesStorageIds),
        ("tv", spec.tvStorageIds),
        ("other", spec.otherStorageIds),
    ):
        for index, identifier in enumerate(identifiers):
            choice = policy.storage.get(identifier)
            if choice is None or choice.kind != kind:
                raise DomainError(
                    "plex_storage_denied", "Selected media mapping is not approved for Plex", 403
                )
            bindings.append(
                {
                    "Type": "bind",
                    "Source": choice.path,
                    "Target": f"/media/{kind}/{index + 1}",
                    "ReadOnly": True,
                }
            )
    appdata = policy.storage.get(spec.appdataStorageId)
    if appdata is None or appdata.kind != "appdata":
        raise DomainError("plex_appdata_denied", "Choose approved app data storage", 403)
    for mount in bindings:
        media, data = Path(mount["Source"]), Path(appdata.path)
        if media == data or media in data.parents or data in media.parents:
            raise DomainError(
                "plex_storage_overlap", "App data must be separate from media folders", 409
            )
    name = "mediahub-" + spec.installationId
    labels = {
        "org.mediahub.package": "org.mediahub.plex",
        "org.mediahub.installation": spec.installationId,
    }
    app_root = str(Path(appdata.path) / spec.installationId)
    protected_roots = [
        Path(path) for path in (*policy.requiredMounts, *policy.requiredFilesystemUuids)
    ]
    for path in [app_root, *(mount["Source"] for mount in bindings)]:
        if not any(Path(path) == root or root in Path(path).parents for root in protected_roots):
            raise DomainError(
                "plex_unguarded_storage", "Every Plex path must be on verified storage", 409
            )
    volume = {
        "Name": name + "-runtime",
        "Driver": "local",
        "Labels": labels,
        "DriverOpts": {
            "type": "tmpfs",
            "device": "tmpfs",
            "o": f"size=512m,{('noswap,' if policy.tmpfsNoSwap else '')}nodev,nosuid,mode=0700,uid={policy.uid},gid={policy.gid}",
        },
    }
    # Codecs may need executable mappings. All media remain read-only; writable
    # app folders are explicit and never expand to their parent media directory.
    mounts = [
        {"Type": "volume", "Source": volume["Name"], "Target": "/config", "ReadOnly": False},
        *bindings,
    ]
    for directory in PERSISTENT_DIRECTORIES:
        mounts.append(
            {
                "Type": "bind",
                "Source": str(Path(app_root) / directory),
                "Target": PMS_ROOT + "/" + directory,
                "ReadOnly": False,
            }
        )
    container = {
        "Image": policy.image,
        "User": f"{policy.uid}:{policy.gid}",
        "Labels": labels,
        "Env": [
            f"PUID={policy.uid}",
            f"PGID={policy.gid}",
            "VERSION=docker",
            f"TZ={spec.timezone}",
            f"ADVERTISE_IP=http://{policy.bindAddress}:32400/",
            "FILE__PLEX_CLAIM=/config/.claim",
        ],
        "ExposedPorts": {"32400/tcp": {}},
        "HostConfig": {
            "Mounts": mounts,
            "NetworkMode": "bridge",
            "Privileged": False,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "ReadonlyRootfs": True,
            "Tmpfs": {
                "/run": f"rw,exec,{('noswap,' if policy.tmpfsNoSwap else '')}nosuid,nodev,size=64m,mode=0755,uid={policy.uid},gid={policy.gid}",
                "/tmp": f"rw,{('noswap,' if policy.tmpfsNoSwap else '')}nosuid,nodev,size=128m,mode=1777",
            },
            "PortBindings": {"32400/tcp": [{"HostIp": policy.bindAddress, "HostPort": "32400"}]},
            "Memory": policy.memoryBytes,
            "MemorySwap": policy.memoryBytes,
            "PidsLimit": 512,
            "RestartPolicy": {"Name": "no"},
            "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
            "LogConfig": {"Type": "none", "Config": {}},
        },
    }
    if policy.controlNetwork:
        container["NetworkingConfig"] = {
            "EndpointsConfig": {
                "bridge": {},
                policy.controlNetwork: {},
            }
        }
    plan = {
        "name": name,
        "runtimeVolume": volume,
        "container": container,
        "appdataPath": app_root,
        "installation": spec.model_dump(),
        "libraries": {
            kind: [m["Target"] for m in bindings if m["Target"].startswith("/media/" + kind + "/")]
            for kind in ("movies", "tv", "other")
        },
    }
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {**plan, "planDigest": digest}
