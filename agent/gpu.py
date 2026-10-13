"""Explicit operator GPU grants. HTTP callers select IDs, never device paths."""

import os
import re
import stat
from pathlib import Path
from typing import Literal

from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field, model_validator


class GPUGrant(StrictModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)
    vendor: Literal["intel", "amd", "nvidia"]
    devices: list[str] = Field(min_length=1, max_length=16)
    uuid: str | None = Field(default=None, pattern=r"^GPU-[a-fA-F0-9-]{8,60}$")

    @model_validator(mode="after")
    def trusted_devices(self):
        if len(set(self.devices)) != len(self.devices):
            raise ValueError("Duplicate GPU device")
        pattern = (
            r"/dev/nvidia(?:[0-9]+|ctl|-uvm|-uvm-tools|-modeset)|/dev/nvidia-caps/nvidia-cap[0-9]+"
            if self.vendor == "nvidia"
            else r"/dev/dri/renderD[0-9]+"
        )
        if not all(re.fullmatch(pattern, p) for p in self.devices):
            raise ValueError("GPU grant contains an unsupported device")
        if self.vendor == "nvidia" and (
            not self.uuid
            or "/dev/nvidiactl" not in self.devices
            or not any(re.fullmatch(r"/dev/nvidia[0-9]+", p) for p in self.devices)
        ):
            raise ValueError("NVIDIA grant requires its UUID and control device")
        if self.vendor != "nvidia" and self.uuid:
            raise ValueError("DRM grants cannot request NVIDIA GPUs")
        return self


def available(grant):
    try:
        return all(
            stat.S_ISCHR(Path(p).stat().st_mode) and os.access(p, os.R_OK | os.W_OK)
            for p in grant.devices
        )
    except OSError:
        return False


def apply_gpu(container, grant):
    if not available(grant):
        raise DomainError(
            "gpu_unavailable", "The selected GPU is unavailable or not accessible to MediaHub", 409
        )
    host = container["HostConfig"]
    container["Labels"]["org.mediahub.gpu"] = grant.id
    # Explicit device rules are needed for rootful Docker inside an LXC where
    # NVIDIA's toolkit cannot manage the ancestor cgroup (no-cgroups mode).
    host["Devices"] = [
        {"PathOnHost": p, "PathInContainer": p, "CgroupPermissions": "rw"} for p in grant.devices
    ]
    host["GroupAdd"] = sorted({str(Path(p).stat().st_gid) for p in grant.devices})
    if grant.vendor == "nvidia":
        host["Runtime"] = "nvidia"
        host["DeviceRequests"] = [
            {
                "Driver": "nvidia",
                "Count": 0,
                "DeviceIDs": [grant.uuid],
                "Capabilities": [["gpu"]],
                "Options": {},
            }
        ]
        container["Env"] += [
            "NVIDIA_VISIBLE_DEVICES=" + grant.uuid,
            "NVIDIA_DRIVER_CAPABILITIES=compute,video,utility",
        ]


def verify_gpu(actual, expected):
    host = actual.get("HostConfig", {})
    policy = expected["HostConfig"]
    return (
        (host.get("Devices") or []) == policy.get("Devices", [])
        and (host.get("DeviceRequests") or []) == policy.get("DeviceRequests", [])
        and sorted(host.get("GroupAdd") or []) == sorted(policy.get("GroupAdd", []))
        and (not policy.get("Runtime") or host.get("Runtime") == policy["Runtime"])
    )
