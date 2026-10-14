import subprocess
from types import SimpleNamespace

import pytest
from test_gpu_installation import NVIDIA

from scripts import proxmox_gpu as gpu


@pytest.fixture
def driver_host(tmp_path, monkeypatch):
    system = tmp_path / "os-release"
    system.write_text('ID=debian\nVERSION_CODENAME="trixie"\n')
    actual_path = gpu.Path
    monkeypatch.setattr(gpu, "Path", lambda p: system if p == "/etc/os-release" else actual_path(p))
    state = {"installed": False, "working": False, "driver": "", "candidate": "550.163.01-2"}
    calls = []
    device = {"vendor": "nvidia", "pci": "0000:0d:00.0", "name": "RTX 3070 Ti", "driver": ""}
    monkeypatch.setattr(gpu, "host_gpu_inventory", lambda: [device | {"driver": state["driver"]}])
    monkeypatch.setattr(gpu, "discover", lambda: [NVIDIA] if state["installed"] else [])
    monkeypatch.setattr(gpu, "host_gpu_ready", lambda device, grants: bool(grants))
    monkeypatch.setattr(gpu, "nvidia_driver_ready", lambda: state["installed"])
    monkeypatch.setattr(gpu.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(gpu, "package_candidate", lambda _: state["candidate"])

    def run(*args):
        calls.append(args)
        if args[:2] == ("uname", "-r"):
            return "6.14.11-9-pve"
        if args[0] == "nvidia-smi":
            if not state["working"]:
                raise subprocess.CalledProcessError(1, args)
            return "550.163.01" if "driver_version" in args[1] else NVIDIA["uuid"]
        if args[0] == "apt-get":
            return (
                "Inst nvidia-driver (550.163.01-2)"
                if not state["working"]
                else "Inst libnvcuvid1 (550.163.01-2)"
            )
        return ""

    def execute(args, **kwargs):
        calls.append(tuple(args))
        if args[:2] == ["apt-get", "install"]:
            state["installed"] = True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gpu, "run", run)
    monkeypatch.setattr(gpu.subprocess, "run", execute)
    return state, calls


def test_working_driver_is_reused_without_package_changes(driver_host):
    state, calls = driver_host
    state["installed"] = True
    gpu.prepare_host_drivers()
    assert calls == []


def test_nvidia_installs_headers_dkms_video_libraries_and_loads_uvm(driver_host):
    state, calls = driver_host
    gpu.prepare_host_drivers(yes=True)
    install = next(call for call in calls if call[:2] == ("apt-get", "install"))
    for package in (
        "proxmox-headers-6.14.11-9-pve",
        "dkms",
        "nvidia-driver",
        "nvidia-kernel-dkms",
        "libnvcuvid1",
        "libnvidia-encode1",
    ):
        assert package in install
    assert "--no-remove" in install
    assert ("modprobe", "nvidia_uvm") in calls
    assert not any("reboot" in call or "rmmod" in call for call in calls)


def test_host_confirmation_is_separate_from_lxc_confirmation(driver_host, monkeypatch):
    state, calls = driver_host
    monkeypatch.setattr("builtins.input", lambda _: "")
    with pytest.raises(ValueError, match="cancelled"):
        gpu.prepare_host_drivers()
    assert calls == []


def test_missing_video_libraries_are_pinned_to_working_driver(driver_host):
    state, calls = driver_host
    state["working"] = True
    gpu.prepare_host_drivers(yes=True)
    install = next(call for call in calls if call[:2] == ("apt-get", "install"))
    assert "libnvcuvid1=550.163.01-2" in install
    assert "libnvidia-encode1=550.163.01-2" in install
    assert "nvidia-driver" not in install and "nvidia-kernel-dkms" not in install


def test_mismatching_libraries_never_replace_working_driver(driver_host):
    state, calls = driver_host
    state.update(working=True, candidate="570.1.0-1")
    with pytest.raises(ValueError, match="matching the running"):
        gpu.prepare_host_drivers(yes=True)
    assert not any(call[:2] == ("apt-get", "install") for call in calls)


def test_nouveau_requires_operator_reboot_without_touching_guests(driver_host):
    state, calls = driver_host
    state["driver"] = "nouveau"
    with pytest.raises(ValueError, match="Reboot Proxmox"):
        gpu.prepare_host_drivers(yes=True)
    assert not any(call[0] in {"pct", "reboot", "modprobe", "rmmod"} for call in calls)


def test_vfio_assignment_is_preserved(driver_host):
    state, calls = driver_host
    state["driver"] = "vfio-pci"
    with pytest.raises(ValueError, match="VFIO"):
        gpu.prepare_host_drivers(yes=True)
    assert calls == []


def test_gpu_repository_requires_separate_confirmation(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    with pytest.raises(ValueError, match="not enabled"):
        gpu.enable_driver_repository("trixie", False)


def test_gpu_repository_only_adds_official_signed_components(tmp_path, monkeypatch):
    keyring = tmp_path / "debian-archive-keyring.gpg"
    keyring.write_bytes(b"test-keyring")
    source = tmp_path / "mediahub-gpu-drivers.sources"
    real_path = gpu.Path
    monkeypatch.setattr(
        gpu,
        "Path",
        lambda path: (
            keyring
            if path.endswith(".gpg")
            else source
            if path.endswith(".sources")
            else real_path(path)
        ),
    )
    calls = []
    monkeypatch.setattr(gpu.subprocess, "run", lambda args, **kwargs: calls.append(args))
    gpu.enable_driver_repository("trixie", True)
    assert "https://deb.debian.org/debian" in source.read_text()
    assert "Components: contrib non-free non-free-firmware" in source.read_text()
    assert "Suites: trixie" in source.read_text()
    assert "Signed-By:" in source.read_text()
    assert calls == [["apt-get", "update"]]
    source.write_text("existing unrelated source")
    with pytest.raises(ValueError, match="Refusing to replace"):
        gpu.enable_driver_repository("trixie", True)
    assert source.read_text() == "existing unrelated source"


@pytest.mark.parametrize(
    "vendor,firmware,module",
    [("intel", "firmware-intel-graphics", "i915"), ("amd", "firmware-amd-graphics", "amdgpu")],
)
@pytest.mark.parametrize("proxmox_firmware", [True, False])
def test_intel_amd_reuse_proxmox_firmware_or_install_missing_firmware(
    driver_host, monkeypatch, vendor, firmware, module, proxmox_firmware
):
    state, calls = driver_host
    monkeypatch.setattr(
        gpu,
        "host_gpu_inventory",
        lambda: [{"vendor": vendor, "pci": "0000:00:02.0", "driver": "", "name": vendor}],
    )
    original = gpu.run

    def run(*args):
        if args[0] == "dpkg-query":
            return "installed" if proxmox_firmware else "not-installed"
        return original(*args)

    def execute(args, **kwargs):
        calls.append(tuple(args))
        if args[0] == "modprobe":
            state["installed"] = True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(gpu, "run", run)
    monkeypatch.setattr(gpu.subprocess, "run", execute)
    gpu.prepare_host_drivers(yes=True)
    installs = [call for call in calls if call[:2] == ("apt-get", "install")]
    assert (not installs) if proxmox_firmware else firmware in installs[0]
    assert ("modprobe", module) in calls


@pytest.mark.parametrize("plan", ["Remv proxmox-ve [9.1]", "Inst nvidia-kernel-dkms (570)"])
def test_apt_plan_cannot_remove_packages_or_replace_working_kernel_driver(monkeypatch, plan):
    calls = []
    monkeypatch.setattr(gpu, "run", lambda *args: plan)
    monkeypatch.setattr(gpu.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError):
        gpu.install_host_packages(["libnvcuvid1=550.163.01-2"], preserve_driver=True)
    assert calls == []
