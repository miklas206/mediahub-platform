import asyncio
import copy
import hashlib
import json
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from pydantic import ValidationError
from test_container_apps import inspected_container, runtime_and_spec
from test_shared_vpn import controller

from agent.gpu import GPUGrant
from agent.install_files import read_json, save_json
from scripts import gpu_setup, proxmox_gpu

NVIDIA = {
    "id": "GPU-abcd1234-1234",
    "name": "RTX 3070 Ti",
    "vendor": "nvidia",
    "uuid": "GPU-abcd1234-1234",
    "devices": ["/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm"],
}
INTEL = {
    "id": "intel-0000:00:02.0",
    "name": "Intel GPU",
    "vendor": "intel",
    "devices": ["/dev/dri/renderD128"],
}


def gpu_runtime(tmp_path, monkeypatch, grant=NVIDIA):
    runtime, spec = runtime_and_spec(tmp_path, "jellyfin")
    policy = json.loads(runtime.policy_file.read_text())
    policy["gpus"] = [grant]
    runtime.policy_file.write_text(json.dumps(policy))
    monkeypatch.setattr("agent.gpu.available", lambda _: True)
    monkeypatch.setattr("agent.container_apps.gpu_available", lambda _: True)
    monkeypatch.setattr(
        "agent.gpu.Path", lambda _: SimpleNamespace(stat=lambda: SimpleNamespace(st_gid=104))
    )
    runtime.request = AsyncMock(return_value={"Runtimes": {"nvidia": {}}})
    return runtime, spec.model_copy(update={"gpuId": grant["id"]})


@pytest.mark.parametrize("grant", [NVIDIA, INTEL])
def test_gpu_is_explicit_scoped_and_part_of_reviewed_plan(tmp_path, monkeypatch, grant):
    runtime, spec = gpu_runtime(tmp_path, monkeypatch, grant)
    plan = asyncio.run(runtime.build_plan(spec))
    cpu = asyncio.run(runtime.build_plan(spec.model_copy(update={"gpuId": None})))
    assert cpu["planDigest"] != plan["planDigest"]
    assert "gpuId" not in cpu["installation"]
    assert not cpu["container"]["HostConfig"].get("Devices")
    host = plan["container"]["HostConfig"]
    if grant["vendor"] == "nvidia":
        assert host["Runtime"] == "nvidia"
        assert host["DeviceRequests"][0]["DeviceIDs"] == [grant["uuid"]]
        assert host["DeviceRequests"][0]["Count"] == 0  # never all GPUs
        assert {device["PathOnHost"] for device in host["Devices"]} == set(grant["devices"])
        assert host["GroupAdd"] == ["104"]
    else:
        assert host["Devices"] == [
            {
                "PathOnHost": "/dev/dri/renderD128",
                "PathInContainer": "/dev/dri/renderD128",
                "CgroupPermissions": "rw",
            }
        ]
        assert host["GroupAdd"] == ["104"]
    assert host["Privileged"] is False and host["CapDrop"] == ["ALL"]
    old_spec = spec.model_dump(exclude={"gpuId"})
    assert (
        cpu["planDigest"]
        == hashlib.sha256(
            json.dumps({"spec": old_spec, "container": cpu["container"]}, sort_keys=True).encode()
        ).hexdigest()
    )
    row = inspected_container(plan)
    plan["imageId"] = row["Image"]
    runtime.verify(row, plan)
    assert runtime.gpu_ready(plan)
    if grant["vendor"] == "nvidia":
        row["HostConfig"]["DeviceRequests"][0]["DeviceIDs"] = ["GPU-other"]
    else:
        row["HostConfig"]["Devices"][0]["PathOnHost"] = "/dev/dri/renderD129"
    with pytest.raises(DomainError, match="no longer matches"):
        runtime.verify(row, plan)
    policy = json.loads(runtime.policy_file.read_text())
    policy["gpus"] = []
    runtime.policy_file.write_text(json.dumps(policy))
    assert not runtime.gpu_ready(plan)


def test_missing_runtime_unapproved_and_wrong_app_are_rejected(tmp_path, monkeypatch):
    runtime, spec = gpu_runtime(tmp_path, monkeypatch)
    runtime.request.return_value = {"Runtimes": {"runc": {}}}
    choices = asyncio.run(runtime.options("jellyfin"))
    assert choices["gpus"][0]["available"] is False
    with pytest.raises(DomainError):
        asyncio.run(runtime.build_plan(spec))
    runtime.request.return_value = {"Runtimes": {"nvidia": {}}}
    for invalid in (
        spec.model_copy(update={"gpuId": "unknown"}),
        spec.model_copy(update={"app": "prowlarr", "storageIds": {"appdata": "appdata"}}),
    ):
        with pytest.raises(DomainError):
            asyncio.run(runtime.build_plan(invalid))
    monkeypatch.setattr("agent.gpu.available", lambda _: False)
    with pytest.raises(DomainError):
        asyncio.run(runtime.build_plan(spec))


@pytest.mark.parametrize(
    "devices",
    [
        ["/dev/mem"],
        ["/dev/dri"],
        ["/dev/dri/renderD128", "/dev/dri/renderD128"],
        ["/dev/dri/../mem"],
    ],
)
def test_policy_never_grants_arbitrary_devices(devices):
    with pytest.raises(ValidationError):
        GPUGrant(**{**INTEL, "devices": devices})


def test_vpn_enable_disable_preserves_gpu_access(tmp_path):
    control, peer, events, path = controller(tmp_path)
    record = read_json(path)
    gpu_host = {
        "Runtime": "nvidia",
        "DeviceRequests": [
            {"Driver": "nvidia", "DeviceIDs": [NVIDIA["uuid"]], "Capabilities": [["gpu"]]}
        ],
    }
    record["container"]["HostConfig"].update(copy.deepcopy(gpu_host))
    record["container"]["Env"] = ["NVIDIA_VISIBLE_DEVICES=" + NVIDIA["uuid"]]
    save_json(path, record)
    control.relay = AsyncMock(return_value={"Id": "relay", "State": {"StartedAt": "generation"}})
    control.status = AsyncMock(return_value={"enabled": True})
    asyncio.run(control.configuration("jellyfin", peer, True))
    for key, value in gpu_host.items():
        assert read_json(path)["container"]["HostConfig"][key] == value
    original_request = control.request

    async def recreated_request(method, url, body=None, missing=False):
        if method == "GET" and url == "/containers/mediahub-jellyfin/json":
            return {"Id": "recreated", "State": {"Running": True}}
        return await original_request(method, url, body, missing)

    control.request = recreated_request
    asyncio.run(control.configuration("jellyfin", None, False))
    for key, value in gpu_host.items():
        assert read_json(path)["container"]["HostConfig"][key] == value


def test_controller_compose_preserves_storage_and_other_devices(monkeypatch):
    monkeypatch.setattr(
        gpu_setup, "Path", lambda _: SimpleNamespace(stat=lambda: SimpleNamespace(st_gid=1000))
    )
    compose = {
        "services": {
            "core": {
                "devices": ["/dev/net/tun:/dev/net/tun"],
                "volumes": ["/media:/media:ro"],
                "group_add": ["10001"],
            },
            "proxy": {"image": "proxy"},
        }
    }
    result = gpu_setup.compose_gpu(copy.deepcopy(compose), [INTEL])
    assert result["services"]["core"]["volumes"] == ["/media:/media:ro"]
    assert result["services"]["core"]["devices"] == [
        "/dev/net/tun:/dev/net/tun",
        "/dev/dri/renderD128:/dev/dri/renderD128:rw",
    ]
    assert result["services"]["proxy"] == compose["services"]["proxy"]
    assert gpu_setup.compose_gpu(copy.deepcopy(result), [INTEL]) == result


def test_proxmox_refuses_running_guest_before_any_mutation(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(proxmox_gpu, "run", lambda *args: calls.append(args) or "status: running")
    with pytest.raises(ValueError, match="Stop"):
        proxmox_gpu.configure("107", NVIDIA, tmp_path / "inventory.json")
    assert calls == [("pct", "status", "107")]


def test_proxmox_discovery_excludes_non_gpu_devices(monkeypatch):
    monkeypatch.setattr(
        proxmox_gpu.shutil,
        "which",
        lambda command: "/usr/bin/nvidia-smi" if command == "nvidia-smi" else None,
    )
    monkeypatch.setattr(
        proxmox_gpu, "run", lambda *args: NVIDIA["uuid"] + ", NVIDIA RTX 3070 Ti, 0"
    )

    class Device:
        def __init__(self, path):
            self.path = str(path)

        def __truediv__(self, other):
            return Device(self.path + "/" + other)

        def glob(self, pattern):
            return []

        def exists(self):
            return self.path in NVIDIA["devices"]

        def stat(self):
            return SimpleNamespace(st_mode=stat.S_IFCHR)

        def __str__(self):
            return self.path

        def __eq__(self, other):
            return isinstance(other, Device) and self.path == other.path

    monkeypatch.setattr(proxmox_gpu, "Path", Device)
    assert proxmox_gpu.discover() == [NVIDIA | {"name": "NVIDIA RTX 3070 Ti"}]


def test_proxmox_gpu_mapping_keeps_tun_and_uses_free_slot(tmp_path, monkeypatch):
    from pathlib import Path

    configuration = tmp_path / "lxc/107.conf"
    configuration.parent.mkdir()
    original = "unprivileged: 1\ndev0: path=/dev/net/tun,uid=0,gid=0,mode=0600\nmp0: local:32,mp=/storage\n"
    configuration.write_text(original)

    def mapped_path(value):
        if value == "/etc/pve/lxc":
            return configuration.parent
        if value == "/var/lib/mediahub-gpu":
            return tmp_path / "gpu"
        if value == INTEL["devices"][0]:
            return SimpleNamespace(stat=lambda: SimpleNamespace(st_mode=stat.S_IFCHR))
        return Path(value)

    calls = []

    def request(*args):
        calls.append(args)
        return "status: stopped" if args[:2] == ("pct", "status") else ""

    monkeypatch.setattr(proxmox_gpu, "Path", mapped_path)
    monkeypatch.setattr(proxmox_gpu, "run", request)
    inventory = tmp_path / "inventory.json"
    proxmox_gpu.configure("107", INTEL, inventory)
    assert calls[-1] == (
        "pct",
        "set",
        "107",
        "--dev1",
        "path=/dev/dri/renderD128,uid=10001,gid=1000,mode=0660",
    )
    assert configuration.read_text() == original
    assert json.loads(inventory.read_text()) == [INTEL]
    assert (tmp_path / "gpu/107/before-gpu.conf").read_text() == original


def test_nvidia_driver_libraries_must_exist_before_guest_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(proxmox_gpu, "run", lambda *args: "")
    with pytest.raises(ValueError, match="matching NVIDIA userspace"):
        proxmox_gpu.stage_nvidia(tmp_path / "driver")
    assert not (tmp_path / "driver").exists()


@pytest.mark.parametrize(
    "uid,mode",
    [(10001, stat.S_IFREG | 0o600), (0, stat.S_IFREG | 0o666), (0, stat.S_IFLNK | 0o777)],
)
def test_untrusted_inventory_is_rejected_before_reading(uid, mode, monkeypatch):
    monkeypatch.setattr(
        gpu_setup,
        "Path",
        lambda _: SimpleNamespace(lstat=lambda: SimpleNamespace(st_uid=uid, st_mode=mode)),
    )
    with pytest.raises(ValueError, match="root-owned"):
        gpu_setup.read_inventory("inventory")
