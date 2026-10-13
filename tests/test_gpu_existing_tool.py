import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_gpu_installation import INTEL, NVIDIA

from scripts import gpu_setup, proxmox_gpu


def test_repair_wizard_only_recreates_controllers(tmp_path, monkeypatch):
    tool = existing_tool(monkeypatch)
    monkeypatch.setattr(
        tool, "Path", lambda value: tmp_path if value == "/etc/pve" else Path(value)
    )
    calls = []

    def run(*args):
        calls.append(args)
        if args[:2] == ("pct", "status"):
            return "status: running"
        if "cat" in args:
            return json.dumps({"services": {"core": {}, "proxy": {}}})
        return ""

    monkeypatch.setattr(tool, "run", run)
    monkeypatch.setattr(tool, "guest", lambda *args: calls.append(args))
    monkeypatch.setattr(
        sys, "argv", ["setup-existing-gpu.py", "--ctid", "107", "--repair-video-access", "--yes"]
    )
    tool.main()
    assert not any("shutdown" in call or "start" in call or "restart" in call for call in calls)
    recreated = [call for call in calls if "up" in call]
    assert len(recreated) == 1 and recreated[0][-2:] == ("--no-deps", "core")
    assert any("--repair-video-access" in call for call in calls)
    assert "--test-only" in calls[-1]


def test_video_grants_remove_admin_nodes_without_changing_input_or_uuid():
    legacy = NVIDIA | {
        "devices": NVIDIA["devices"]
        + ["/dev/nvidia-caps/nvidia-cap1", "/dev/nvidia-modeset", "/dev/nvidia-uvm-tools"]
    }
    assert gpu_setup.video_grants([legacy, INTEL]) == [NVIDIA, INTEL]
    assert "/dev/nvidia-caps/nvidia-cap1" in legacy["devices"]


def test_video_repair_preserves_storage_other_services_and_backups(tmp_path, monkeypatch):
    legacy = NVIDIA | {"devices": NVIDIA["devices"] + ["/dev/nvidia-caps/nvidia-cap1"]}
    (tmp_path / "agent").mkdir()
    inventory = tmp_path / "inventory.json"
    policy = tmp_path / "agent/container-apps.json"
    compose = tmp_path / "compose.json"
    inventory.write_text(json.dumps([legacy]))
    policy.write_text(json.dumps({"gpus": [legacy], "storage": ["keep-media"]}))
    compose.write_text(
        json.dumps(
            {
                "name": "mediahub-platform",
                "services": {
                    "core": {
                        "devices": [p + ":" + p + ":rw" for p in legacy["devices"]]
                        + ["/dev/net/tun:/dev/net/tun"],
                        "volumes": ["/media:/media:ro"],
                    },
                    "proxy": {"image": "unchanged"},
                },
            }
        )
    )
    before = {p: p.read_bytes() for p in [inventory, policy, compose]}
    original_lstat = Path.lstat

    def root_metadata(path):
        meta = original_lstat(path)
        if path in before:
            return SimpleNamespace(st_mode=0o100600, st_uid=10001 if path == policy else 0)
        return meta

    monkeypatch.setattr(Path, "lstat", root_metadata)
    monkeypatch.setattr(gpu_setup, "read_inventory", lambda _: [legacy])
    monkeypatch.setattr(gpu_setup, "validate_devices", lambda grants: None)
    monkeypatch.setattr(gpu_setup, "compose_gpu", lambda value, grants: value)
    monkeypatch.setattr(gpu_setup.os, "fchown", lambda *args: None, raising=False)
    monkeypatch.setattr(gpu_setup.os, "fchmod", lambda *args: None, raising=False)
    gpu_setup.repair_video_access(tmp_path, inventory)
    assert json.loads(inventory.read_text()) == [NVIDIA]
    assert json.loads(policy.read_text()) == {"gpus": [NVIDIA], "storage": ["keep-media"]}
    result = json.loads(compose.read_text())
    assert result["services"]["proxy"] == {"image": "unchanged"}
    assert result["services"]["core"]["volumes"] == ["/media:/media:ro"]
    assert "/dev/net/tun:/dev/net/tun" in result["services"]["core"]["devices"]
    assert not any("nvidia-cap" in p for p in result["services"]["core"]["devices"])
    for path, content in before.items():
        backups = list(path.parent.glob(path.name + ".before-video-repair-*"))
        assert len(backups) == 1 and backups[0].read_bytes() == content


@pytest.mark.parametrize(
    "grant,encoder",
    [(NVIDIA, "h264_nvenc"), (INTEL, "h264_qsv"), (INTEL | {"vendor": "amd"}, "h264_vaapi")],
)
def test_smoke_test_uses_selected_gpu_without_media_network_or_cpu_fallback(
    monkeypatch, grant, encoder
):
    monkeypatch.setattr(
        gpu_setup, "Path", lambda _: SimpleNamespace(stat=lambda: SimpleNamespace(st_gid=104))
    )
    command = gpu_setup.smoke_command(grant, "sha256:" + "a" * 64, "test-token")
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "10001:1000"
    assert command[command.index("-c:v") + 1] == encoder
    assert "--privileged" not in command
    assert "--read-only" in command
    temporary = [
        command[index + 1].split(":")[0]
        for index, value in enumerate(command)
        if value == "--tmpfs"
    ]
    assert temporary == ["/tmp", "/config", "/cache"]
    assert "--volume" not in command and "-v" not in command and "--mount" not in command
    assert command[command.index("-i") + 1].startswith("testsrc2=")
    assert command[-2:] == ["null", "-"]
    for device in grant["devices"]:
        assert device + ":" + device + ":rw" in command
    if grant["vendor"] == "nvidia":
        assert command[command.index("--gpus") + 1] == "device=" + grant["uuid"]


@pytest.mark.parametrize("success,own_leftover", [(True, True), (False, True), (False, False)])
def test_doctor_requires_actual_encode_success_and_cleans_only_owned_test_container(
    tmp_path, monkeypatch, success, own_leftover
):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent/container-apps.json").write_text(json.dumps({"gpus": [NVIDIA]}))
    (tmp_path / "compose.json").write_text(
        json.dumps({"name": "mediahub-platform", "services": {"core": {}}})
    )
    calls = []
    monkeypatch.setattr(gpu_setup, "validate_devices", lambda _: None)
    monkeypatch.setattr(gpu_setup.uuid, "uuid4", lambda: SimpleNamespace(hex="unique-token"))
    monkeypatch.setattr(
        gpu_setup,
        "smoke_command",
        lambda grant, image, token: [
            "docker",
            "run",
            "--name",
            "mediahub-gpu-test-" + token,
            image,
            "h264_nvenc",
        ],
    )

    def run(*args):
        calls.append(args)
        if args[:2] == ("docker", "compose"):
            return "a" * 64
        if args[:2] == ("docker", "inspect"):
            return json.dumps(
                {"Devices": [{"PathOnHost": d, "PathInContainer": d} for d in NVIDIA["devices"]]}
            )
        if args[:2] == ("docker", "info"):
            return json.dumps({"Runtimes": {"nvidia": {}}})
        if args[0] == "nvidia-smi":
            return NVIDIA["uuid"]
        if args[:3] == ("docker", "image", "inspect"):
            return "sha256:" + "b" * 64
        return ""

    def execute(args, **kwargs):
        calls.append(tuple(args))
        if args[:2] == ["docker", "run"]:
            return SimpleNamespace(
                returncode=0 if success else 1, stdout="", stderr="Synthetic GPU failure"
            )
        if args[:2] == ["docker", "inspect"]:
            return SimpleNamespace(
                returncode=0, stdout="unique-token" if own_leftover else "foreign-token"
            )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gpu_setup, "run", run)
    monkeypatch.setattr(gpu_setup.subprocess, "run", execute)
    if success:
        gpu_setup.verify_installation(tmp_path, [NVIDIA])
    else:
        with pytest.raises(ValueError, match="GPU encode test failed"):
            gpu_setup.verify_installation(tmp_path, [NVIDIA])
    assert (("docker", "rm", "-f", "mediahub-gpu-test-unique-token") in calls) is own_leftover
    assert any(
        call[:2] == ("docker", "exec") and "--privileged" not in call and "--user" not in call
        for call in calls
    )


def test_existing_policy_merge_preserves_volumes_and_original_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "fchmod", lambda *args: None, raising=False)
    monkeypatch.setattr(os, "fchown", lambda *args: None, raising=False)
    (tmp_path / "agent").mkdir()
    policy = {"hostId": "local", "storage": {"movies": {"path": "/media/movies"}}}
    compose = {
        "name": "mediahub-platform",
        "services": {
            "core": {
                "volumes": ["/media:/media:ro"],
                "environment": {"MEDIAHUB_BASE_URL": "https://synthetic.invalid"},
            }
        },
    }
    (tmp_path / "agent/container-apps.json").write_text(json.dumps(policy))
    (tmp_path / "compose.json").write_text(json.dumps(compose))
    monkeypatch.setattr(gpu_setup, "compose_gpu", lambda doc, grants: doc)
    gpu_setup.apply_existing(tmp_path, [INTEL])
    gpu_setup.apply_existing(tmp_path, [INTEL])
    assert json.loads((tmp_path / "compose.json").read_text()) == compose
    merged = json.loads((tmp_path / "agent/container-apps.json").read_text())
    assert merged == policy | {"gpus": [INTEL]}
    assert json.loads((tmp_path / "agent/container-apps.json.before-gpu").read_text()) == policy


def existing_tool(monkeypatch):
    monkeypatch.setitem(sys.modules, "proxmox_gpu", proxmox_gpu)
    source = Path(__file__).resolve().parents[1] / "scripts/setup-existing-gpu.py"
    spec = importlib.util.spec_from_file_location("existing_gpu", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0, raising=False)
    return module


def test_existing_wizard_refuses_unsupported_core_before_shutdown(tmp_path, monkeypatch):
    import subprocess

    tool = existing_tool(monkeypatch)
    monkeypatch.setattr(
        tool, "Path", lambda value: tmp_path if value == "/etc/pve" else Path(value)
    )
    calls = []
    monkeypatch.setattr(tool, "run", lambda *args: calls.append(args) or "status: running")

    def old_core(*args):
        raise subprocess.CalledProcessError(1, ["unsupported-core"])

    monkeypatch.setattr(tool, "guest", old_core)
    monkeypatch.setattr(sys, "argv", ["setup-existing-gpu.py", "--ctid", "107", "--yes"])
    with pytest.raises(ValueError, match="update MediaHub"):
        tool.main()
    assert calls == [("pct", "status", "107")]


@pytest.mark.parametrize("test_only", [False, True])
def test_existing_wizard_orders_shutdown_prepare_restart_and_verify(
    tmp_path, monkeypatch, test_only
):
    tool = existing_tool(monkeypatch)
    (tmp_path / "lxc").mkdir()
    (tmp_path / "lxc/107.conf").write_text("unprivileged: 1\ndev0: path=/dev/net/tun\n")

    def mapped_path(value):
        if value == "/etc/pve":
            return tmp_path
        if value == "/etc/pve/lxc":
            return tmp_path / "lxc"
        if value == "/var/lib/mediahub-gpu":
            return tmp_path / "gpu"
        return Path(value)

    monkeypatch.setattr(tool, "Path", mapped_path)
    monkeypatch.setattr(tool, "discover", lambda: [INTEL])
    calls = []
    state = "running"

    def run(*args):
        nonlocal state
        calls.append(args)
        if args[:2] == ("pct", "status"):
            return "status: " + state
        if args[:2] == ("pct", "shutdown"):
            state = "stopped"
        if args[:2] == ("pct", "start"):
            state = "running"
        return ""

    monkeypatch.setattr(tool, "run", run)
    monkeypatch.setattr(tool, "guest", lambda *args: calls.append(tuple(map(str, args))))
    monkeypatch.setattr(tool, "configure", lambda *args: calls.append(("configure", *args)))
    argv = ["setup-existing-gpu.py", "--ctid", "107", "--gpu", INTEL["id"], "--yes"]
    if test_only:
        argv += ["--test-only"]
    monkeypatch.setattr(sys, "argv", argv)
    tool.main()
    verified = next(i for i, call in enumerate(calls) if "--test-only" in call)
    if test_only:
        assert not any(
            call[:2] in {("pct", "shutdown"), ("pct", "start")} or call[0] == "configure"
            for call in calls
        )
        assert not any("up" in call for call in calls)
    else:
        stopped = next(i for i, call in enumerate(calls) if call[:2] == ("pct", "shutdown"))
        configured = next(i for i, call in enumerate(calls) if call[0] == "configure")
        started = next(i for i, call in enumerate(calls) if call[:2] == ("pct", "start"))
        prepared = next(
            i for i, call in enumerate(calls) if "--inventory" in call and "--test-only" not in call
        )
        recreated = next(i for i, call in enumerate(calls) if "up" in call)
        assert stopped < configured < started < prepared < recreated < verified
