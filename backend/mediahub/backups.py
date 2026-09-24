"""Portable encrypted Core backups; never traverse media or write plaintext archives."""

import io
import json
import os
import re
import sqlite3
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from mediahub import __version__
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

MAGIC = b"MEDIAHUB-BACKUP-1\n"
LIMIT = 64 * 1024 * 1024


def derive(password, salt):
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())


def decrypt_archive(payload, password):
    """Offline verification primitive; never extract or replace a running installation."""
    if not payload.startswith(MAGIC) or len(payload) > LIMIT + 1024 * 1024:
        raise ValueError("Unsupported backup envelope")
    offset = len(MAGIC)
    salt, nonce = payload[offset : offset + 16], payload[offset + 16 : offset + 28]
    return AESGCM(derive(password, salt)).decrypt(nonce, payload[offset + 28 :], MAGIC)


def verified_members(payload, password):
    """Bounded offline verification. No extraction, execution or destination writes."""
    with zipfile.ZipFile(io.BytesIO(decrypt_archive(payload, password))) as archive:
        members = archive.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > LIMIT:
            raise ValueError("Backup exceeds the supported size")
        names = [m.filename for m in members]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive paths")
        allowed = {"manifest.json", "core/mediahub.db", "core/secrets.key"}
        for member in members:
            path = PurePosixPath(member.filename)
            if (
                member.is_dir()
                or ".." in path.parts
                or path.is_absolute()
                or path.as_posix() != member.filename
                or "\\" in member.filename
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError("Unsafe archive path")
            private = (
                len(path.parts) == 3
                and path.parts[0] == "core"
                and path.parts[1] in {"private-records", "security-secrets"}
                and (
                    path.name == "master.key"
                    or re.fullmatch(r"[a-z][a-z0-9_-]{2,80}\.sealed", path.name)
                )
                and path.stem.lower()
                not in {
                    "con",
                    "prn",
                    "aux",
                    "nul",
                    *[f"com{i}" for i in range(10)],
                    *[f"lpt{i}" for i in range(10)],
                }
            )
            if member.filename not in allowed and not private:
                raise ValueError("Unsupported archive content")
        if not allowed.issubset(names):
            raise ValueError("Incomplete Core backup")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != 1 or manifest.get("scope") != "core-configuration":
            raise ValueError("Unsupported backup format")
        result = {name: archive.read(name) for name in names if name.startswith("core/")}
        connection = sqlite3.connect(":memory:")
        try:
            connection.deserialize(result["core/mediahub.db"])
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Invalid database backup")
        finally:
            connection.close()
        return manifest, result


def restore_new_directory(payload, password, destination: Path):
    """Restore only to a NEW directory. Never replace running state or media."""
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise ValueError("Choose a new absolute directory; existing paths are never overwritten")
    if destination.parent.resolve() != destination.parent or not destination.parent.is_dir():
        raise ValueError("Restore parent must exist without symlinks")
    manifest, members = verified_members(payload, password)
    destination.mkdir(mode=0o700, exist_ok=False)
    for name, content in members.items():
        target = destination.joinpath(*PurePosixPath(name).parts[1:])
        target.parent.mkdir(mode=0o700, exist_ok=True)
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    return manifest


class CoreBackup:
    def __init__(self, svc):
        self.svc = svc

    def create(self, password):
        root = self.svc.config.data_dir.resolve()
        # Keep SQLite's online snapshot in memory, so WAL remains consistent.
        source = sqlite3.connect(f"file:{(root / 'mediahub.db').as_posix()}?mode=ro", uri=True)
        snapshot = sqlite3.connect(":memory:")
        try:
            source.backup(snapshot)
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DomainError("backup_database_invalid", "Database integrity check failed", 409)
            # Restoring a backup must not revive authenticated browser sessions or pairing tokens.
            snapshot.execute("DELETE FROM sessions")
            for table in ("pairing_requests",):
                if snapshot.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    snapshot.execute(f"DELETE FROM {table}")
            snapshot.commit()
            database = snapshot.serialize()
            # The online snapshot includes WAL pages, but SQLite deserialize cannot
            # reopen a WAL header in RAM. SQLite documents normalizing these two
            # file-format bytes: https://www.sqlite.org/c3ref/deserialize.html
            database = database[:18] + b"\x01\x01" + database[20:]
        finally:
            snapshot.close()
            source.close()
        total = len(database)
        if total > LIMIT:
            raise DomainError(
                "backup_too_large", "Core config exceeds the in-memory backup limit", 409
            )
        output = io.BytesIO()
        records = []
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("core/mediahub.db", database)
            # App configuration and paired-Agent tokens in SQLite use this key.
            # It is included only INSIDE the password-encrypted envelope.
            archive.writestr("core/secrets.key", SecretStore._read(root / "secrets.key", 128))
            # Deliberate allowlist: no media, logs, arbitrary external mounts or bootstrap token.
            for folder in ("private-records", "security-secrets"):
                directory = root / folder
                if not directory.exists():
                    continue
                if directory.is_symlink() or directory.resolve().parent != root:
                    raise DomainError("backup_path_unsafe", "Private config path is unsafe", 409)
                for path in sorted(directory.iterdir()):
                    if path.is_symlink():
                        raise DomainError(
                            "backup_path_unsafe", "Private config contains a link", 409
                        )
                    info = path.stat()
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1
                        or info.st_size > 262144
                    ):
                        raise DomainError(
                            "backup_path_unsafe", "Private config file is unsafe", 409
                        )
                    if path.name != "master.key" and path.suffix != ".sealed":
                        continue
                    total += info.st_size
                    if total > LIMIT:
                        raise DomainError(
                            "backup_too_large", "Core config exceeds backup limit", 409
                        )
                    # O_NOFOLLOW closes the symlink race on supported platforms.
                    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as stream:
                        current = os.fstat(stream.fileno())
                        if (current.st_dev, current.st_ino, current.st_size) != (
                            info.st_dev,
                            info.st_ino,
                            info.st_size,
                        ):
                            raise DomainError(
                                "backup_changed", "Config changed; retry the backup", 409
                            )
                        archive.writestr(
                            "core/" + path.relative_to(root).as_posix(), stream.read(262145)
                        )
                    records.append(path.relative_to(root).as_posix())
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": 1,
                        "version": __version__,
                        "createdAt": time.time(),
                        "scope": "core-configuration",
                        "privateRecords": records,
                        "mediaIncluded": False,
                        "appRuntimeDataIncluded": False,
                        "externalDeploymentFilesIncluded": False,
                        "sessionsInvalidated": True,
                    }
                ),
            )
        salt, nonce = os.urandom(16), os.urandom(12)
        payload = (
            MAGIC
            + salt
            + nonce
            + AESGCM(derive(password, salt)).encrypt(nonce, output.getvalue(), MAGIC)
        )
        # Full authenticated round trip + CRC validation before handing the backup out.
        with zipfile.ZipFile(io.BytesIO(decrypt_archive(payload, password))) as archive:
            if archive.testzip() is not None:
                raise DomainError("backup_invalid", "Backup verification failed", 503)
            restored = sqlite3.connect(":memory:")
            try:
                restored.deserialize(archive.read("core/mediahub.db"))
                if restored.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DomainError(
                        "backup_invalid", "Restored database verification failed", 503
                    )
            finally:
                restored.close()
        return payload
