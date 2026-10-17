"""Bounded filesystem work for the isolated, app-UID transcode helper."""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

MARKER = ".mediahub-plex-transcode.json"


def prepare(parent, relative, identity, *, minimum_free=1024**3, clean=False):
    parent = Path(parent)
    root = parent
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts):
        raise ValueError("Invalid temporary directory")
    if parent.resolve() != parent or not parent.is_dir():
        raise ValueError("Temporary storage parent changed")
    created = False
    for index, part in enumerate(parts):
        root = root / part
        if root.is_symlink():
            raise ValueError("Temporary storage cannot contain symlinks")
        if not root.exists():
            root.mkdir(mode=0o700 if index == len(parts) - 1 else 0o750)
            if index == len(parts) - 1:
                created = True
        if not root.is_dir():
            raise ValueError("Temporary storage path is not a directory")
    marker = root / MARKER
    if marker.is_symlink():
        raise ValueError("Temporary storage marker changed")
    expected = {"installationId": identity, "purpose": "plex-transcoding"}
    if marker.exists():
        if json.loads(marker.read_text()) != expected:
            raise ValueError("Temporary storage belongs to another installation")
    elif created or not any(root.iterdir()):
        with marker.open("x") as stream:
            json.dump(expected, stream)
        marker.chmod(0o600)
    else:
        raise ValueError("Existing temporary directory has no ownership marker")
    # Keep ownership metadata outside the directory exposed to Plex, which is
    # free to clear its own temporary work tree.
    work = root / "work"
    if work.is_symlink():
        raise ValueError("Temporary work directory changed")
    work.mkdir(mode=0o700, exist_ok=True)
    if not work.is_dir():
        raise ValueError("Temporary work path is not a directory")
    removed = 0
    # The caller must verify Plex is stopped. Runtime session cleanup belongs
    # to Plex itself; never race its active or paused streams with an age timer.
    if clean:
        sessions = work / "Transcode" / "Sessions"
        if sessions.exists():
            if sessions.is_symlink() or sessions.resolve() != sessions:
                raise ValueError("Session directory changed")
            for directory in sessions.iterdir():
                if not re.fullmatch(r"plex-transcode-[A-Za-z0-9_-]{8,}", directory.name):
                    continue
                if directory.is_symlink() or not directory.is_dir():
                    continue
                if any(p.is_symlink() for p in directory.rglob("*")):
                    continue
                shutil.rmtree(directory)
                removed += 1
    # statvfs on a pooled mount can report free space on a different branch.
    # Verify real allocation as the exact application UID as well. Clean dead
    # sessions first so their space can be reclaimed on a full temporary disk.
    with tempfile.NamedTemporaryFile(prefix=".mediahub-space-probe-", dir=work) as stream:
        stream.write(b"\0" * 4096)
        stream.flush()
        os.fsync(stream.fileno())
    space = shutil.disk_usage(work)
    if space.free < minimum_free:
        raise OSError(28, "Temporary storage has less than 1 GiB free")
    return {"freeBytes": space.free, "removedSessions": removed}
