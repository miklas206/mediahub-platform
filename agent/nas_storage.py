"""Read host-observed NAS readiness; no NAS credentials are available to Agent."""

import json
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from mediahub.errors import DomainError


def plex_nas_ready(policy, folder):
    identifiers = [
        m.target.removeprefix("/media/nas/")
        for m in policy.mounts
        if m.target.startswith("/media/nas/")
    ]
    if not identifiers:
        return True
    try:
        status = json.loads((Path(folder) / "nas-storage-status.json").read_text())
        return 0 <= time.time() - status["observedAt"] <= 75 and all(
            status["nas"].get(identifier) is True for identifier in identifiers
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


@contextmanager
def app_storage_guard(folder):
    path = Path(folder) / "app-storage.lock"
    if not path.exists():
        yield
        return
    if path.is_symlink():
        raise DomainError(
            "app_storage_busy", "App storage ownership changed; keep the app stopped", 409
        )
    import fcntl

    with path.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DomainError(
                "app_storage_busy", "Wait for the app storage change to finish", 409
            ) from None
        yield


def storage_operation(method):
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        with app_storage_guard(self.state_dir):
            return await method(self, *args, **kwargs)

    return guarded
