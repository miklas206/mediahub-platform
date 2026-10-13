"""List GPUs and share one with a stopped, unprivileged MediaHub LXC."""

import argparse
import csv
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def nvidia_minor(uuid, bus):
    """Resolve the device node from kernel evidence, never from the GPU index."""
    match = re.fullmatch(r"([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])", bus)
    if not match:
        return None
    domain, slot, device, function = match.groups()
    pci = f"{int(domain, 16):04x}:{slot.lower()}:{device.lower()}.{function}"
    try:
        information = (Path("/proc/driver/nvidia/gpus") / pci / "information").read_text()
    except OSError:
        return None
    kernel_uuid = re.search(r"^GPU UUID:\s*(GPU-[a-fA-F0-9-]+)\s*$", information, re.M)
    minor = re.search(r"^Device Minor:\s*([0-9]+)\s*$", information, re.M)
    if not kernel_uuid or kernel_uuid.group(1) != uuid or not minor:
        return None
    return minor.group(1)


def discover():
    gpus = []
    for render in sorted(Path("/sys/class/drm").glob("renderD*")):
        device = render / "device"
        try:
            vendor = {"0x8086": "intel", "0x1002": "amd"}.get(
                (device / "vendor").read_text().strip()
            )
        except OSError:
            continue
        node = Path("/dev/dri") / render.name
        if vendor and node.exists() and stat.S_ISCHR(node.stat().st_mode):
            pci = device.resolve().name
            name = run("lspci", "-s", pci) if shutil.which("lspci") else pci
            gpus.append(
                {
                    "id": vendor + "-" + pci,
                    "name": name[:120],
                    "vendor": vendor,
                    "devices": [str(node)],
                }
            )
    if shutil.which("nvidia-smi"):
        try:
            rows = run(
                "nvidia-smi", "--query-gpu=uuid,name,pci.bus_id", "--format=csv,noheader,nounits"
            )
        except subprocess.CalledProcessError:
            print(
                "NVIDIA driver is not ready. Configure the Proxmox host driver first; no driver will be replaced.",
                file=sys.stderr,
            )
            rows = ""
        shared = [
            Path("/dev/nvidiactl"),
            Path("/dev/nvidia-uvm"),
            Path("/dev/nvidia-uvm-tools"),
            Path("/dev/nvidia-modeset"),
        ]
        shared += sorted(Path("/dev/nvidia-caps").glob("nvidia-cap*"))
        for row in csv.reader(rows.splitlines(), skipinitialspace=True):
            if len(row) != 3:
                continue
            uuid, name, bus = [value.strip() for value in row]
            if not re.fullmatch(r"GPU-[a-fA-F0-9-]{8,60}", uuid):
                continue
            minor = nvidia_minor(uuid, bus)
            if minor is None:
                print(
                    "NVIDIA device mapping could not be verified against the host kernel.",
                    file=sys.stderr,
                )
                continue
            nodes = [Path("/dev/nvidia" + minor)] + [p for p in shared if p.exists()]
            if (
                Path("/dev/nvidia-uvm") not in nodes
                or Path("/dev/nvidiactl") not in nodes
                or not all(stat.S_ISCHR(p.stat().st_mode) for p in nodes)
            ):
                print(
                    "NVIDIA UVM is unavailable. Load nvidia_uvm on Proxmox before selecting this GPU.",
                    file=sys.stderr,
                )
                continue
            gpus.append(
                {
                    "id": uuid,
                    "name": name[:120],
                    "vendor": "nvidia",
                    "uuid": uuid,
                    "devices": list(map(str, nodes)),
                }
            )
    return gpus


def stage_nvidia(directory):
    """Stage matching userspace libraries only; do not alter the host driver."""
    libraries = {}
    for line in run("ldconfig", "-p").splitlines():
        match = re.search(r"^\s*(lib(?:nvidia-[\w-]+|cuda|nvcuvid)\.so[\w.-]*) .* => (/\S+)$", line)
        if match:
            alias, source = match.groups()
            path = Path(source).resolve(strict=True)
            if (
                not any(parent in path.parents for parent in (Path("/usr/lib"), Path("/lib")))
                or not path.is_file()
            ):
                raise ValueError("NVIDIA library is outside the trusted library directories")
            # Only host amd64 libraries; skip i386 entries with identical SONAMEs.
            if "x86-64" in line:
                libraries[alias] = path
    for required in (
        "libcuda.so.1",
        "libnvidia-ml.so.1",
        "libnvidia-encode.so.1",
        "libnvcuvid.so.1",
    ):
        if required not in libraries:
            raise ValueError(
                "Install matching NVIDIA userspace libraries on Proxmox first: " + required
            )
    directory.mkdir(mode=0o755, parents=True, exist_ok=False)
    for alias, path in libraries.items():
        target = directory / path.name
        if not target.exists():
            shutil.copyfile(path, target)
            target.chmod(0o644)
        if alias != path.name:
            (directory / alias).symlink_to(path.name)
    smi = Path(shutil.which("nvidia-smi")).resolve(strict=True)
    shutil.copyfile(smi, directory / "nvidia-smi")
    (directory / "nvidia-smi").chmod(0o755)


def configure(ctid, gpu, inventory):
    if not re.fullmatch(r"[1-9][0-9]{2,8}", ctid):
        raise ValueError("Invalid container ID")
    if inventory.exists() or inventory.is_symlink() or not inventory.parent.is_dir():
        raise ValueError("Choose a new inventory file in an existing directory")
    if run("pct", "status", ctid) != "status: stopped":
        raise ValueError("Stop the selected MediaHub LXC before sharing a GPU")
    config_path = Path("/etc/pve/lxc") / (ctid + ".conf")
    original = config_path.read_text()
    if not re.search(r"^unprivileged:\s*1\s*$", original, re.M):
        raise ValueError("GPU guide requires an unprivileged LXC")
    if "mediahub-nvidia" in original:
        raise ValueError(
            "GPU libraries are already configured; inspect existing bindings before changing the GPU"
        )
    used = {int(n) for n in re.findall(r"^dev([0-9]+):", original, re.M)}
    free = [n for n in range(256) if n not in used]
    if len(free) < len(gpu["devices"]):
        raise ValueError("Not enough free device mapping slots")
    if any(p in original for p in gpu["devices"]):
        raise ValueError("Selected GPU already has device mappings; inspect them before retrying")
    base = Path("/var/lib/mediahub-gpu") / ctid
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = base / "before-gpu.conf"
    if not backup.exists():
        backup.write_text(original)
        backup.chmod(0o600)
    bindings = []
    if gpu["vendor"] == "nvidia":
        # A fresh directory also prevents silently reusing stale host driver libraries.
        from tempfile import mkdtemp

        stage = Path(mkdtemp(prefix="nvidia-", dir=base))
        stage.rmdir()
        stage_nvidia(stage)
        modules = Path("/etc/modules-load.d/mediahub-nvidia.conf")
        if not modules.exists():
            fd = os.open(modules, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "w") as output:
                output.write("nvidia_uvm\n")
        # Allow unprivileged guest root to traverse the staged read-only libraries.
        base.chmod(0o755)
        bindings = [
            f"lxc.mount.entry: {stage} usr/local/lib/mediahub-nvidia none bind,ro,create=dir 0 0",
            f"lxc.mount.entry: {stage}/nvidia-smi usr/bin/nvidia-smi none bind,ro,create=file 0 0",
            "lxc.mount.entry: /proc/driver/nvidia proc/driver/nvidia none bind,ro,create=dir 0 0",
        ]
    if config_path.read_text() != original or run("pct", "status", ctid) != "status: stopped":
        raise ValueError("Container changed during GPU preparation")
    args = ["pct", "set", ctid]
    for slot, device in zip(free, gpu["devices"]):
        if not stat.S_ISCHR(Path(device).stat().st_mode):
            raise ValueError("GPU node is not a character device")
        args += ["--dev" + str(slot), f"path={device},uid=10001,gid=1000,mode=0660"]
    run(*args)
    if bindings:
        with config_path.open("a") as output:
            output.write("\n" + "\n".join(bindings) + "\n")
    fd = os.open(inventory, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump([gpu], output)
    print(
        "GPU shared. Start the LXC and prepare its Docker GPU runtime before installing Jellyfin."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--check", action="store_true", help="Validate the choice without changing a container"
    )
    parser.add_argument("--gpu", help="Exact GPU ID from --list; never a device path")
    parser.add_argument("--ctid")
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path("/etc/pve").is_dir():
        raise ValueError("Run from the Proxmox node shell as root")
    gpus = discover()
    if args.list:
        for gpu in gpus:
            print(gpu["id"] + "  " + gpu["name"])
        if not gpus:
            print("No supported, driver-ready GPU found.")
        return
    selected = next((g for g in gpus if g["id"] == args.gpu), None)
    if selected and args.check:
        print("Selected: " + selected["name"])
        return
    if not selected or not args.ctid or not args.inventory:
        raise ValueError("Choose an available GPU ID, CTID and new inventory file")
    configure(args.ctid, selected, args.inventory)


if __name__ == "__main__":
    main()
