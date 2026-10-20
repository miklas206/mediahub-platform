"""Serialize the supervisor and operator processes using the same private state."""
import asyncio
import os
from pathlib import Path


class PlexLifecycleLock:
    def __init__(self, path):
        self.path = Path(path)
        self.local = asyncio.Lock()
        self.fd = None

    def locked(self):
        return self.local.locked()

    async def __aenter__(self):
        import fcntl

        await self.local.acquire()
        fd = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    await asyncio.sleep(0.05)
            self.fd = fd
            return self
        except BaseException:
            if fd is not None:
                os.close(fd)
            self.local.release()
            raise

    async def __aexit__(self, *exception):
        os.close(self.fd)
        self.fd = None
        self.local.release()
