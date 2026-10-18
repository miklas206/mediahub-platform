"""Prepare one existing MediaHub LXC for userspace SMB, preserving other devices."""

import argparse
import json
import os
import re
import stat
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def prepare(ctid, runner=run):
    if not re.fullmatch(r"[1-9][0-9]{2,8}", str(ctid)):
        raise ValueError("Choose an existing container ID")
    config = dict(
        line.split(": ", 1)
        for line in runner("pct", "config", str(ctid)).splitlines()
        if ": " in line
    )
    if config.get("unprivileged") != "1":
        raise ValueError("This preparation is for an unprivileged MediaHub container")
    # Verify the application without inspecting passwords or other container data.
    runner("pct", "exec", str(ctid), "--", "test", "-f", "/opt/mediahub/installed-version")
    for key, value in config.items():
        if re.fullmatch(r"dev[0-9]+", key) and re.search(r"(?:^|,)path=/dev/fuse(?:,|$)", value):
            return {"prepared": True, "changed": False}
    for number in range(256):
        if "dev" + str(number) not in config:
            runner(
                "pct",
                "set",
                str(ctid),
                "--dev" + str(number),
                "path=/dev/fuse,uid=0,gid=0,mode=0600",
            )
            runner(
                "pct",
                "exec",
                str(ctid),
                "--",
                "python3",
                "-c",
                "import os; fd=os.open('/dev/fuse',os.O_RDWR); os.close(fd)",
            )
            return {"prepared": True, "changed": True}
    raise ValueError("No free device slot; existing devices were preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ctid", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path("/etc/pve").is_dir():
        raise SystemExit("Run on the Proxmox host as root")
    if not stat.S_ISCHR(Path("/dev/fuse").stat().st_mode):
        raise SystemExit("The host requires the FUSE device")
    print(json.dumps(prepare(args.ctid)))
