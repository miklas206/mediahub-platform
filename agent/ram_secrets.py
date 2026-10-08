"""Fail-closed RAM materialization. No disk fallback or secret-valued errors."""

import json
import os
import stat
from pathlib import Path

from mediahub.secret_store import SecretStore


def verify_ram_directory(directory: Path):
    if os.name != "posix" or not directory.is_absolute() or directory.resolve() != directory:
        raise ValueError("RAM-backed private storage required")
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Unsafe RAM directory permissions")
    matches = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        fields, fs = left.split(), right.split()
        mount = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
        if directory == mount or mount in directory.parents:
            matches.append(
                (len(str(mount)), fs[0], set(fields[5].split(",")) | set(fs[2].split(",")))
            )
    if not matches:
        raise ValueError("RAM mount verification unavailable")
    _, filesystem, options = max(matches)
    if filesystem != "tmpfs" or not {"noexec", "nosuid", "nodev", "noswap"} <= options:
        raise ValueError("Private runtime requires protected non-swappable tmpfs")
    if len(Path("/proc/swaps").read_text().splitlines()) != 1:
        raise ValueError("Swap must be disabled for secret-bearing processes")


class RuntimeSecrets:
    def __init__(self, root: Path):
        self.root = root
        self.directory = root / "secrets"
        self.store = SecretStore(root / "vault")

    def _write(self, name, payload):
        # Preserve inode for an existing read-only Docker file bind.
        if name not in {"vpn.conf", "qbit.json"} or (self.directory / name).is_symlink():
            raise ValueError("Unsafe runtime secret path")
        fd = os.open(
            self.directory / name, os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077))
            ):
                raise ValueError("Unsafe runtime secret file")
            stream.truncate(0)
            stream.write(payload)
            stream.flush()

    def materialize(self):
        verify_ram_directory(self.directory)
        payload = json.loads(self.store.get("seedbox-runtime"))
        if set(payload) != {"vpnConfig", "webUsername", "webPassword"} or not all(
            isinstance(value, str) and value for value in payload.values()
        ):
            raise ValueError("Invalid runtime private record")
        self._write("vpn.conf", payload["vpnConfig"].encode())
        self._write(
            "qbit.json",
            json.dumps(
                {"username": payload["webUsername"], "password": payload["webPassword"]}
            ).encode(),
        )

    def clear(self):
        verify_ram_directory(self.directory)
        for name in ("vpn.conf", "qbit.json"):
            self._write(name, b"")
