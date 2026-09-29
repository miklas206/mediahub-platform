import errno
import os
from pathlib import Path
from types import SimpleNamespace

import mediahub.path_policy as policy_module
import pytest
from mediahub.errors import DomainError
from mediahub.path_policy import DirectoryPolicy


def test_linux_traversal_does_not_require_ancestor_read_permission(tmp_path, monkeypatch):
    root = tmp_path / "search-only" / "media"
    root.mkdir(parents=True)
    policy = DirectoryPolicy([root], True)
    target = root / "Film"
    flags = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
    flags.name = "posix"
    flags.O_PATH = 0x200000
    flags.O_DIRECTORY = 0x10000
    flags.O_NOFOLLOW = 0x20000
    seen = []

    def opened(path, value, dir_fd=None):
        seen.append((str(path), value))
        if str(path) == "search-only" and not value & flags.O_PATH:
            raise PermissionError(errno.EACCES, "Parent is searchable but not readable")
        return len(seen) + 10

    flags.open = opened
    flags.close = lambda _: None
    flags.mkdir = lambda name, mode, dir_fd: target.mkdir()
    monkeypatch.setattr(policy_module, "os", flags)
    monkeypatch.setattr(policy, "inspect", lambda value: {"path": value, "exists": True})
    assert policy.create(str(target), str(target))["exists"]
    assert target.is_dir()
    assert any(path == "search-only" for path, _ in seen)
    assert all(value & flags.O_DIRECTORY and value & flags.O_NOFOLLOW for _, value in seen)


@pytest.mark.parametrize(
    "number,reason,status",
    [
        (errno.EACCES, "Permission denied", 403),
        (errno.EROFS, "mounted read-only", 403),
        (errno.ENOSPC, "free space or inodes", 507),
        (errno.ENAMETOOLONG, "filesystem limit", 400),
    ],
)
def test_mkdir_errors_preserve_real_cause(tmp_path, monkeypatch, number, reason, status):
    policy = DirectoryPolicy([tmp_path], True)
    target = tmp_path / "Film"

    def fail(*args, **kwargs):
        raise OSError(number, "test filesystem failure")

    if os.name == "posix":
        monkeypatch.setattr(policy_module.os, "mkdir", fail)
    else:
        monkeypatch.setattr(Path, "mkdir", fail)
    with pytest.raises(DomainError) as caught:
        policy.create(str(target), str(target))
    assert reason in caught.value.message
    assert errno.errorcode[number] in caught.value.message
    assert str(target) in caught.value.message
    assert caught.value.status == status


@pytest.mark.skipif(
    not hasattr(os, "O_PATH") or not hasattr(os, "fork"), reason="Linux permissions"
)
def test_real_linux_search_only_ancestor_allows_folder_and_chunked_upload():
    import asyncio
    import tempfile

    from agent.uploads import UploadSessions

    with tempfile.TemporaryDirectory(prefix="mediahub-search-access-") as temporary:
        base = Path(temporary)
        base.chmod(0o755)
        ancestor = base / "search-only"
        ancestor.mkdir()
        root = ancestor / "media"
        root.mkdir()
        root.chmod(0o777)
        ancestor.chmod(0o111)
        child = os.fork()
        if child == 0:
            try:
                if os.geteuid() == 0:
                    os.setgroups([])
                    os.setgid(65534)
                    os.setuid(65534)
                try:
                    fd = os.open(ancestor, os.O_RDONLY | os.O_DIRECTORY)
                except PermissionError:
                    pass
                else:
                    os.close(fd)
                    raise AssertionError("Old traversal should fail without read permission")
                policy = DirectoryPolicy([root], True)
                folder = root / "Movie"
                policy.create(str(folder), str(folder))
                uploads = UploadSessions(policy, root / "state")
                session = uploads.create(str(root), str(folder), "test.mkv", 3)

                async def chunks():
                    yield b"abc"

                async def upload():
                    await uploads.chunk(session["id"], str(root), 0, chunks())
                    await uploads.finish(session["id"], str(root))

                asyncio.run(upload())
                assert (folder / "test.mkv").read_bytes() == b"abc"
                os._exit(0)
            except BaseException:
                import traceback

                traceback.print_exc()
                os._exit(1)
        try:
            _, status = os.waitpid(child, 0)
            assert os.waitstatus_to_exitcode(status) == 0
        finally:
            ancestor.chmod(0o755)
