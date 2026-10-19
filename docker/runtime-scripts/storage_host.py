#!/usr/bin/env python3
"""Private host controller for approved storage, CIFS mounts and LAN-only SMB.

Installed by the root updater, never run inside Core. HTTP is Unix-socket-only
and verifies SO_PEERCRED. No caller supplies commands, host paths or Docker specs.
"""

import argparse
import hashlib
import io
import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import socketserver
import struct
import subprocess
import threading
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ID = re.compile(r"[a-f0-9]{24}\Z")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}\Z")
PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
OWNER = "org.mediahub.storage"
CONTAINER = "mediahub-storage-smb"
RCLONE_VERSION = "1.75.2"
RCLONE_ARCHIVES = {
    "x86_64": ("amd64", "349ac8fba6ff65d6247043f1750cdcb518ec5d500ef91463a10d37c0ccdf3702"),
    "aarch64": ("arm64", "7e1e8d69654941b7b7df84ee74c5f7fb09cce7d5496947fb7bf16b55ff427d10"),
}


class StorageError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def private_ip(value):
    try:
        ip = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        raise StorageError("Enter a private LAN IPv4 address", 422) from None
    if not any(ip in network for network in PRIVATE):
        raise StorageError("Enter a private LAN IPv4 address", 422)
    return str(ip)


def text(value, limit=256, minimum=1):
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise StorageError("Invalid storage field", 422)
    return value


def name(value):
    if (
        not isinstance(value, str)
        or not NAME.fullmatch(value)
        or value.casefold() in {"global", "homes", "printers", "print"}
    ):
        raise StorageError(
            "Use a name starting with a letter, followed by letters, digits, - or _", 422
        )
    return value


def command(args, *, content=None, timeout=35):
    try:
        result = subprocess.run(
            args,
            input=content,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
            if args[0] == "apt-get"
            else None,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise StorageError(
            "Storage command unavailable or timed out; check host prerequisites"
        ) from None
    if result.returncode:
        # Command output can include credentials and must never reach logs/API.
        raise StorageError(
            "Storage operation failed; check server access, credentials and host mount permissions"
        )
    return result.stdout


def save(path, value):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value if isinstance(value, str) else json.dumps(value))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class StorageHost:
    def __init__(self, root, run=command):
        self.root = Path(root)
        self.installation = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
        self.run = run
        self.folder = self.root / "storage-private"
        self.folder.mkdir(mode=0o700, exist_ok=True)
        self.mounts = self.root / "network-storage"
        self.mounts.mkdir(mode=0o711, exist_ok=True)
        self.file = self.folder / "state.json"
        self.lock = threading.RLock()
        self.package_error = None
        self.revision = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def policy(self):
        return json.loads((self.root / "storage-policy.json").read_text())

    def state(self):
        return (
            json.loads(self.file.read_text())
            if self.file.exists()
            else {"nas": [], "shares": [], "passwordConfigured": False}
        )

    def mount_info(self, path):
        try:
            rows = json.loads(
                self.run(
                    ["findmnt", "--json", "--target", str(path), "--output", "TARGET,SOURCE,FSTYPE"]
                )
            )["filesystems"]
            return rows[0]
        except (StorageError, ValueError, KeyError, IndexError):
            return {}

    def nas_ready(self, row):
        info = self.mount_info(self.mounts / row["id"])
        return info.get("target") == str(self.mounts / row["id"]) and (
            (
                info.get("fstype") == "cifs"
                and info.get("source") == "//" + row["server"] + "/" + row["share"]
            )
            or (
                info.get("fstype") == "fuse.rclone"
                and info.get("source") == "mediahub-nas-" + row["id"]
            )
        )

    @staticmethod
    def userspace_mounts():
        """CIFS cannot be mounted in an unprivileged Linux user namespace."""
        try:
            first = Path("/proc/self/uid_map").read_text().splitlines()[0].split()
            return int(first[1]) != 0
        except (OSError, ValueError, IndexError):
            return False

    def rclone_binary(self):
        return self.folder / "tools" / ("rclone-v" + RCLONE_VERSION)

    def prepare_rclone(self):
        """Pin and verify the SMB client; old distro versions misreport block sizes."""
        target = self.rclone_binary()
        directory = target.parent
        directory.mkdir(mode=0o700, exist_ok=True)
        if (
            directory.is_symlink()
            or directory.stat().st_mode & 0o077
            or directory.stat().st_uid != os.geteuid()
        ):
            raise StorageError("Unsafe private storage tools directory")
        if target.exists():
            if (
                target.is_symlink()
                or not target.is_file()
                or target.stat().st_uid != os.geteuid()
                or target.stat().st_nlink != 1
                or target.stat().st_mode & 0o022
                or not os.access(target, os.X_OK)
            ):
                raise StorageError("Storage tool ownership or permissions changed")
            return
        try:
            arch, expected = RCLONE_ARCHIVES[platform.machine()]
            name = "rclone-v" + RCLONE_VERSION + "-linux-" + arch
            url = (
                "https://github.com/rclone/rclone/releases/download/v"
                + RCLONE_VERSION
                + "/"
                + name
                + ".zip"
            )
            with urllib.request.urlopen(url, timeout=45) as response:
                content = response.read(128 * 1024 * 1024 + 1)
            if len(content) > 128 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != expected:
                raise ValueError("Storage tool checksum mismatch")
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                member = archive.getinfo(name + "/rclone")
                if member.file_size > 256 * 1024 * 1024:
                    raise ValueError("Storage tool size exceeded")
                binary = archive.read(member)
            temporary = target.with_suffix(".preparing")
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700
            )
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(binary)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            raise StorageError(
                "Automatic SMB client preparation failed. Check the host's access to GitHub release downloads and retry server setup."
            ) from None

    def mount_userspace(self, row, target):
        try:
            descriptor = os.open("/dev/fuse", os.O_RDWR)
            os.close(descriptor)
        except OSError:
            raise StorageError(
                "This container needs access to /dev/fuse for automatic NAS connections. "
                "Run the MediaHub Proxmox storage preparation on its host once; "
                "the saved NAS connection will then retry automatically."
            ) from None
        values = dict(
            line.split("=", 1)
            for line in (self.folder / (row["id"] + ".credentials")).read_text().splitlines()
        )
        obscured = self.run(
            [str(self.rclone_binary()), "obscure", "-"], content=values["password"]
        ).strip()
        config = self.folder / (row["id"] + ".rclone.conf")
        save(
            config,
            "[mediahub]\ntype = smb\nhost = "
            + row["server"]
            + "\nuser = "
            + values["username"]
            + "\npass = "
            + obscured
            + "\n",
        )
        # Validate authentication before exposing a mounted filesystem. No listing
        # or credentials are returned to the browser or written to the journal.
        try:
            self.run(
                [
                    str(self.rclone_binary()),
                    "lsjson",
                    "mediahub:" + row["share"],
                    "--config",
                    str(config),
                    "--stat",
                    "--contimeout",
                    "5s",
                    "--timeout",
                    "10s",
                    "--retries",
                    "1",
                    "--low-level-retries",
                    "1",
                ],
                timeout=20,
            )
        except StorageError:
            raise StorageError(
                "The NAS share or login was rejected or the NAS is unreachable. Check the share name and NAS account."
            ) from None
        unit = "mediahub-nas-" + self.installation + "-" + row["id"]
        args = [
            "systemd-run",
            "--quiet",
            "--collect",
            "--unit=" + unit,
            "--property=Type=notify",
            "--property=TimeoutStartSec=30",
            "--property=UMask=0077",
            "--property=StandardOutput=null",
            "--property=StandardError=null",
            str(self.rclone_binary()),
            "mount",
            "mediahub:" + row["share"],
            str(target),
            "--config",
            str(config),
            "--devname",
            "mediahub-nas-" + row["id"],
            "--allow-other",
            "--default-permissions",
            "--uid",
            "1000",
            "--gid",
            "1000",
            "--file-perms",
            "0660",
            "--dir-perms",
            "0770",
            "--vfs-cache-mode",
            "off",
            "--contimeout",
            "5s",
            "--timeout",
            "15s",
            "--option",
            "nosuid,nodev,noexec",
        ]
        if row["readOnly"]:
            args.append("--read-only")
        self.run(args, timeout=40)

    def locations(self):
        result = []
        for row in self.policy()["locations"]:
            path = Path(row["source"])
            info = self.mount_info(path)
            ready = (
                path.is_dir()
                and path.resolve() == path
                and info.get("source") == row["mountSource"]
                and info.get("target") == row["mountTarget"]
            )
            try:
                ready = ready and all(
                    not Path(marker).is_symlink() and Path(marker).read_text().strip() == expected
                    for marker, expected in row.get("markers", {}).items()
                )
            except OSError:
                ready = False
            result.append({**row, "ready": ready, "kind": "local"})
        for row in self.state()["nas"]:
            result.append(
                {
                    "id": row["id"],
                    "label": row["label"],
                    "source": str(self.mounts / row["id"]),
                    "kind": "nas",
                    "readOnly": row["readOnly"],
                    "ready": self.nas_ready(row),
                }
            )
        return result

    def location(self, identifier):
        row = next((r for r in self.locations() if r["id"] == identifier), None)
        if not row or not row["ready"]:
            raise StorageError("Selected storage is unavailable; reconnect its disk or NAS first")
        return row

    def inventory(self):
        policy, state = self.policy(), self.state()
        locations = []
        for row in self.locations():
            free = total = None
            if row["ready"]:
                try:
                    if (
                        row["kind"] == "nas"
                        and self.mount_info(Path(row["source"])).get("fstype") == "fuse.rclone"
                    ):
                        connection = next(r for r in state["nas"] if r["id"] == row["id"])
                        usage = json.loads(
                            self.run(
                                [
                                    str(self.rclone_binary()),
                                    "about",
                                    "mediahub:" + connection["share"],
                                    "--config",
                                    str(self.folder / (row["id"] + ".rclone.conf")),
                                    "--json",
                                    "--contimeout",
                                    "1s",
                                    "--timeout",
                                    "2s",
                                    "--retries",
                                    "1",
                                    "--low-level-retries",
                                    "1",
                                ],
                                timeout=3,
                            )
                        )
                        total, free = usage["total"], usage["free"]
                        if (
                            type(total) is not int
                            or type(free) is not int
                            or not 0 <= free <= total
                        ):
                            raise ValueError("Invalid NAS capacity")
                    else:
                        blocks, available, size = map(
                            int,
                            self.run(
                                ["stat", "--file-system", "--format=%b:%a:%S", row["source"]],
                                timeout=3,
                            )
                            .strip()
                            .split(":"),
                        )
                        free, total = available * size, blocks * size
                except (StorageError, OSError, ValueError, KeyError, StopIteration):
                    free = total = None  # Capacity failure does not disconnect a mounted NAS.
            locations.append(
                {
                    k: v
                    for k, v in {**row, "freeBytes": free, "totalBytes": total}.items()
                    if k not in {"mountSource", "mountTarget", "markers"}
                }
            )
        return {
            "available": True,
            "controllerRevision": self.revision,
            "server": policy["lan"],
            "locations": locations,
            "nas": [
                {**r, "ready": self.nas_ready(r), "path": str(self.mounts / r["id"])}
                for r in state["nas"]
            ],
            "shares": [
                {**r, "unc": "\\\\" + policy["lan"] + "\\" + r["name"], "username": "mediahub"}
                for r in state["shares"]
            ],
            "passwordConfigured": state["passwordConfigured"],
            "prerequisite": self.package_error,
            "smbRunning": self.smb_running(),
        }

    def packages(self):
        required = {"mount.cifs": "cifs-utils"}
        if self.userspace_mounts():
            self.prepare_rclone()
            required.update({"fusermount3": "fuse3"})
        missing = sorted(
            {package for executable, package in required.items() if not shutil.which(executable)}
        )
        if not missing:
            self.package_error = None
            return
        try:
            self.run(["apt-get", "update"], timeout=120)
            self.run(
                ["apt-get", "install", "--no-remove", "--no-install-recommends", "-y", *missing],
                timeout=180,
            )
            self.package_error = None
        except StorageError:
            self.package_error = "Automatic CIFS preparation failed. This feature requires a Linux host with cifs-utils and permission to mount CIFS. In an LXC, the host administrator must allow CIFS mounts or mount the NAS on the Proxmox host."
            raise StorageError(self.package_error) from None

    def mount_nas(self, row):
        if self.nas_ready(row):
            return
        target = self.mounts / row["id"]
        if target.is_symlink() or (
            target.exists() and (any(target.iterdir()) or os.path.ismount(target))
        ):
            raise StorageError("NAS target is occupied; existing files were preserved")
        target.mkdir(mode=0o000, exist_ok=True)
        target.chmod(0o000)  # Unmounted storage must never become writable system-disk storage.
        if self.userspace_mounts():
            self.mount_userspace(row, target)
            if not self.nas_ready(row):
                raise StorageError("NAS mount identity could not be verified")
            return
        options = [
            "credentials=" + str(self.folder / (row["id"] + ".credentials")),
            "vers=3.1.1",
            "nosuid",
            "nodev",
            "noexec",
            "uid=1000",
            "gid=1000",
            "file_mode=0660",
            "dir_mode=0770",
            "ro" if row["readOnly"] else "rw",
        ]
        try:
            self.run(
                [
                    "mount",
                    "-t",
                    "cifs",
                    "//" + row["server"] + "/" + row["share"],
                    str(target),
                    "-o",
                    ",".join(options),
                ],
                timeout=40,
            )
        except StorageError:
            raise StorageError(
                "NAS mount failed. Check the NAS share and login. This Linux host must permit CIFS mounts; an LXC may require permission from its Proxmox administrator."
            ) from None
        if not self.nas_ready(row):
            raise StorageError("NAS mount identity could not be verified")

    def add_nas(self, body):
        if set(body) - {"label", "server", "share", "username", "password", "readOnly"}:
            raise StorageError("Unexpected NAS fields", 422)
        server, share = private_ip(body.get("server")), text(body.get("share"), 80)
        if (
            not re.fullmatch(r"[\w .-]{1,80}", share)
            or share in {".", ".."}
            or share != share.strip()
        ):
            raise StorageError("Enter the share name, without a path", 422)
        username, password = text(body.get("username"), 128), text(body.get("password"), minimum=1)
        label = text(body.get("label"), 80)
        read_only = body.get("readOnly", True)
        if type(read_only) is not bool:
            raise StorageError("Choose read-only or writable", 422)
        with self.lock:
            state = self.state()
            existing = next(
                (r for r in state["nas"] if r["server"] == server and r["share"] == share), None
            )
            if existing:
                raise StorageError(
                    "This NAS share is already configured; reconnect or remove it first"
                )
            if len(state["nas"]) >= 20:
                raise StorageError("A maximum of 20 NAS mounts is supported")
            identifier = os.urandom(12).hex()
            row = {
                "id": identifier,
                "label": label,
                "server": server,
                "share": share,
                "username": username,
                "readOnly": read_only,
                "enabled": True,
            }
            self.packages()
            credentials = self.folder / (identifier + ".credentials")
            save(credentials, "username=" + username + "\npassword=" + password + "\n")
            # Persist before mounting: a timeout is recoverable and credentials stay private.
            state["nas"].append(row)
            save(self.file, state)
            try:
                self.mount_nas(row)
            except StorageError as error:
                row["error"] = str(error)
                save(self.file, state)
                raise
        return {"saved": True}

    def nas_credentials(self, identifier, body):
        if not ID.fullmatch(identifier) or set(body) != {"username", "password"}:
            raise StorageError("Invalid NAS login fields", 422)
        username, password = text(body["username"], 128), text(body["password"], minimum=1)
        with self.lock:
            state = self.state()
            row = next((r for r in state["nas"] if r["id"] == identifier), None)
            if not row:
                raise StorageError("NAS not found", 404)
            if self.nas_ready(row):
                raise StorageError("Disconnect this NAS before changing its login")
            save(
                self.folder / (identifier + ".credentials"),
                "username=" + username + "\npassword=" + password + "\n",
            )
            row.update(username=username, enabled=True)
            row.pop("error", None)
            save(self.file, state)
            try:
                self.packages()
                self.mount_nas(row)
            except StorageError as error:
                row["error"] = str(error)
                save(self.file, state)
                raise
        return {"saved": True}

    def nas_action(self, identifier, action):
        if not ID.fullmatch(identifier):
            raise StorageError("Invalid NAS identifier", 422)
        with self.lock:
            state = self.state()
            row = next((r for r in state["nas"] if r["id"] == identifier), None)
            if not row:
                raise StorageError("NAS not found", 404)
            if action == "connect":
                self.packages()
                row["enabled"] = True
                save(self.file, state)
                try:
                    self.mount_nas(row)
                except StorageError as error:
                    row["error"] = str(error)
                    save(self.file, state)
                    raise
                row.pop("error", None)
            elif action in {"disconnect", "remove"}:
                if any(r["storageId"] == identifier for r in state["shares"]):
                    raise StorageError("Remove this NAS's Windows shares before disconnecting it")
                if self.nas_ready(row):
                    info = self.mount_info(self.mounts / identifier)
                    self.run(
                        [
                            "fusermount3" if info.get("fstype") == "fuse.rclone" else "umount",
                            *(["-u"] if info.get("fstype") == "fuse.rclone" else []),
                            str(self.mounts / identifier),
                        ]
                    )  # Never force/lazy-unmount busy data.
                elif os.path.ismount(self.mounts / identifier):
                    raise StorageError("NAS mount ownership changed; nothing was disconnected")
                row["enabled"] = False
                if action == "remove":
                    state["nas"].remove(row)
                    (self.folder / (identifier + ".credentials")).unlink(missing_ok=True)
                    (self.folder / (identifier + ".rclone.conf")).unlink(missing_ok=True)
            else:
                raise StorageError("Unknown NAS operation", 422)
            save(self.file, state)
        return {"saved": True}

    def owned_smb(self):
        try:
            rows = json.loads(self.run(["docker", "inspect", CONTAINER]))
        except StorageError:
            return None
        if (
            len(rows) != 1
            or rows[0].get("Config", {}).get("Labels", {}).get(OWNER) != "smb"
            or rows[0].get("Config", {}).get("Labels", {}).get(OWNER + ".installation")
            != self.installation
        ):
            raise StorageError("The SMB container name is occupied by another service")
        return rows[0]

    def smb_running(self):
        row = self.owned_smb()
        return bool(row and row.get("State", {}).get("Running"))

    def smb_image(self):
        dockerfile = """FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends samba smbclient && rm -rf /var/lib/apt/lists/* && useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin mediahub
CMD ["smbd", "--foreground", "--no-process-group", "--configfile=/config/smb.conf", "--debug-stdout"]
"""
        image = "mediahub-storage-smb:" + hashlib.sha256(dockerfile.encode()).hexdigest()[:16]
        try:
            self.run(["docker", "image", "inspect", image])
        except StorageError:
            build = self.folder / "image"
            build.mkdir(mode=0o700, exist_ok=True)
            save(build / "Dockerfile", dockerfile)
            self.run(["docker", "build", "-t", image, str(build)], timeout=300)
        return image

    def configure_smb(self, shares, password=None):
        image = self.smb_image() if shares else None
        folder = self.folder / "samba"
        folder.mkdir(mode=0o700, exist_ok=True)
        # Samba's passdb stays private. Never save a plaintext SMB password.
        config = """[global]
server role = standalone server
security = user
map to guest = Never
server min protocol = SMB3_00
smb ports = 445
disable netbios = yes
load printers = no
printing = bsd
printcap name = /dev/null
passdb backend = tdbsam:/config/passdb.tdb
private dir = /config
state directory = /config
cache directory = /tmp
lock directory = /tmp
log file = /dev/null
logging = file
"""
        binds = []
        for share in shares:
            location = self.location(share["storageId"])
            if not share["readOnly"] and location.get("readOnly"):
                raise StorageError("A read-only NAS cannot be shared with write access")
            target = "/shares/" + share["name"]
            config += (
                "\n["
                + share["name"]
                + "]\npath = "
                + target
                + "\nbrowseable = yes\nguest ok = no\nvalid users = mediahub\n"
                + "read only = "
                + ("yes" if share["readOnly"] else "no")
                + "\nfollow symlinks = no\nwide links = no\n"
            )
            binds += [
                "--mount",
                "type=bind,src="
                + location["source"]
                + ",dst="
                + target
                + (",readonly" if share["readOnly"] else ""),
            ]
        previous = self.owned_smb()
        # Verify all source mounts and image before stopping the existing service.
        recovery = CONTAINER + "-previous"
        if previous:
            try:
                self.run(["docker", "inspect", recovery])
            except StorageError:
                pass
            else:
                raise StorageError(
                    "A previous SMB recovery is still present; resolve it before changing shares"
                )
            self.run(["docker", "stop", "--time", "15", CONTAINER])
            self.run(["docker", "rename", CONTAINER, recovery])
        old_config = (folder / "smb.conf").read_text() if (folder / "smb.conf").exists() else None
        save(folder / "smb.conf", config)
        if not shares:
            if previous:
                self.run(["docker", "rm", recovery])
            return
        lan = private_ip(self.policy()["lan"])
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            CONTAINER,
            "--label",
            OWNER + "=smb",
            "--label",
            OWNER + ".installation=" + self.installation,
            "--restart",
            "no",
            "--read-only",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--tmpfs",
            "/run:rw,nosuid,nodev,size=16m",
            "--publish",
            lan + ":445:445/tcp",
            "--mount",
            "type=bind,src=" + str(folder) + ",dst=/config",
            *binds,
            image,
        ]
        try:
            self.run(args)
            if password is not None:
                self.run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        CONTAINER,
                        "smbpasswd",
                        "-c",
                        "/config/smb.conf",
                        "-s",
                        "-a",
                        "mediahub",
                    ],
                    content=password + "\n" + password + "\n",
                )
            if not self.smb_running():
                raise StorageError(
                    "Windows sharing did not start; check that LAN port 445 is available"
                )
            if previous:
                self.run(["docker", "rm", recovery])
        except StorageError:
            if self.owned_smb():
                self.run(["docker", "rm", "-f", CONTAINER])
            if old_config is not None:
                save(folder / "smb.conf", old_config)
            if previous:
                self.run(["docker", "rename", recovery, CONTAINER])
                self.run(["docker", "start", CONTAINER])
            raise

    def add_share(self, body):
        if set(body) - {"name", "storageId", "readOnly", "password"}:
            raise StorageError("Unexpected Windows share fields", 422)
        share_name, storage_id = name(body.get("name")), text(body.get("storageId"), 80)
        read_only = body.get("readOnly", True)
        if type(read_only) is not bool:
            raise StorageError("Choose read-only or writable", 422)
        password = body.get("password") or None
        if password is not None:
            text(password, minimum=12)
        with self.lock:
            state = self.state()
            if not state["passwordConfigured"] and password is None:
                raise StorageError("Set a Windows sharing password of at least 12 characters", 422)
            if password is not None and state["passwordConfigured"]:
                raise StorageError(
                    "Use the separate password action to change the shared Windows account password",
                    422,
                )
            if any(r["name"].casefold() == share_name.casefold() for r in state["shares"]):
                raise StorageError("This Windows share name already exists")
            if len(state["shares"]) >= 20:
                raise StorageError("A maximum of 20 Windows shares is supported")
            shares = [
                *state["shares"],
                {"name": share_name, "storageId": storage_id, "readOnly": read_only},
            ]
            self.configure_smb(shares, password)
            state["shares"] = shares
            state["passwordConfigured"] = True
            save(self.file, state)
        return {"saved": True}

    def remove_share(self, share_name):
        name(share_name)
        with self.lock:
            state = self.state()
            shares = [r for r in state["shares"] if r["name"] != share_name]
            if len(shares) == len(state["shares"]):
                raise StorageError("Windows share not found", 404)
            self.configure_smb(shares)
            state["shares"] = shares
            save(self.file, state)
        return {"saved": True}

    def password(self, body):
        password = text(body.get("password"), minimum=12)
        with self.lock:
            if not self.smb_running():
                raise StorageError(
                    "Create or reconnect a Windows share before changing its password"
                )
            self.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    CONTAINER,
                    "smbpasswd",
                    "-c",
                    "/config/smb.conf",
                    "-s",
                    "mediahub",
                ],
                content=password + "\n" + password + "\n",
            )
        return {"saved": True}

    def reconcile(self):
        with self.lock:
            state = self.state()
            previous = json.dumps(state, sort_keys=True)
            for row in state["nas"]:
                if row["enabled"]:
                    try:
                        if not self.nas_ready(row):
                            self.mount_nas(row)
                        row.pop("error", None)
                    except StorageError as error:
                        row["error"] = str(error)
            if json.dumps(state, sort_keys=True) != previous:
                save(self.file, state)
            if state["shares"] and not self.smb_running():
                self.configure_smb(state["shares"])

    def dispatch(self, method, path, body):
        if method == "GET" and path == "/status":
            return self.inventory()
        if method == "POST" and path == "/nas":
            return self.add_nas(body)
        if method == "POST" and path == "/shares":
            return self.add_share(body)
        if method == "POST" and path == "/password":
            return self.password(body)
        match = re.fullmatch(r"/nas/([a-f0-9]{24})/credentials", path)
        if method == "POST" and match:
            return self.nas_credentials(match[1], body)
        match = re.fullmatch(r"/nas/([a-f0-9]{24})/(connect|disconnect|remove)", path)
        if method == "POST" and match:
            return self.nas_action(*match.groups())
        match = re.fullmatch(r"/shares/([A-Za-z][A-Za-z0-9_-]{0,39})", path)
        if method == "DELETE" and match:
            return self.remove_share(match[1])
        raise StorageError("Unknown storage operation", 404)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log request bodies or credentials.

    def handle_request(self):
        self.connection.settimeout(15)
        try:
            _, uid, _ = struct.unpack(
                "3i", self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            if uid not in {0, 10001}:
                raise StorageError("Storage controller access denied", 403)
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 16384:
                raise StorageError("Storage request too large", 413)
            body = json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(body, dict):
                raise StorageError("Expected a storage object", 422)
            value, status = self.server.controller.dispatch(self.command, self.path, body), 200
        except StorageError as error:
            value, status = {"message": str(error)}, error.status
        except (OSError, ValueError, TypeError, KeyError):
            value, status = (
                {"message": "Storage operation could not be verified; inspect host prerequisites"},
                503,
            )
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_DELETE = handle_request


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def install(root):
    """Executed by PID1 outside the updater's read-only filesystem sandbox."""
    root = Path(root)
    script = root / "storage_host.py"
    for path in (root, script, root / "storage-policy.json"):
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise StorageError("Storage installation ownership changed")
    unit = Path("/etc/systemd/system/mediahub-storage.service")
    content = (
        "[Unit]\nDescription=MediaHub private storage controller\nAfter=network-online.target docker.service\nWants=network-online.target docker.service\n"
        "[Service]\nType=simple\nUser=root\nUMask=0077\nExecStart=/usr/bin/python3 "
        + str(script)
        + " --root "
        + str(root)
        + "\nRestart=on-failure\nRestartSec=10\n[Install]\nWantedBy=multi-user.target\n"
    )
    if unit.exists() and (
        "Description=MediaHub private storage controller" not in unit.read_text()
        or "ExecStart=/usr/bin/python3 " + str(script) + " --root " + str(root) + "\n"
        not in unit.read_text()
    ):
        raise StorageError("Storage service name is already owned by another installation")
    save(unit, content)
    command(["systemctl", "daemon-reload"])
    command(["systemctl", "enable", unit.name])
    command(["systemctl", "restart", unit.name])


def serve(root):
    controller = StorageHost(root)
    directory = Path(root) / "data/storage-control"
    if directory.is_symlink() or directory.resolve() != directory:
        raise StorageError("Unsafe storage socket directory")
    directory.mkdir(mode=0o750, exist_ok=True)
    os.chown(directory, 0, 10001)
    directory.chmod(0o750)
    path = directory / "service.sock"
    path.unlink(missing_ok=True)
    with Server(str(path), Handler) as server:
        server.controller = controller
        os.chown(path, 0, 10001)
        path.chmod(0o660)

        def reconcile():
            try:
                controller.packages()
            except StorageError:
                pass
            while True:
                try:
                    controller.reconcile()
                except (StorageError, OSError, ValueError):
                    pass
                threading.Event().wait(30)

        threading.Thread(target=reconcile, daemon=True).start()
        server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if not args.root.is_absolute() or args.root.resolve() != args.root or os.geteuid() != 0:
        raise SystemExit(
            "Storage controller requires an owned absolute installation root and root privileges"
        )
    install(args.root) if args.install else serve(args.root)
