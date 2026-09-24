"""Storage path policy shared by the agent and tests.

Directory management never reads file contents. The media browser returns bounded
metadata below approved roots, and uploads are streamed into an approved directory
without ever overwriting an existing file.
"""

import asyncio
import os
import secrets
import shutil
import stat
from collections.abc import AsyncIterable
from pathlib import Path

import psutil

from mediahub.errors import DomainError


class DirectoryPolicy:
    max_upload_bytes = 512 * 1024**3

    def __init__(self, roots: list[Path], create_enabled: bool = False):
        self.roots = [r.absolute() for r in roots]
        self.create_enabled = create_enabled

    def allowed(self, value: str, missing: bool = False) -> Path:
        path = Path(value)
        if not path.is_absolute() or ".." in path.parts:
            raise DomainError(
                "unsafe_path", "An absolute path without parent traversal is required"
            )
        path = path.absolute()
        if path == Path(path.anchor):
            raise DomainError("unsafe_path", "Filesystem roots cannot be used as storage")
        forbidden = [
            Path(p)
            for p in (
                "/etc",
                "/bin",
                "/sbin",
                "/usr",
                "/proc",
                "/sys",
                "/dev",
                "/boot",
                "/var/lib/docker",
            )
        ]
        if os.name == "nt":
            forbidden = [
                Path(os.environ.get("SystemRoot", "C:/Windows")),
                Path("C:/Program Files"),
                Path("C:/ProgramData"),
            ]
        if any(path == p or path.is_relative_to(p) for p in forbidden):
            raise DomainError("unsafe_path", "System directories are not media storage")
        if not any(path.is_relative_to(root) for root in self.roots):
            raise DomainError(
                "path_not_allowed", "Path is outside the agent's approved storage roots", 403
            )
        # Reject symlinks and Windows junction/reparse points anywhere in the chain.
        for part in [path, *path.parents]:
            try:
                info = part.lstat()
            except FileNotFoundError:
                if part == path and missing:
                    continue
                raise DomainError(
                    "missing_path", "Directory or parent directory does not exist"
                ) from None
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise DomainError("unsafe_path", "Symlinks and junctions are not allowed")
        return path

    def inspect(self, value: str):
        path = self.allowed(value, missing=True)
        exists = path.exists()
        directory = path.is_dir()
        if exists and not directory:
            raise DomainError("not_directory", "Only directories can be selected")
        details = path.stat() if directory else None
        capacity = shutil.disk_usage(path if directory else path.parent)
        filesystem = None
        matches = [
            p for p in psutil.disk_partitions(all=True) if path.is_relative_to(Path(p.mountpoint))
        ]
        if matches:
            filesystem = max(matches, key=lambda p: len(p.mountpoint)).fstype
        owner = str(details.st_uid) if details else None
        if os.name != "nt" and details:
            import pwd

            try:
                owner = pwd.getpwuid(details.st_uid).pw_name
            except KeyError:
                pass
        return {
            "path": str(path),
            "exists": exists,
            "directory": directory,
            "readable": directory and os.access(path, os.R_OK | os.X_OK),
            "writable": directory and os.access(path, os.W_OK | os.X_OK),
            "owner": owner if os.name != "nt" else "Windows ACL (advisory)",
            "uid": details.st_uid if details and os.name != "nt" else None,
            "gid": details.st_gid if details and os.name != "nt" else None,
            "permissions": stat.filemode(details.st_mode) if details else None,
            "filesystem": filesystem,
            "totalBytes": capacity.total,
            "freeBytes": capacity.free,
            "permissionCheck": "advisory-no-write-probe",
        }

    def browse(self, value: str | None = None):
        if value is None:
            return {
                "path": None,
                "parent": None,
                "folders": [{"name": p.name, "path": str(p)} for p in self.roots],
                "capacity": None,
            }
        path = self.allowed(value)
        try:
            folders = []
            with os.scandir(path) as entries:
                for entry in entries:
                    if len(folders) >= 500:
                        break
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            checked = self.allowed(entry.path)
                            folders.append({"name": checked.name, "path": str(checked)})
                        except DomainError:
                            continue
            parent = None if path in self.roots else str(path.parent)
            return {
                "path": str(path),
                "parent": parent,
                "folders": sorted(folders, key=lambda f: f["name"].lower()),
                "capacity": self.inspect(str(path)),
            }
        except OSError:
            raise DomainError("permission_denied", "Cannot list this directory", 403) from None

    def list_entries(self, value: str):
        """Return bounded metadata without opening file contents."""

        path = self.allowed(value)
        if not path.is_dir():
            raise DomainError("not_directory", "Only directories can be browsed")
        try:
            items = []
            truncated = False
            with os.scandir(path) as entries:
                for entry in entries:
                    if len(items) >= 500:
                        truncated = True
                        break
                    if entry.name.startswith(".mediahub-"):
                        continue
                    if entry.is_symlink():
                        continue
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                    if not is_directory and not is_file:
                        continue
                    try:
                        checked = self.allowed(entry.path)
                        details = entry.stat(follow_symlinks=False)
                    except (DomainError, OSError):
                        continue
                    size, complete = (
                        self._directory_size(checked) if is_directory else (details.st_size, True)
                    )
                    items.append(
                        {
                            "name": checked.name,
                            "path": str(checked),
                            "type": "folder" if is_directory else "file",
                            "sizeBytes": size,
                            "sizeComplete": complete,
                            "modifiedAt": details.st_mtime,
                        }
                    )
            items.sort(key=lambda item: (item["type"] != "folder", item["name"].lower()))
            return {
                "path": str(path),
                "items": items,
                "truncated": truncated,
            }
        except OSError:
            raise DomainError("permission_denied", "Cannot list this directory", 403) from None

    @staticmethod
    def _directory_size(path: Path) -> tuple[int, bool]:
        """Measure regular files recursively without following links or opening contents."""

        total = 0
        complete = True
        pending = [path]
        while pending:
            current = pending.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        if entry.name.startswith(".mediahub-upload-") or entry.is_symlink():
                            continue
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            complete = False
            except OSError:
                complete = False
        return total, complete

    @staticmethod
    def _upload_filename(value: str) -> str:
        if (
            not value
            or len(value.encode("utf-8")) > 255
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or "\x00" in value
            or any(ord(character) < 32 for character in value)
        ):
            raise DomainError("invalid_filename", "Choose a valid file name")
        return value

    @staticmethod
    def _write_all(stream, chunk: bytes):
        view = memoryview(chunk)
        while view:
            written = stream.write(view)
            if not written:
                raise OSError("Upload write returned no progress")
            view = view[written:]

    async def upload(
        self,
        directory_value: str,
        filename_value: str,
        chunks: AsyncIterable[bytes],
        expected_size: int | None = None,
    ):
        """Stream one new file into approved storage and never replace existing data."""

        directory = self.allowed(directory_value)
        if not directory.is_dir():
            raise DomainError("not_directory", "Upload destination must be a directory")
        if not os.access(directory, os.W_OK | os.X_OK):
            raise DomainError("permission_denied", "Upload destination is not writable", 403)
        filename = self._upload_filename(filename_value)
        destination = directory / filename
        self.allowed(str(destination), missing=not destination.exists())
        if destination.exists():
            raise DomainError(
                "file_exists", "A file with this name already exists; nothing was overwritten", 409
            )
        if expected_size is not None and (
            expected_size < 0 or expected_size > self.max_upload_bytes
        ):
            raise DomainError("upload_too_large", "This file exceeds the upload limit", 413)
        if expected_size is not None:
            free = shutil.disk_usage(directory).free
            if expected_size + 64 * 1024**2 > free:
                raise DomainError("storage_full", "Not enough free space for this upload", 507)

        temporary = directory / f".mediahub-upload-{secrets.token_hex(12)}.part"
        written = 0
        stream = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o640,
            )
            stream = os.fdopen(descriptor, "wb", buffering=0)
            async for chunk in chunks:
                if not chunk:
                    continue
                written += len(chunk)
                if written > self.max_upload_bytes:
                    raise DomainError("upload_too_large", "This file exceeds the upload limit", 413)
                await asyncio.to_thread(self._write_all, stream, chunk)
            await asyncio.to_thread(os.fsync, stream.fileno())
            await asyncio.to_thread(stream.close)
            stream = None
            if expected_size is not None and written != expected_size:
                raise DomainError(
                    "upload_incomplete", "The upload ended before the file was complete"
                )
            try:
                await asyncio.to_thread(os.link, temporary, destination, follow_symlinks=False)
            except FileExistsError:
                raise DomainError(
                    "file_exists",
                    "A file with this name already exists; nothing was overwritten",
                    409,
                ) from None
            await asyncio.to_thread(temporary.unlink)
            details = destination.stat()
            return {
                "name": destination.name,
                "path": str(destination),
                "type": "file",
                "sizeBytes": details.st_size,
                "sizeComplete": True,
                "modifiedAt": details.st_mtime,
            }
        except DomainError:
            raise
        except OSError as error:
            if getattr(error, "errno", None) == 28:
                raise DomainError(
                    "storage_full", "Storage became full during upload", 507
                ) from None
            raise DomainError("upload_failed", "The file could not be stored", 500) from None
        finally:
            if stream is not None:
                stream.close()
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def create(self, value: str, confirmed_path: str):
        if not self.create_enabled:
            raise DomainError(
                "creation_disabled", "Directory creation is disabled on this agent", 403
            )
        path = self.allowed(value, missing=True)
        if confirmed_path != str(path):
            raise DomainError("confirmation_required", "Confirm the exact path before creating it")
        if path.exists():
            raise DomainError(
                "already_exists", "Directory already exists; choose Use Existing Folder", 409
            )
        parent = self.allowed(str(path.parent))
        try:
            if os.name == "posix":
                # Walk by descriptors with O_NOFOLLOW, preventing parent-symlink swap attacks.
                descriptor = os.open(parent.anchor, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    for component in parent.parts[1:]:
                        child = os.open(
                            component,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                        os.close(descriptor)
                        descriptor = child
                    os.mkdir(path.name, mode=0o750, dir_fd=descriptor)
                finally:
                    os.close(descriptor)
            else:
                # Development only: approved roots must be private to the current Windows user.
                self.allowed(str(parent))
                path.mkdir()
        except FileExistsError:
            raise DomainError("already_exists", "Directory already exists", 409) from None
        except OSError:
            raise DomainError(
                "creation_failed", "Unable to create directory; check permissions"
            ) from None
        return self.inspect(str(path))
