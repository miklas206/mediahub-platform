"""Bounded upload chunks with atomic publication and cancellation of unfinished data."""

import asyncio
import contextlib
import json
import os
import re
import secrets
import shutil
import stat
import time
import weakref
from pathlib import Path

from mediahub.errors import DomainError

CHUNK_BYTES = 8 * 1024 * 1024


class UploadSessions:
    def __init__(self, policy, state):
        self.policy, self.state = policy, Path(state)
        self.locks = weakref.WeakValueDictionary()

    def _file(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise DomainError("invalid_upload", "Invalid upload identifier", 400)
        return self.state / (identifier + ".json")

    def _save(self, data):
        target = self._file(data["id"])
        pending = target.with_suffix(".pending")
        descriptor = os.open(
            pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, target)

    def _load(self, identifier, root):
        path = self._file(identifier)
        if path.is_symlink() or not path.is_file():
            raise DomainError("upload_not_found", "Upload session no longer exists", 404)
        data = json.loads(path.read_text())
        if data["root"] != str(Path(root)):
            raise DomainError("path_not_allowed", "Upload belongs to another media location", 403)
        self.policy.allowed(data["root"])
        self.policy.allowed(data["path"])
        return data

    @contextlib.contextmanager
    def _directory(self, value):
        path = self.policy.allowed(value)
        descriptor = None
        if os.name == "posix":
            descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for part in path.parts[1:]:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                    os.close(descriptor)
                    descriptor = child
                yield descriptor
            finally:
                os.close(descriptor)
        else:
            yield None

    @staticmethod
    def _name(data):
        return ".mediahub-upload-" + data["id"] + ".part"

    def _part(self, data, directory, flags):
        name = self._name(data)
        descriptor = os.open(
            name if directory is not None else str(Path(data["path"], name)),
            flags | getattr(os, "O_NOFOLLOW", 0),
            0o640,
            dir_fd=directory,
        )
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or (
            "inode" in data and [details.st_dev, details.st_ino] != data["inode"]
        ):
            os.close(descriptor)
            raise DomainError("invalid_upload", "Upload temporary file changed", 409)
        return descriptor

    @staticmethod
    def public(data):
        return {k: data[k] for k in ("id", "offset", "size", "complete")}

    def create(self, root, directory, filename, size):
        root = self.policy.allowed(root)
        path = self.policy.allowed(directory)
        if not path.is_relative_to(root):
            raise DomainError("path_not_allowed", "Choose a folder inside this media location", 403)
        filename = self.policy._upload_filename(filename)
        destination = self.policy.allowed(str(path / filename), missing=True)
        if destination.parent != path:
            raise DomainError("invalid_filename", "Choose a plain file name", 400)
        if not 0 <= size <= self.policy.max_upload_bytes:
            raise DomainError("upload_too_large", "This file exceeds the upload limit", 413)
        if (path / filename).exists() or (path / filename).is_symlink():
            raise DomainError("file_exists", "File already exists; nothing was overwritten", 409)
        if size + 64 * 1024**2 > shutil.disk_usage(path).free:
            raise DomainError("storage_full", "Not enough free space for this upload", 507)
        self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.state.is_symlink() or len(list(self.state.glob("*.json"))) >= 10000:
            raise DomainError("upload_limit", "Too many upload sessions; try again later", 409)
        data = dict(
            id=secrets.token_hex(16),
            root=str(root),
            path=str(path),
            filename=filename,
            size=size,
            offset=0,
            complete=False,
            updated=time.time(),
        )
        with self._directory(str(path)) as fd:
            part = self._part(data, fd, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            details = os.fstat(part)
            os.close(part)
            data["inode"] = [details.st_dev, details.st_ino]
            try:
                self._save(data)
            except BaseException:
                name = self._name(data) if fd is not None else str(path / self._name(data))
                os.unlink(name, dir_fd=fd)
                raise
        return self.public(data)

    def _commit_chunk(self, data, content):
        with self._directory(data["path"]) as fd:
            descriptor = self._part(data, fd, os.O_WRONLY)
            with os.fdopen(descriptor, "r+b", buffering=0) as stream:
                if os.fstat(stream.fileno()).st_nlink != 1:
                    raise DomainError("invalid_upload", "Upload is already published", 409)
                # Truncate any unacknowledged tail left by a process interruption.
                stream.truncate(data["offset"])
                stream.seek(data["offset"])
                self.policy._write_all(stream, content)
                os.fsync(stream.fileno())
                data["offset"] += len(content)
                data["updated"] = time.time()
                self._save(data)
        return self.public(data)

    async def chunk(self, identifier, root, offset, chunks):
        self._file(identifier)
        async with self.locks.setdefault(identifier, asyncio.Lock()):
            data = self._load(identifier, root)
            if data["complete"] or offset != data["offset"]:
                raise DomainError("upload_offset", "Upload position changed; check progress", 409)
            content = bytearray()
            async for chunk in chunks:
                if len(content) + len(chunk) > CHUNK_BYTES:
                    raise DomainError("upload_too_large", "Upload chunk exceeds 8 MiB", 413)
                content.extend(chunk)
            if not content or data["offset"] + len(content) > data["size"]:
                raise DomainError("invalid_upload", "Upload chunk has an invalid size", 400)
            if len(content) + 64 * 1024**2 > shutil.disk_usage(data["path"]).free:
                raise DomainError("storage_full", "Storage is full", 507)
            task = asyncio.create_task(asyncio.to_thread(self._commit_chunk, data, content))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                # Cancellation cannot release the session lock while a disk write runs.
                await task
                raise

    async def status(self, identifier, root):
        self._file(identifier)
        async with self.locks.setdefault(identifier, asyncio.Lock()):
            return self.public(self._load(identifier, root))

    async def finish(self, identifier, root):
        self._file(identifier)
        async with self.locks.setdefault(identifier, asyncio.Lock()):
            data = self._load(identifier, root)
            if data["complete"]:
                return self.public(data)
            if data["offset"] != data["size"]:
                raise DomainError("upload_incomplete", "Upload has not finished", 409)
            with self._directory(data["path"]) as fd:
                part = self._part(data, fd, os.O_RDONLY)
                try:
                    if os.fstat(part).st_size != data["size"]:
                        raise DomainError("upload_incomplete", "Upload size does not match", 409)
                    source = (
                        self._name(data)
                        if fd is not None
                        else str(Path(data["path"], self._name(data)))
                    )
                    target = (
                        data["filename"]
                        if fd is not None
                        else str(Path(data["path"], data["filename"]))
                    )
                    try:
                        os.link(source, target, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                    except FileExistsError:
                        existing = os.stat(target, dir_fd=fd, follow_symlinks=False)
                        if [existing.st_dev, existing.st_ino] != data["inode"]:
                            raise DomainError(
                                "file_exists", "File already exists; nothing was overwritten", 409
                            ) from None
                    data["complete"] = True
                    data["updated"] = time.time()
                    self._save(data)
                finally:
                    os.close(part)
                os.unlink(source, dir_fd=fd)
            return self.public(data)

    async def cancel(self, identifier, root):
        self._file(identifier)
        async with self.locks.setdefault(identifier, asyncio.Lock()):
            if not self._file(identifier).exists():
                return {"cancelled": True}
            data = self._load(identifier, root)
            with self._directory(data["path"]) as fd:
                try:
                    part = self._part(data, fd, os.O_RDONLY)
                except FileNotFoundError:
                    pass
                else:
                    os.close(part)
                    name = (
                        self._name(data)
                        if fd is not None
                        else str(Path(data["path"], self._name(data)))
                    )
                    os.unlink(name, dir_fd=fd)
            # Final files are never deleted, even if Stop races with completion.
            self._file(identifier).unlink(missing_ok=True)
            return {"cancelled": not data["complete"], "complete": data["complete"]}

    async def cleanup(self):
        while True:
            for path in list(self.state.glob("*.json"))[:10000]:
                try:
                    if path.is_symlink():
                        continue
                    data = json.loads(path.read_text())
                    if time.time() - data["updated"] > 24 * 3600:
                        await self.cancel(path.stem, data["root"])
                except (OSError, ValueError, KeyError, DomainError):
                    continue
            await asyncio.sleep(1800)
