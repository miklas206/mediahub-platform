"""Standalone program sent over pinned SSH to the Proxmox host.

Only a dedicated MediaHub-created LXC is supported. External bind sources are
never deleted. Unknown volumes, snapshots and local media block removal.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GUEST_PROBE = r"""
import json, pathlib, subprocess, sys
cfg = json.loads(sys.argv[1])
root = pathlib.Path(cfg['installPath'])
if root.resolve() != root or not root.is_dir():
    raise ValueError('Source ownership changed')
origin = subprocess.check_output(['git', '-C', str(root), 'remote', 'get-url', 'origin'], text=True).strip()
if origin.removesuffix('.git') != 'https://github.com/qlerup/fjordhub':
    raise ValueError('Unexpected source repository')
env = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines()
           if '=' in line and not line.startswith('#'))
if env.get('DATA_DIR') != cfg['dataPath']:
    raise ValueError('App data location changed')
ids = subprocess.check_output(['docker', 'ps', '-aq'], text=True).split()
items = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True)) if ids else []
media = []
for item in items:
    for mount in item.get('Mounts', []):
        target = mount.get('Destination', '').lower()
        if any(target == p or target.startswith(p + '/') for p in
               ('/media', '/uploads', '/library', '/movies', '/tv', '/videos')):
            source = pathlib.Path(mount['Source'])
            if not source.is_dir():
                raise ValueError('Cannot verify a media source')
            media.append({'path': str(source.resolve()), 'nonempty': any(source.iterdir())})
default_media = pathlib.Path('/opt/fjordflix-data/media')
if default_media.is_dir():
    media.append({'path': str(default_media.resolve()), 'nonempty': any(default_media.iterdir())})
print(json.dumps({'containers': sorted(item['Name'].lstrip('/') for item in items),
                  'media': media, 'account': env.get('PROXMOX_TOKEN_ID', '').split('!')[0]}))
"""


def run(args, timeout=60):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Do not echo subprocess output: environment/SSH errors may contain secrets.
        raise ValueError("Command failed: " + " ".join(args[:2]))
    return result.stdout


def beneath(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def storage_plan(raw, cfg):
    """Reject every volume that is not the installer's two dedicated disks."""
    if any(line.startswith("[") for line in raw.splitlines()):
        raise ValueError(
            "Snapshots or pending configuration exist; review them before uninstalling."
        )
    config = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
    if config.get("hostname") != cfg["hostname"]:
        raise ValueError("LXC identity changed.")
    if config.get("lock") or config.get("protection") == "1" or config.get("template") == "1":
        raise ValueError("The LXC is locked, protected or a template.")
    deleted, kept = [], []
    for key, value in config.items():
        if key == "lxc.mount.auto":
            # These are kernel pseudo-filesystems, not disks or media shares.
            # https://linuxcontainers.org/lxc/manpages/man5/lxc.container.conf.5.html
            allowed = {"proc", "proc:mixed", "proc:rw", "sys", "sys:mixed", "sys:ro", "sys:rw"}
            allowed.update(
                kind + mode + force
                for kind in ("cgroup", "cgroup-full")
                for mode in ("", ":mixed", ":ro", ":rw")
                for force in ("", ":force")
            )
            if all(item in allowed for item in value.split()):
                continue
        if key.startswith("unused") or key.startswith("lxc.mount") or key.startswith("lxc.rootfs"):
            raise ValueError(
                f"Preview blocked by {key} in LXC {cfg['ctid']}. "
                f"Inspect this entry with 'pct config {cfg['ctid']}' on Proxmox. "
                "Its storage ownership cannot be verified automatically. Nothing has been deleted."
            )
        if key != "rootfs" and not re.fullmatch(r"mp\d+", key):
            continue
        source, *options = value.split(",")
        opts = dict(option.split("=", 1) for option in options if "=" in option)
        target = "/" if key == "rootfs" else opts.get("mp", "")
        if not target.startswith("/") or ".." in Path(target).parts:
            raise ValueError("Invalid mount target.")
        if key in {"rootfs", "mp0"}:
            if key == "mp0" and target != cfg["dataPath"]:
                raise ValueError("The app-data mount changed.")
            # Proxmox managed rootdir names, including directory, LVM and ZFS storage.
            pattern = (
                re.escape(cfg["storage"])
                + r":(?:"
                + re.escape(cfg["ctid"])
                + r"/)?(?:vm|subvol)-"
                + re.escape(cfg["ctid"])
                + r"-disk-\d+(?:\.raw)?"
            )
            if not re.fullmatch(pattern, source):
                raise ValueError("System/app-data disk ownership cannot be verified.")
            deleted.append({"slot": key, "source": source, "path": target})
        elif source.startswith("/") and not beneath(source, "/dev"):
            kept.append({"slot": key, "source": source, "path": target})
        else:
            raise ValueError(
                "Additional managed/device disks may contain media. Detach them safely before uninstalling."
            )
    if {item["slot"] for item in deleted} != {"rootfs", "mp0"}:
        raise ValueError("The original system and app-data disks could not both be identified.")
    if len({item["source"] for item in deleted}) != 2:
        raise ValueError("System and app-data disks must be distinct.")
    return deleted, kept


def inspect(cfg):
    ctid = cfg["ctid"]
    journal = Path(f"/var/lib/mediahub/fjordhub-uninstall/{ctid}.json")
    if not Path(f"/etc/pve/lxc/{ctid}.conf").exists() and journal.is_file():
        saved = json.loads(journal.read_text())
        if saved["config"] != cfg:
            raise ValueError("Uninstall recovery identity does not match.")
        return saved["plan"]
    raw = run(["pct", "config", ctid])
    deleted, kept = storage_plan(raw, cfg)
    # Also reject snapshots/pending entries that pct config might omit.
    full = Path(f"/etc/pve/lxc/{ctid}.conf").read_text()
    storage_plan(full, cfg)
    if run(["pct", "status", ctid]).strip() != "status: running":
        raise ValueError("Start the existing LXC so its ownership and media mounts can be checked.")
    guest = json.loads(
        run(["pct", "exec", ctid, "--", "python3", "-c", GUEST_PROBE, json.dumps(cfg)])
    )
    for media in guest["media"]:
        # A managed disk nested below an external mount is still internal.
        containing = max(
            (item for item in deleted + kept if beneath(media["path"], item["path"])),
            key=lambda item: len(item["path"]),
        )
        if media["nonempty"] and containing not in kept:
            raise ValueError(
                "Media exists on an internal disk: "
                + media["path"]
                + ". Move it to shared storage first."
            )
    account = guest["account"]
    accounts = json.loads(run(["pveum", "user", "list", "--output-format", "json"]))
    dedicated = []
    for user in accounts:
        if (
            re.fullmatch(
                r"mediahub-fjordhub-" + re.escape(ctid) + r"-[a-f0-9]{8}@pve", user["userid"]
            )
            and user.get("comment") == f"FjordHub inventory for LXC {ctid} (MediaHub)"
        ):
            dedicated.append(user["userid"])
    if account and account not in dedicated:
        raise ValueError(
            "The Proxmox account is not dedicated to this deployment; review it first."
        )
    plan = {
        "ctid": ctid,
        "deleteDisks": deleted,
        "preserveMounts": kept,
        "containers": guest["containers"],
        "accounts": sorted(dedicated),
        "node": Path("/etc/pve/local").resolve().name,
    }
    volumes = json.loads(
        run(
            [
                "pvesh",
                "get",
                f"/nodes/{plan['node']}/storage/{cfg['storage']}/content",
                "--vmid",
                ctid,
                "--output-format",
                "json",
            ]
        )
    )
    if not {item["source"] for item in deleted} <= {item["volid"] for item in volumes}:
        raise ValueError("The planned application disks could not be verified in storage.")
    plan["digest"] = hashlib.sha256((full + json.dumps(plan, sort_keys=True)).encode()).hexdigest()
    return plan


def execute(cfg, expected):
    plan = inspect(cfg)
    if plan["digest"] != expected:
        raise ValueError("Installation changed. Review a new uninstall plan.")
    ctid = cfg["ctid"]
    config_path = Path(f"/etc/pve/lxc/{ctid}.conf")
    journal = Path(f"/var/lib/mediahub/fjordhub-uninstall/{ctid}.json")
    journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"config": cfg, "plan": plan}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    # No filesystem deletion and no volume pruning. Proxmox deletes the two
    # verified managed disks and ignores bind sources. Never use --force or
    # --destroy-unreferenced-disks=1.
    if config_path.exists():
        run(["pct", "shutdown", ctid, "--timeout", "60"], timeout=90)
        if run(["pct", "status", ctid]).strip() != "status: stopped":
            raise ValueError("LXC did not stop; no disks were deleted.")
        # Repeat the storage comparison after shutdown, before the destructive call.
        deleted, kept = storage_plan(config_path.read_text(), cfg)
        if deleted != plan["deleteDisks"] or kept != plan["preserveMounts"]:
            raise ValueError("Storage changed during shutdown; no disks were deleted.")
        run(
            ["pct", "destroy", ctid, "--purge", "1", "--destroy-unreferenced-disks", "0"],
            timeout=180,
        )
    if config_path.exists():
        raise ValueError("LXC removal could not be verified.")
    # Proxmox can warn about a failed volume deletion while returning success.
    remaining = json.loads(
        run(
            [
                "pvesh",
                "get",
                f"/nodes/{plan['node']}/storage/{cfg['storage']}/content",
                "--vmid",
                ctid,
                "--output-format",
                "json",
            ]
        )
    )
    if any(row["volid"] in {disk["source"] for disk in plan["deleteDisks"]} for row in remaining):
        raise ValueError(
            "LXC removed, but an application disk remains. Inspect storage before retrying."
        )
    users = {
        user["userid"]: user
        for user in json.loads(run(["pveum", "user", "list", "--output-format", "json"]))
    }
    for account in plan["accounts"]:
        if account in users:
            if users[account].get("comment") != f"FjordHub inventory for LXC {ctid} (MediaHub)":
                raise ValueError("Proxmox account ownership changed; cleanup is incomplete.")
            run(["pveum", "user", "delete", account])
    return {
        **plan,
        "state": "removed",
        "message": "FjordHub LXC, applications, app data and dedicated Proxmox accounts removed. External media preserved.",
    }


def main():
    body = json.loads(sys.stdin.read())
    try:
        result = (
            execute(body["config"], body["digest"])
            if body.get("remove")
            else inspect(body["config"])
        )
        print(json.dumps({"ok": True, "result": result}))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": str(error)
                    if isinstance(error, ValueError)
                    else "Cannot verify or complete uninstall. Inspect the existing LXC before retrying.",
                }
            )
        )


if __name__ == "__main__":
    main()
