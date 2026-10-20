import asyncio
import os
import subprocess
import sys

import pytest

from agent.plex_lifecycle_lock import PlexLifecycleLock

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux Docker host lifecycle")


def child(path):
    return subprocess.Popen([sys.executable, "-u", "-c",
        "import fcntl,sys,time;f=open(sys.argv[1],'a');"
        "fcntl.flock(f,fcntl.LOCK_EX);print('locked',flush=True);time.sleep(30)", str(path)],
        stdout=subprocess.PIPE, text=True)


def test_supervisor_waits_for_other_process_and_process_exit_releases_lock(tmp_path):
    path = tmp_path / "lifecycle.lock"
    process = child(path)
    try:
        assert process.stdout.readline().strip() == "locked"

        async def run():
            entered = asyncio.Event()
            lock = PlexLifecycleLock(path)

            async def supervisor():
                async with lock:
                    entered.set()
            task = asyncio.create_task(supervisor())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(entered.wait(), 0.1)
            process.terminate()
            process.wait(timeout=3)
            await asyncio.wait_for(task, 3)
            assert entered.is_set() and not lock.locked()
        asyncio.run(run())
    finally:
        process.terminate()
        process.wait(timeout=3)


def test_cancelled_waiter_releases_local_lock_and_file_descriptor(tmp_path):
    path = tmp_path / "lifecycle.lock"
    process = child(path)
    try:
        assert process.stdout.readline().strip() == "locked"
        async def run():
            lock = PlexLifecycleLock(path)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(lock.__aenter__(), 0.1)
            assert not lock.locked() and lock.fd is None
            process.terminate()
            process.wait(timeout=3)
            async with lock:
                pass
        asyncio.run(run())
    finally:
        process.terminate()
        process.wait(timeout=3)
