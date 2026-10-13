"""Operator-only GPU preparation for a Linux Docker guest. No kernel drivers installed."""

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def read_inventory(path):
    path = Path(path)
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
        raise ValueError(
            "GPU inventory must be a root-owned regular file without group/world write access"
        )
    grants = json.loads(path.read_text())
    if not isinstance(grants, list) or len(grants) > 16:
        raise ValueError("Invalid GPU inventory")
    ids = set()
    for gpu in grants:
        if not isinstance(gpu, dict) or set(gpu) - {"id", "name", "vendor", "devices", "uuid"}:
            raise ValueError("Invalid GPU grant")
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,80}", gpu.get("id", "")) or gpu["id"] in ids:
            raise ValueError("Invalid or duplicate GPU ID")
        ids.add(gpu["id"])
        if not isinstance(gpu.get("name"), str) or not 1 <= len(gpu["name"]) <= 120:
            raise ValueError("Invalid GPU name")
        vendor = gpu.get("vendor")
        if vendor not in {"intel", "amd", "nvidia"}:
            raise ValueError("Unsupported GPU vendor")
        pattern = (
            r"/dev/nvidia(?:[0-9]+|ctl|-uvm|-uvm-tools|-modeset)|/dev/nvidia-caps/nvidia-cap[0-9]+"
            if vendor == "nvidia"
            else r"/dev/dri/renderD[0-9]+"
        )
        devices = gpu.get("devices")
        if (
            not isinstance(devices, list)
            or not 1 <= len(devices) <= 16
            or any(not isinstance(p, str) or not re.fullmatch(pattern, p) for p in devices)
            or len(set(devices)) != len(devices)
        ):
            raise ValueError("Unsupported GPU devices")
        if vendor == "nvidia":
            if (
                not re.fullmatch(r"GPU-[a-fA-F0-9-]{8,60}", gpu.get("uuid", ""))
                or "/dev/nvidiactl" not in devices
                or not any(re.fullmatch(r"/dev/nvidia[0-9]+", p) for p in devices)
            ):
                raise ValueError("NVIDIA grant needs UUID, GPU and control devices")
        elif gpu.get("uuid"):
            raise ValueError("Unexpected NVIDIA UUID")
    return grants


def validate_devices(grants):
    for gpu in grants:
        for device in gpu["devices"]:
            if not stat.S_ISCHR(Path(device).stat().st_mode) or not os.access(
                device, os.R_OK | os.W_OK
            ):
                raise ValueError("GPU device is not accessible: " + device)


def compose_gpu(compose, grants):
    """Expose approved nodes to controllers for preflight; apps get separate grants."""
    devices = {p for gpu in grants for p in gpu["devices"]}
    groups = {str(Path(p).stat().st_gid) for p in devices}
    for name in ("core", "agent"):
        service = compose.get("services", {}).get(name)
        if service is None:
            continue
        current = service.setdefault("devices", [])
        for path in sorted(devices):
            mapping = path + ":" + path + ":rw"
            if mapping not in current:
                if any(
                    not isinstance(d, str)
                    or d.split(":")[0] == path
                    or len(d.split(":")) > 1
                    and d.split(":")[1] == path
                    for d in current
                ):
                    raise ValueError("Conflicting GPU device mapping")
                current.append(mapping)
        service["group_add"] = sorted(set(map(str, service.get("group_add", []))) | groups)
    return compose


def prepare(grants):
    validate_devices(grants)
    nvidia = [g for g in grants if g["vendor"] == "nvidia"]
    if not nvidia:
        return
    # The Proxmox helper binds matching host driver libraries, never a guest kernel module.
    library = Path("/usr/local/lib/mediahub-nvidia")
    if library.is_dir():
        Path("/etc/ld.so.conf.d/mediahub-nvidia.conf").write_text(str(library) + "\n")
        run("ldconfig")
    found = run("nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader").splitlines()
    if any(g["uuid"] not in found for g in nvidia):
        raise ValueError("Selected NVIDIA GPU is not available through the guest driver libraries")
    apt_env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    subprocess.run(["apt-get", "update"], check=True, env=apt_env)
    subprocess.run(
        ["apt-get", "install", "-y", "ca-certificates", "curl", "gnupg"], check=True, env=apt_env
    )
    keyring = "/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
    # Separate subprocesses avoid shell interpolation and retain checked HTTPS downloads.
    key = subprocess.check_output(
        ["curl", "-fsSL", "https://nvidia.github.io/libnvidia-container/gpgkey"]
    )
    subprocess.run(["gpg", "--batch", "--yes", "--dearmor", "-o", keyring], input=key, check=True)
    Path(keyring).chmod(0o644)
    repo = run(
        "curl",
        "-fsSL",
        "https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list",
    )
    repo = repo.replace("deb https://", f"deb [signed-by={keyring}] https://")
    Path("/etc/apt/sources.list.d/nvidia-container-toolkit.list").write_text(repo + "\n")
    subprocess.run(["apt-get", "update"], check=True, env=apt_env)
    subprocess.run(
        ["apt-get", "install", "-y", "nvidia-container-toolkit"], check=True, env=apt_env
    )
    run("nvidia-ctk", "runtime", "configure", "--runtime=docker")
    if Path("/usr/local/lib/mediahub-nvidia").is_dir():
        run("nvidia-ctk", "config", "--set", "nvidia-container-cli.no-cgroups", "--in-place")
    print("Restarting Docker to load the explicitly requested NVIDIA runtime.", flush=True)
    run("systemctl", "restart", "docker")
    info = json.loads(run("docker", "info", "--format", "{{json .}}"))
    if "nvidia" not in info.get("Runtimes", {}):
        raise ValueError("Docker NVIDIA runtime was not registered")


def apply_existing(root, grants):
    """Preserve the current deployment and merge explicit operator GPU grants."""
    root = root.resolve(strict=True)
    paths = [root / "agent/container-apps.json", root / "compose.json"]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Existing host policy/compose file is missing or is a symlink")
    policy, compose = [json.loads(path.read_text()) for path in paths]
    if compose.get("name") != "mediahub-platform" or "core" not in compose.get("services", {}):
        raise ValueError("This is not a MediaHub deployment")
    merged = {g["id"]: g for g in policy.get("gpus", [])}
    for grant in grants:
        if grant["id"] in merged and merged[grant["id"]] != grant:
            raise ValueError("Existing GPU grant differs; inspect it before replacing")
        merged[grant["id"]] = grant
    policy["gpus"] = list(merged.values())
    compose_gpu(compose, grants)
    for path, value in zip(paths, [policy, compose]):
        meta = path.stat()
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".gpu-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(value, output, indent=2)
                output.write("\n")
                os.fchmod(output.fileno(), stat.S_IMODE(meta.st_mode))
                os.fchown(output.fileno(), meta.st_uid, meta.st_gid)
                output.flush()
                os.fsync(output.fileno())
            backup = path.with_name(path.name + ".before-gpu")
            if not backup.exists():
                fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    output.write(path.read_text())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    print(
        f"GPU policy saved. Recreate Core/Agent with: docker compose -f {root}/compose.json up -d"
    )


def smoke_command(grant, image, token):
    """Synthetic encode only: no storage, LAN, credentials or app data attached."""
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        "mediahub-gpu-test-" + token,
        "--label",
        "org.mediahub.gpu.test=" + token,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--user",
        "10001:1000",
        "--pids-limit",
        "256",
        "--memory",
        "1g",
    ]
    for device in grant["devices"]:
        command += ["--device", device + ":" + device + ":rw"]
    for gid in sorted({str(Path(p).stat().st_gid) for p in grant["devices"]}):
        command += ["--group-add", gid]
    ffmpeg = ["-hide_banner", "-loglevel", "info"]
    if grant["vendor"] == "nvidia":
        command += [
            "--runtime",
            "nvidia",
            "--gpus",
            "device=" + grant["uuid"],
            "--env",
            "NVIDIA_VISIBLE_DEVICES=" + grant["uuid"],
            "--env",
            "NVIDIA_DRIVER_CAPABILITIES=compute,video,utility",
        ]
        encoder = "h264_nvenc"
    elif grant["vendor"] == "intel":
        ffmpeg += [
            "-init_hw_device",
            "qsv=hw,child_device=" + grant["devices"][0],
            "-filter_hw_device",
            "hw",
        ]
        encoder = "h264_qsv"
    else:
        ffmpeg += ["-vaapi_device", grant["devices"][0]]
        encoder = "h264_vaapi"
    ffmpeg += ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10"]
    if grant["vendor"] != "nvidia":
        ffmpeg += ["-vf", "format=nv12,hwupload=extra_hw_frames=16"]
    ffmpeg += ["-c:v", encoder, "-frames:v", "10", "-an", "-f", "null", "-"]
    return command + ["--entrypoint", "/usr/lib/jellyfin-ffmpeg/ffmpeg", image] + ffmpeg


def verify_installation(root, grants, gpu_id=None):
    """Check real controller access and hardware encode in a disposable container."""
    validate_devices(grants)
    choices = [g for g in grants if not gpu_id or g["id"] == gpu_id]
    if len(choices) != 1:
        raise ValueError("Choose one GPU ID from the prepared inventory for verification")
    grant = choices[0]
    root = root.resolve(strict=True)
    policy = json.loads((root / "agent/container-apps.json").read_text())
    if not any(
        all(g.get(key) == grant.get(key) for key in ("id", "vendor", "devices", "uuid"))
        for g in policy.get("gpus", [])
    ):
        raise ValueError("Selected GPU is not registered in MediaHub's host policy")
    compose = json.loads((root / "compose.json").read_text())
    if compose.get("name") != "mediahub-platform":
        raise ValueError("Not a MediaHub deployment")
    print("[1/4] GPU nodes and MediaHub policy: OK", flush=True)
    for role in ("core", "agent"):
        if role not in compose.get("services", {}):
            continue
        container = run("docker", "compose", "-f", root / "compose.json", "ps", "-q", role)
        if not re.fullmatch(r"[a-f0-9]{12,64}", container):
            raise ValueError(role + " is not running; recreate the MediaHub services first")
        host = json.loads(run("docker", "inspect", "--format", "{{json .HostConfig}}", container))
        approved = {(d["PathOnHost"], d["PathInContainer"]) for d in host.get("Devices") or []}
        if any((p, p) not in approved for p in grant["devices"]):
            raise ValueError(role + " is missing the approved GPU device mappings")
        code = (
            "import os,stat; paths="
            + repr(grant["devices"])
            + "; assert all(stat.S_ISCHR(os.stat(p).st_mode) and os.access(p,os.R_OK|os.W_OK) for p in paths), 'GPU permissions denied'"
        )
        # Default container user and supplementary groups, not a privileged exec.
        run("docker", "exec", container, "python", "-c", code)
    print("[2/4] Running MediaHub controllers can access GPU nodes: OK", flush=True)
    if grant["vendor"] == "nvidia":
        info = json.loads(run("docker", "info", "--format", "{{json .}}"))
        if "nvidia" not in info.get("Runtimes", {}):
            raise ValueError("Docker NVIDIA runtime is missing")
        if (
            grant["uuid"]
            not in run("nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader").splitlines()
        ):
            raise ValueError("The selected NVIDIA GPU cannot be queried inside the guest")
    print("[3/4] Guest GPU runtime: OK. Pulling the official Jellyfin test image...", flush=True)
    subprocess.run(["docker", "pull", "jellyfin/jellyfin:latest"], check=True)
    image = run("docker", "image", "inspect", "--format", "{{.Id}}", "jellyfin/jellyfin:latest")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("Jellyfin test image was not resolved to an immutable ID")
    token = uuid.uuid4().hex
    command = smoke_command(grant, image, token)
    try:
        report = subprocess.run(command, text=True, capture_output=True, timeout=120)
        if report.returncode:
            print((report.stdout + report.stderr)[-12000:], flush=True)
            raise ValueError(
                "GPU encode test failed; check the FFmpeg output above. No CPU fallback was used"
            )
        print(
            "[4/4] Jellyfin FFmpeg encoded 10 synthetic frames using the selected GPU: OK",
            flush=True,
        )
    finally:
        # Only our random, labelled test container may be cleaned up after a timeout.
        leftover = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "org.mediahub.gpu.test"}}',
                "mediahub-gpu-test-" + token,
            ],
            text=True,
            capture_output=True,
        )
        if leftover.returncode == 0 and leftover.stdout.strip() == token:
            run("docker", "rm", "-f", "mediahub-gpu-test-" + token)
    print(
        "GPU verification passed. Existing Jellyfin still needs its GPU choice and hardware-acceleration setting.",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument(
        "--root", type=Path, help="Also merge GPU access into this existing MediaHub deployment"
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Verify an existing deployment without changing its GPU configuration",
    )
    parser.add_argument("--gpu", help="Prepared GPU ID to verify")
    args = parser.parse_args()
    if os.geteuid() != 0 or Path("/etc/pve").exists():
        raise ValueError("Run as root inside the MediaHub Docker guest, not on Proxmox")
    grants = read_inventory(args.inventory)
    if args.test_only:
        if not args.root:
            raise ValueError("--test-only requires --root")
        verify_installation(args.root, grants, args.gpu)
        return
    prepare(grants)
    if args.root:
        apply_existing(args.root, grants)


if __name__ == "__main__":
    main()
