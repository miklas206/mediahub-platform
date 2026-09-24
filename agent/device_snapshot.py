"""Host-side, read-only metadata collector; standard library only.

Run in the host mount namespace, never a container namespace. No mounting, device
writes, SMART commands or filesystem repair. The snapshot is the only file written.
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path


def unescape(value):
    for escaped, literal in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(escaped, literal)
    return value


def collect():
    memory = {
        line.split(":")[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.split()[1].isdigit()
    }
    cpu = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    result = subprocess.run(
        [
            "lsblk",
            "--json",
            "--bytes",
            "--paths",
            "--output",
            "NAME,KNAME,TYPE,MODEL,SERIAL,SIZE,RO,UUID,MAJ:MIN,WWN",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=8,
    )
    if len(result.stdout) > 1024 * 1024:
        raise ValueError("Device inventory exceeds limit")
    listing = json.loads(result.stdout)
    aliases = {}
    alias_root = Path("/dev/disk/by-id")
    if alias_root.is_dir():
        for alias in sorted(alias_root.iterdir())[:1024]:
            if alias.is_symlink():
                aliases.setdefault(str(alias.resolve()), []).append(str(alias))
    mounts = {}
    host_mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        divider = fields.index("-")
        options = fields[5].split(",")
        super_options = fields[divider + 3].split(",")
        host_mounts.append(
            {
                "path": unescape(fields[4]),
                "root": unescape(fields[3]),
                "deviceNumber": fields[2],
                "filesystem": fields[divider + 1],
                "source": unescape(fields[divider + 2]),
                "readOnly": "ro" in options or "ro" in super_options,
            }
        )
        mounts.setdefault(fields[2], []).append(
            {
                "path": unescape(fields[4]),
                "root": unescape(fields[3]),
                "readOnly": "ro" in options or "ro" in super_options,
                "accessScope": "filesystem-mount-options-not-app-permissions",
            }
        )
    devices = []
    filesystem_uuids = {}

    def visit(items, parent=None):
        for item in items:
            if len(devices) >= 256:
                raise ValueError("Too many block devices")
            serial = item.get("serial") or (parent or {}).get("serial")
            path = item["name"]
            by_id = aliases.get(path, [])
            uuid = item.get("uuid")
            if uuid and item.get("maj:min"):
                filesystem_uuids[item["maj:min"]] = uuid
            wwn = item.get("wwn")
            identity = (
                "uuid:" + uuid
                if uuid
                else by_id[0]
                if by_id
                else "wwn:" + wwn
                if wwn
                else "serial:" + serial
                if serial
                else None
            )
            device_mounts = mounts.get(item.get("maj:min"), [])
            devices.append(
                {
                    "type": "block",
                    "kind": item.get("type"),
                    "path": path,
                    "location": Path(path).name,
                    "connected": True,
                    "serial": serial,
                    "uuid": uuid,
                    "wwn": wwn,
                    "byId": by_id,
                    "stableIdentity": identity,
                    "model": item.get("model") or (parent or {}).get("model"),
                    "sizeBytes": item.get("size"),
                    "readOnly": bool(item.get("ro")),
                    "mounted": bool(device_mounts),
                    "mounts": device_mounts,
                    "parentPath": (parent or {}).get("name"),
                }
            )
            visit(item.get("children", []), item)

    visit(listing.get("blockdevices", []))
    for mount in host_mounts:
        mount["uuid"] = filesystem_uuids.get(mount["deviceNumber"])
    return {
        "schemaVersion": 1,
        "observedAt": time.time(),
        "available": True,
        "scope": "host-mount-namespace",
        "devices": devices,
        "mounts": host_mounts,
        "host": {
            "cpuPercent": None,
            "cpuTotalTicks": sum(cpu),
            "cpuIdleTicks": cpu[3] + cpu[4],
            "ramTotalBytes": memory["MemTotal"],
            "ramAvailableBytes": memory["MemAvailable"],
            "ramUsedBytes": memory["MemTotal"] - memory["MemAvailable"],
            "uptimeSeconds": float(Path("/proc/uptime").read_text().split()[0]),
            "cpuCores": os.cpu_count(),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    snapshot = collect()  # On failure do not replace prior snapshot; reader rejects stale data.
    try:
        previous = json.loads(args.output.read_text())
        delta = snapshot["host"]["cpuTotalTicks"] - previous["host"]["cpuTotalTicks"]
        idle = snapshot["host"]["cpuIdleTicks"] - previous["host"]["cpuIdleTicks"]
        if delta > 0 and 0 <= idle <= delta:
            snapshot["host"]["cpuPercent"] = round(100 * (delta - idle) / delta, 1)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    fd, temporary = tempfile.mkstemp(prefix=".devices-", dir=args.output.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(snapshot, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, args.output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
