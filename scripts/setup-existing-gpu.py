"""Guided GPU setup and verification for an existing MediaHub Proxmox LXC."""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from proxmox_gpu import configure, discover, prepare_host_drivers, run


def guest(ctid, *args):
    subprocess.run(["pct", "exec", ctid, "--", *map(str, args)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ctid", help="Existing MediaHub LXC ID")
    parser.add_argument("--gpu", help="Exact ID from the discovered list")
    parser.add_argument(
        "--install-drivers",
        action="store_true",
        help="Prepare missing Proxmox GPU drivers before sharing",
    )
    parser.add_argument(
        "--drivers-yes",
        action="store_true",
        help="Explicitly approve host GPU package/repository installation",
    )
    parser.add_argument(
        "--repair-video-access",
        action="store_true",
        help="Repair existing GPU access without stopping the LXC or restarting Docker",
    )
    parser.add_argument("--root", default="/opt/mediahub")
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Run diagnostics without changing GPU grants or stopping the guest",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Explicitly authorize stopping/restarting this guest and its Docker services",
    )
    args = parser.parse_args()
    if args.install_drivers and (args.test_only or args.repair_video_access):
        raise ValueError(
            "Host driver installation belongs to initial GPU setup, not repair/test-only"
        )
    if args.repair_video_access and args.test_only:
        raise ValueError("Choose repair or test-only, not both")
    if os.geteuid() != 0 or not Path("/etc/pve").is_dir():
        raise ValueError("Run on the Proxmox node as root, not inside MediaHub")
    ctid = args.ctid or input("Existing MediaHub LXC ID: ").strip()
    if (
        not re.fullmatch(r"[1-9][0-9]{2,8}", ctid)
        or not re.fullmatch(r"/[A-Za-z0-9_./-]+", args.root)
        or ".." in Path(args.root).parts
    ):
        raise ValueError("Invalid LXC ID or installation root")
    if run("pct", "status", ctid) != "status: running":
        raise ValueError("Start this existing MediaHub guest before running the guide")
    # Prove the selected guest contains MediaHub before offering any mutation.
    probe = (
        "import json,sys,subprocess\nfrom pathlib import Path\n"
        "p=Path(sys.argv[1]);assert p.resolve()==p\n"
        "d=json.loads((p/'compose.json').read_text())\n"
        "assert d.get('name')=='mediahub-platform' and 'core' in d.get('services',{}), 'Not a MediaHub deployment'\n"
        "for role in ('core','agent'):\n"
        " if role not in d['services']: continue\n"
        " c=subprocess.check_output(['docker','compose','-f',str(p/'compose.json'),'ps','-q',role],text=True).strip()\n"
        " assert c and all(v in '0123456789abcdef' for v in c), 'MediaHub controller is not running'\n"
        " subprocess.run(['docker','exec',c,'python','-c','from agent.gpu import GPUGrant'],check=True)\n"
    )
    try:
        guest(ctid, "python3", "-c", probe, args.root)
    except subprocess.CalledProcessError:
        raise ValueError(
            "Verify the selected guest and update MediaHub Core/Agent to v0.5.29 or newer before using this tool. No GPU changes were made"
        ) from None
    source = Path(__file__).resolve().parent / "gpu_setup.py"
    if not source.is_file():
        raise ValueError(
            "Run this guide from the reviewed MediaHub checkout; gpu_setup.py is required"
        )
    definitions = {
        node.name
        for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.FunctionDef)
    }
    if not {"main", "read_inventory", "prepare", "apply_existing", "verify_installation"}.issubset(
        definitions
    ):
        raise ValueError(
            "Guest GPU helper is incomplete. Download all three scripts again before applying GPU access"
        )
    token = uuid.uuid4().hex
    helper = "/root/mediahub-gpu-tool-" + token + ".py"
    if not args.test_only and not args.repair_video_access:
        if args.install_drivers:
            prepare_host_drivers(args.drivers_yes)
        choices = discover()
        if not choices:
            raise ValueError(
                "No ready GPU detected. Check the GPU diagnostics above; no LXC changes were made"
            )
        for gpu in choices:
            print(gpu["id"] + "  " + gpu["name"])
        selected_id = args.gpu or input("GPU ID to share (Enter cancels): ").strip()
        if not selected_id:
            return
        gpu = next((g for g in choices if g["id"] == selected_id), None)
        if not gpu:
            raise ValueError("Choose a GPU ID from the detected list")
        configuration = (Path("/etc/pve/lxc") / (ctid + ".conf")).read_text()
        if "mediahub-nvidia" in configuration or any(p in configuration for p in gpu["devices"]):
            raise ValueError(
                "GPU devices are already mapped. Use --test-only to verify them; inspect existing mappings before replacing them"
            )
        if not re.search(r"^unprivileged:\s*1\s*$", configuration, re.M):
            raise ValueError("This guide requires an unprivileged MediaHub LXC")
        print(f"MediaHub LXC {ctid}, root {args.root}, GPU {gpu['name']}.")
        print(
            "This stops the selected LXC, shares its GPU, restarts Docker and recreates MediaHub controllers. Media/app volumes are preserved."
        )
        if not args.yes and input("Type GPU to apply and run hardware tests: ").strip() != "GPU":
            return
        directory = Path("/var/lib/mediahub-gpu") / ctid
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        inventory = directory / ("inventory-" + token + ".json")
        print("[1/5] Stopping the selected MediaHub guest...", flush=True)
        run("pct", "shutdown", ctid, "--timeout", "120")
        try:
            print("[2/5] Sharing only the selected GPU...", flush=True)
            configure(ctid, gpu, inventory)
        finally:
            # Recover availability if GPU preflight failed after the planned shutdown.
            if run("pct", "status", ctid) == "status: stopped":
                run("pct", "start", ctid)
        run("pct", "push", ctid, inventory, "/etc/mediahub-gpus.json", "--perms", "0600")
    print("[3/5] Copying the reviewed guest helper...", flush=True)
    run("pct", "push", ctid, source, helper, "--perms", "0600")
    if args.repair_video_access:
        print(
            "This removes administrative NVIDIA nodes from MediaHub's grants and recreates only Core/Agent. The LXC and Docker stay running."
        )
        if not args.yes and input("Type GPU to repair and run hardware tests: ").strip() != "GPU":
            return
        guest(
            ctid,
            "python3",
            helper,
            "--inventory",
            "/etc/mediahub-gpus.json",
            "--root",
            args.root,
            "--repair-video-access",
        )
        # Never restart proxy or installed apps while repairing controller access.
        compose = json.loads(run("pct", "exec", ctid, "cat", args.root + "/compose.json"))
        roles = [r for r in ("core", "agent") if r in compose.get("services", {})]
        guest(
            ctid,
            "docker",
            "compose",
            "-f",
            args.root + "/compose.json",
            "up",
            "-d",
            "--no-deps",
            *roles,
        )
    if not args.test_only and not args.repair_video_access:
        print("[4/5] Preparing Docker and updating the existing MediaHub GPU policy...", flush=True)
        guest(
            ctid, "python3", helper, "--inventory", "/etc/mediahub-gpus.json", "--root", args.root
        )
        guest(ctid, "docker", "compose", "-f", args.root + "/compose.json", "up", "-d")
    print("[5/5] Testing host policy, controller access and real GPU transcoding...", flush=True)
    command = [
        "python3",
        helper,
        "--inventory",
        "/etc/mediahub-gpus.json",
        "--root",
        args.root,
        "--test-only",
    ]
    if args.gpu:
        command += ["--gpu", args.gpu]
    guest(ctid, *command)
    print(
        "Done: GPU tests passed. Select this GPU when installing Jellyfin, then enable hardware acceleration in Jellyfin."
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print("GPU setup/test failed: " + str(error), file=sys.stderr)
        print(
            "Keep the configuration backups and inspect the reported step before retrying. No media or app volumes are deleted.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
