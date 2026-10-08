"""Small, durable private metadata files; never a plaintext secret store."""

import json
import os
import tempfile
from pathlib import Path


def read_json(path: Path):
    if path.is_symlink() or path.stat().st_size > 262144:
        raise ValueError("Unsafe metadata file")
    return json.loads(path.read_text())


def save_json(path: Path, data):
    if path.is_symlink() or path.parent.resolve() != path.parent:
        raise ValueError("Unsafe metadata path")
    fd, name = tempfile.mkstemp(prefix=".metadata-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if os.name != "nt":
            parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        Path(name).unlink(missing_ok=True)
