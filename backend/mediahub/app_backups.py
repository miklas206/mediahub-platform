"""Bounded encrypted app configuration archives; never include media storage."""

import io
import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mediahub.backups import derive

MAGIC = b"MEDIAHUB-APP-BACKUP-1\n"
LIMIT = 48 * 1024**2


def create_archive(app, roots, password, extra_entries=None):
    if app not in {"plex", "seedbox"} or not 16 <= len(password) <= 256:
        raise ValueError("Invalid app backup request")
    entries = dict(extra_entries or {})
    size = sum(len(value) for value in entries.values())
    if size > LIMIT:
        raise ValueError("Configuration exceeds bounded export size")
    for label, root in roots.items():
        label_path = PurePosixPath(label)
        if (
            label_path.is_absolute()
            or ".." in label_path.parts
            or label_path.as_posix() != label
            or "\\" in label
            or ":" in label
        ):
            raise ValueError("Unsafe archive root")
        root = Path(root)
        if not root.exists():
            continue
        if root.is_symlink():
            raise ValueError("Symbolic configuration path refused")
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if path.is_symlink():
                raise ValueError("Symbolic configuration entry refused")
            if path.is_dir():
                continue
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Non-file configuration entry refused")
            size += info.st_size
            if size > LIMIT or len(entries) >= 10000:
                raise ValueError("Configuration exceeds bounded export size")
            name = label if path == root else label + "/" + path.relative_to(root).as_posix()
            with path.open("rb") as source:
                entries[name] = source.read(min(info.st_size + 1, LIMIT + 1))
            if len(entries[name]) != info.st_size:
                raise ValueError("Configuration changed during backup")
    if not entries:
        raise ValueError("No configuration found")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"format": 1, "app": app, "mediaIncluded": False, "files": len(entries)}),
        )
        for name, data in entries.items():
            archive.writestr(name, data)
    salt, nonce = os.urandom(16), os.urandom(12)
    payload = (
        MAGIC
        + salt
        + nonce
        + AESGCM(derive(password, salt)).encrypt(nonce, stream.getvalue(), MAGIC)
    )
    verify_archive(payload, password)
    return payload


def verified_members(payload, password):
    if not payload.startswith(MAGIC) or len(payload) > LIMIT + 1024**2:
        raise ValueError("Unsupported app archive")
    offset = len(MAGIC)
    salt = payload[offset : offset + 16]
    nonce = payload[offset + 16 : offset + 28]
    raw = AESGCM(derive(password, salt)).decrypt(nonce, payload[offset + 28 :], MAGIC)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        names = [m.filename for m in files]
        if (
            len(files) > 10001
            or len(names) != len(set(names))
            or sum(m.file_size for m in files) > LIMIT + 65536
        ):
            raise ValueError("Invalid app archive limits")
        for m in files:
            p = PurePosixPath(m.filename)
            if (
                m.is_dir()
                or p.is_absolute()
                or ".." in p.parts
                or p.as_posix() != m.filename
                or "\\" in m.filename
                or ":" in m.filename
                or stat.S_ISLNK(m.external_attr >> 16)
            ):
                raise ValueError("Unsafe archive path")
        manifest = json.loads(archive.read("manifest.json"))
        if (
            manifest.get("app") not in {"plex", "seedbox"}
            or manifest.get("format") != 1
            or manifest.get("mediaIncluded") is not False
        ):
            raise ValueError("Invalid app archive scope")
        if manifest.get("files") != len(files) - 1:
            raise ValueError("Invalid app archive count")
        # Read every member to validate CRCs as well as the authenticated envelope.
        return manifest, {
            m.filename: archive.read(m) for m in files if m.filename != "manifest.json"
        }


def verify_archive(payload, password):
    return verified_members(payload, password)[0]


def restore_new_directory(payload, password, destination):
    """Offline staging only: never map archive paths onto a live app or media."""
    destination = Path(destination)
    if not destination.is_absolute() or destination.exists() or destination.is_symlink():
        raise ValueError("A new absolute destination is required")
    if any(parent.is_symlink() for parent in destination.parents):
        raise ValueError("Symbolic destination parent refused")
    manifest, members = verified_members(payload, password)
    destination.mkdir(mode=0o700, exist_ok=False)
    for name, data in members.items():
        target = destination.joinpath(*PurePosixPath(name).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    return manifest
