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
    return subprocess.check_output(
        list(map(str, args)), text=True, env={**os.environ, "LC_ALL": "C"}
    ).strip()


def host_gpu_inventory():
    result = []
    for device in sorted(Path("/sys/bus/pci/devices").glob("*")):
        try:
            if not (device / "class").read_text().strip().startswith("0x03"):
                continue
            vendor = {"0x10de": "nvidia", "0x8086": "intel", "0x1002": "amd"}.get(
                (device / "vendor").read_text().strip()
            )
            if not vendor:
                continue
            driver = (device / "driver").resolve().name if (device / "driver").exists() else ""
            name = run("lspci", "-s", device.name) if shutil.which("lspci") else device.name
            result.append({"pci": device.name, "vendor": vendor, "driver": driver, "name": name})
        except OSError:
            continue
    return result


def package_candidate(package):
    output = run("apt-cache", "policy", package)
    candidate = re.search(r"^\s*Candidate:\s*(\S+)", output, re.M)
    return candidate.group(1) if candidate and candidate.group(1) != "(none)" else None


def host_gpu_ready(gpu, grants):
    if gpu["vendor"] != "nvidia":
        return any(g["vendor"] == gpu["vendor"] and g["id"].endswith(gpu["pci"]) for g in grants)
    try:
        information = (Path("/proc/driver/nvidia/gpus") / gpu["pci"] / "information").read_text()
    except OSError:
        return False
    match = re.search(r"^GPU UUID:\s*(GPU-[a-fA-F0-9-]+)\s*$", information, re.M)
    return bool(
        match and any(g["vendor"] == "nvidia" and g["uuid"] == match.group(1) for g in grants)
    )


def nvidia_driver_ready():
    if not shutil.which("nvidia-smi"):
        return False
    try:
        if not run("nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"):
            return False
        libraries = run("ldconfig", "-p")
        return all(
            name in libraries
            for name in (
                "libcuda.so.1",
                "libnvidia-ml.so.1",
                "libnvidia-encode.so.1",
                "libnvcuvid.so.1",
            )
        )
    except subprocess.CalledProcessError:
        return False


def install_host_packages(packages, preserve_driver=False):
    packages = sorted(set(packages))
    if not packages:
        return
    # Simulate first and prohibit removal even when dependency resolution changes.
    plan = run("apt-get", "--simulate", "--no-remove", "install", *packages)
    if re.search(r"^Remv\s", plan, re.M):
        raise ValueError(
            "Driver installation would remove existing packages; inspect the APT plan first"
        )
    if preserve_driver and re.search(
        r"^Inst (?:nvidia-driver|nvidia-(?:open-)?kernel-dkms)\b", plan, re.M
    ):
        raise ValueError(
            "Matching video libraries would replace the working NVIDIA driver; inspect APT dependencies first"
        )
    print(plan, flush=True)
    subprocess.run(
        ["apt-get", "install", "--no-remove", "-y", *packages],
        check=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )


def enable_driver_repository(codename, yes):
    if codename not in {"bookworm", "trixie"}:
        raise ValueError("Automatic GPU packages support Debian bookworm/trixie Proxmox hosts")
    print(
        "GPU packages are missing from APT. Add official Debian contrib/non-free/non-free-firmware components for "
        + codename
        + ". Existing repositories are preserved.",
        flush=True,
    )
    if (
        not yes
        and input("Type REPOSITORY to enable the GPU package repository: ").strip() != "REPOSITORY"
    ):
        raise ValueError("Driver package repository was not enabled; no GPU was shared")
    keyring = Path("/usr/share/keyrings/debian-archive-keyring.gpg")
    if not keyring.is_file():
        raise ValueError("Debian archive signing keyring is missing")
    path = Path("/etc/apt/sources.list.d/mediahub-gpu-drivers.sources")
    content = f"Types: deb\nURIs: https://deb.debian.org/debian\nSuites: {codename}\nComponents: contrib non-free non-free-firmware\nSigned-By: {keyring}\n"
    if path.is_symlink() or (path.exists() and path.read_text() != content):
        raise ValueError("Refusing to replace an existing GPU package source")
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as output:
            output.write(content)
    subprocess.run(["apt-get", "update"], check=True)


def prepare_host_drivers(yes=False):
    """Explicit host setup; never unload a driver, rebind VFIO or reboot a node."""
    devices = host_gpu_inventory()
    if not devices:
        print(
            "No NVIDIA, Intel or AMD display GPU detected. CPU-only installation remains available."
        )
        return
    eligible = [gpu for gpu in devices if gpu["driver"] != "vfio-pci"]
    for gpu in devices:
        print(gpu["name"] + " [" + (gpu["driver"] or "no driver") + "]", flush=True)
    if not eligible:
        raise ValueError(
            "All GPUs are assigned to VFIO/VMs. Host driver installation will not reassign them"
        )
    ready = discover()
    pending = [gpu for gpu in eligible if not host_gpu_ready(gpu, ready)]
    nvidia = any(g["vendor"] == "nvidia" for g in eligible)
    if not pending and (not nvidia or nvidia_driver_ready()):
        print(
            "GPU host drivers, video libraries and devices are already ready. Existing drivers were preserved."
        )
        return
    if any(g["vendor"] == "nvidia" and g["driver"] == "vfio-pci" for g in devices) and nvidia:
        raise ValueError(
            "Mixed NVIDIA host/VFIO GPUs require a manual driver plan; VM assignments are preserved"
        )
    print(
        "Driver setup may install kernel headers, DKMS, video libraries and firmware. It may require a Proxmox reboot affecting all guests. No automatic reboot, driver unload or guest stop will occur.",
        flush=True,
    )
    if (
        not yes
        and input("Type DRIVERS to install required GPU host packages: ").strip() != "DRIVERS"
    ):
        raise ValueError("Host driver installation cancelled; no LXC changes were made")
    system = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            system[key] = value.strip('"')
    codename = system.get("VERSION_CODENAME")
    if system.get("ID") != "debian" or codename not in {"bookworm", "trixie"}:
        raise ValueError(
            "Automatic driver setup supports Debian-based Proxmox bookworm/trixie hosts"
        )
    subprocess.run(["apt-get", "update"], check=True)
    packages = []
    preserve_driver = False
    if nvidia and not nvidia_driver_ready():
        # Do not let APT replace an already working externally installed driver.
        working = False
        if shutil.which("nvidia-smi"):
            try:
                working = bool(run("nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"))
            except subprocess.CalledProcessError:
                pass
        if working:
            versions = set(
                run(
                    "nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"
                ).splitlines()
            )
            if len(versions) != 1:
                raise ValueError("Cannot determine one working NVIDIA driver version")
            version = versions.pop()
            preserve_driver = True
            if any(not package_candidate(p) for p in ("libnvcuvid1", "libnvidia-encode1")):
                enable_driver_repository(codename, yes)
                subprocess.run(["apt-get", "update"], check=True)
            for package in ("libnvcuvid1", "libnvidia-encode1"):
                candidate = package_candidate(package)
                if not candidate or not candidate.split(":")[-1].startswith(version + "-"):
                    raise ValueError(
                        "APT has no video libraries matching the running NVIDIA driver "
                        + version
                        + "; the working driver was preserved"
                    )
                packages.append(package + "=" + candidate)
        else:
            kernel = run("uname", "-r")
            if not re.fullmatch(r"[a-zA-Z0-9_.+-]+-pve", kernel):
                raise ValueError("Expected a supported Proxmox kernel")
            headers = next(
                (
                    p
                    for p in ("proxmox-headers-" + kernel, "pve-headers-" + kernel)
                    if package_candidate(p)
                ),
                None,
            )
            if not headers:
                raise ValueError(
                    "Headers for the running Proxmox kernel are unavailable. Update the host kernel/repositories and reboot before continuing"
                )
            packages += [
                headers,
                "dkms",
                "build-essential",
                "nvidia-driver",
                "nvidia-kernel-dkms",
                "libnvcuvid1",
                "libnvidia-encode1",
            ]
    if any(g["vendor"] in {"intel", "amd"} for g in pending):
        # Proxmox normally supplies graphics firmware through pve-firmware;
        # avoid conflicting Debian firmware packages when it is installed.
        try:
            bundled = (
                run("dpkg-query", "-W", "-f=${db:Status-Status}", "pve-firmware") == "installed"
            )
        except subprocess.CalledProcessError:
            bundled = False
        if not bundled:
            if any(g["vendor"] == "amd" for g in pending):
                packages += ["firmware-amd-graphics"]
            if any(g["vendor"] == "intel" for g in pending):
                packages += [
                    "firmware-intel-graphics" if codename == "trixie" else "firmware-misc-nonfree"
                ]
    if any(not package_candidate(p.split("=")[0]) for p in packages):
        enable_driver_repository(codename, yes)
    missing = [p for p in packages if not package_candidate(p.split("=")[0])]
    if missing:
        raise ValueError("Required GPU packages are unavailable: " + ", ".join(missing))
    install_host_packages(packages, preserve_driver=preserve_driver)
    if nvidia and any(
        g["driver"] == "nouveau" or g["driver"] == "nvidia" and "nvidia-driver" in packages
        for g in pending
    ):
        raise ValueError(
            "GPU host packages installed. Reboot Proxmox at a suitable time, then rerun this guide. Running driver modules were not replaced"
        )
    for vendor in sorted({g["vendor"] for g in pending}):
        module = {"nvidia": "nvidia_uvm", "intel": "i915", "amd": "amdgpu"}[vendor]
        subprocess.run(["modprobe", module], check=False)
    now = discover()
    if (nvidia and not nvidia_driver_ready()) or any(
        not host_gpu_ready(gpu, now) for gpu in pending
    ):
        raise ValueError(
            "Driver packages installed but GPU is not ready. Check DKMS/Secure Boot or kernel support and reboot Proxmox when appropriate; no LXC changes were made"
        )
    print("GPU host drivers and devices are ready. Continue with LXC sharing.")


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
        ]
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
        "--prepare-drivers",
        action="store_true",
        help="Install missing host drivers/firmware with confirmation",
    )
    parser.add_argument(
        "--drivers-yes",
        action="store_true",
        help="Explicitly authorize host GPU packages and official Debian GPU sources without prompts",
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate the choice without changing a container"
    )
    parser.add_argument("--gpu", help="Exact GPU ID from --list; never a device path")
    parser.add_argument("--ctid")
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path("/etc/pve").is_dir():
        raise ValueError("Run from the Proxmox node shell as root")
    if args.prepare_drivers:
        prepare_host_drivers(args.drivers_yes)
        return
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
