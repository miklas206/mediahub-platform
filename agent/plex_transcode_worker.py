"""Bounded filesystem work for the isolated, app-UID transcode helper."""

import errno
import json
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

MARKER = ".mediahub-plex-transcode.json"


def traversal_acl(raw, mode):
    """Add execute-only access for the namespace root; preserve other grants."""
    if raw:
        if len(raw) < 4 or (len(raw) - 4) % 8 or struct.unpack("<I", raw[:4])[0] != 2:
            raise ValueError("Invalid temporary storage ACL")
        entries = [list(struct.unpack("<HHI", raw[i : i + 8])) for i in range(4, len(raw), 8)]
    else:
        entries = [
            [1, (mode >> 6) & 7, 0xFFFFFFFF],
            [4, (mode >> 3) & 7, 0xFFFFFFFF],
            [32, mode & 7, 0xFFFFFFFF],
        ]
    masks = [e for e in entries if e[0] == 16]
    mask = masks[0][1] if masks else ((mode >> 3) & 7) | 1
    if not mask & 1:
        raise PermissionError("Temporary storage ACL mask must allow directory traversal")
    root = next((e for e in entries if e[0] == 2 and e[2] == 0), None)
    if root is None:
        entries.append([2, 1, 0])
    else:
        root[1] |= 1
    if not masks:
        entries.append([16, mask, 0xFFFFFFFF])
    entries.sort(key=lambda e: (e[0], e[2]))
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *e) for e in entries)


def grant_daemon_traversal(paths):
    mapping = Path("/proc/self/uid_map")
    if not mapping.exists():
        return
    rows = [list(map(int, line.split())) for line in mapping.read_text().splitlines()]
    if not any(inside == 0 and outside != 0 for inside, outside, _ in rows):
        return  # Native root can traverse; an unprivileged LXC root cannot.
    for path in paths:
        try:
            raw = os.getxattr(path, "system.posix_acl_access")
        except OSError as error:
            if error.errno != errno.ENODATA:
                raise
            raw = None
        updated = traversal_acl(raw, path.stat().st_mode)
        if updated != raw:
            os.setxattr(path, "system.posix_acl_access", updated)


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
    # Docker's root in an unprivileged LXC needs to stat the bind source.
    # Grant only traversal, retaining private markers/files and other ACLs.
    parents = [parent]
    for part in parts:
        parents.append(parents[-1] / part)
    grant_daemon_traversal([*parents, work])
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
