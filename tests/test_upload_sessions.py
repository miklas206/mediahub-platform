import asyncio
import json
import os
from types import SimpleNamespace

import pytest
from mediahub.errors import DomainError
from mediahub.path_policy import DirectoryPolicy

from agent.uploads import CHUNK_BYTES, UploadSessions


async def body(*chunks):
    for chunk in chunks:
        yield chunk


@pytest.fixture
def uploads(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    return UploadSessions(DirectoryPolicy([media], True), tmp_path / "state"), media


def test_interrupted_chunk_never_advances_and_restart_recovers(uploads):
    service, root = uploads
    session = service.create(str(root), str(root), "movie.mkv", 9)
    identifier = session["id"]

    async def disconnected():
        yield b"abc"
        raise ConnectionError("browser disconnected")

    async def exercise():
        with pytest.raises(ConnectionError):
            await service.chunk(identifier, str(root), 0, disconnected())
        assert (await service.status(identifier, str(root)))["offset"] == 0
        await service.chunk(identifier, str(root), 0, body(b"abc"))
        restarted = UploadSessions(service.policy, service.state)
        assert (await restarted.status(identifier, str(root)))["offset"] == 3
        await restarted.chunk(identifier, str(root), 3, body(b"def", b"ghi"))
        await restarted.finish(identifier, str(root))
        # Lost finish response is safe to retry; Stop never removes published media.
        assert (await restarted.finish(identifier, str(root)))["complete"]
        assert (await restarted.cancel(identifier, str(root)))["complete"]

    asyncio.run(exercise())
    assert (root / "movie.mkv").read_bytes() == b"abcdefghi"
    assert not list(root.glob("*.part"))


def test_chunk_bounds_and_location_isolation(uploads):
    service, root = uploads
    other = root / "other"
    other.mkdir()
    identifier = service.create(str(root), str(root), "movie.mkv", CHUNK_BYTES + 1)["id"]

    async def exercise():
        with pytest.raises(DomainError, match="another media location"):
            await service.cancel(identifier, str(other))
        with pytest.raises(DomainError, match="exceeds 8 MiB"):
            await service.chunk(identifier, str(root), 0, body(b"x" * CHUNK_BYTES, b"x"))
        assert (await service.status(identifier, str(root)))["offset"] == 0
        await service.cancel(identifier, str(root))
        assert not list(root.glob(".mediahub-upload-*.part"))

    asyncio.run(exercise())


def test_competing_destination_is_not_overwritten(uploads):
    service, root = uploads
    identifier = service.create(str(root), str(root), "movie.mkv", 3)["id"]

    async def exercise():
        await service.chunk(identifier, str(root), 0, body(b"new"))
        (root / "movie.mkv").write_bytes(b"original")
        with pytest.raises(DomainError, match="nothing was overwritten"):
            await service.finish(identifier, str(root))
        await service.cancel(identifier, str(root))

    asyncio.run(exercise())
    assert (root / "movie.mkv").read_bytes() == b"original"


def test_large_file_metadata_does_not_allocate_whole_file(uploads, monkeypatch):
    service, root = uploads
    monkeypatch.setattr("agent.uploads.shutil.disk_usage", lambda _: SimpleNamespace(free=1024**4))
    session = service.create(str(root), str(root), "large.mkv", 100 * 1024**3)
    assert session["size"] == 100 * 1024**3
    assert next(root.glob(".mediahub-upload-*.part")).stat().st_size == 0
    asyncio.run(service.cancel(session["id"], str(root)))


def test_cancel_waits_for_inflight_commit(uploads, monkeypatch):
    import threading

    service, root = uploads
    identifier = service.create(str(root), str(root), "movie.mkv", 6)["id"]
    entered, release = threading.Event(), threading.Event()
    commit = service._commit_chunk

    def delayed(data, content):
        entered.set()
        assert release.wait(5)
        return commit(data, content)

    monkeypatch.setattr(service, "_commit_chunk", delayed)

    async def exercise():
        task = asyncio.create_task(service.chunk(identifier, str(root), 0, body(b"abc")))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        stopped = asyncio.create_task(service.cancel(identifier, str(root)))
        await asyncio.sleep(0)
        assert not stopped.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stopped

    asyncio.run(exercise())
    assert not list(root.iterdir())


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink/descriptor protection")
def test_symlink_swap_and_temporary_replacement_are_rejected(uploads, tmp_path):
    service, root = uploads
    child = root / "film"
    child.mkdir()
    identifier = service.create(str(root), str(child), "movie.mkv", 3)["id"]
    child.rename(root / "original")
    child.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DomainError, match="Symlinks"):
        asyncio.run(service.chunk(identifier, str(root), 0, body(b"abc")))
    child.unlink()
    (root / "original").rename(child)
    temporary = next(child.glob(".mediahub-upload-*.part"))
    temporary.rename(child / "original.part")
    temporary.write_bytes(b"unrelated")
    with pytest.raises(DomainError, match="temporary file changed"):
        asyncio.run(service.cancel(identifier, str(root)))
    assert temporary.read_bytes() == b"unrelated"


def test_stale_session_cleanup_keeps_final_files(uploads, monkeypatch):
    service, root = uploads
    identifier = service.create(str(root), str(root), "empty.mkv", 0)["id"]
    asyncio.run(service.finish(identifier, str(root)))
    path = service._file(identifier)
    data = json.loads(path.read_text())
    data["updated"] = 0
    path.write_text(json.dumps(data))

    async def end_loop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr("agent.uploads.asyncio.sleep", end_loop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.cleanup())
    assert (root / "empty.mkv").is_file()
    assert not path.exists()
