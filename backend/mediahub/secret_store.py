"""Generic encrypted records. Protected local key permits unattended startup.

Callers own the operation lock. Decrypted values must never reach durable files,
logs or public responses. This does not protect against a compromised host root.
"""

import os
import re
import stat as file_stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from mediahub.errors import DomainError


class SecretStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def _root(self, create=False):
        root = self.directory
        if not root.is_absolute() or root.resolve() != root:
            raise DomainError("secret_store_unsafe", "Private storage path is unsafe", 503)
        if create:
            root.mkdir(mode=0o700, exist_ok=True)
        if not root.is_dir():
            raise DomainError("secret_store_missing", "Private configuration is not available", 409)
        if os.name != "nt" and (root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077):
            raise DomainError(
                "secret_store_permissions", "Private storage permissions are unsafe", 503
            )
        return root

    def _path(self, reference):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{2,80}", reference):
            raise DomainError(
                "invalid_secret_reference", "Invalid private configuration reference", 422
            )
        return self.directory / (reference + ".sealed")

    @staticmethod
    def _read(path, limit):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        if path.is_symlink():
            raise ValueError("Unsafe secret file")
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            stat = os.fstat(stream.fileno())
            if (
                not file_stat.S_ISREG(stat.st_mode)
                or stat.st_nlink != 1
                or stat.st_size > limit
                or (os.name != "nt" and (stat.st_uid != os.getuid() or stat.st_mode & 0o077))
            ):
                raise ValueError("Unsafe secret file permissions or size")
            return stream.read(limit + 1)

    def _cipher(self, create=False):
        path = self._root(create) / "master.key"
        if create and not path.exists():
            try:
                fd = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
                )
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(Fernet.generate_key())
                    stream.flush()
                    os.fsync(stream.fileno())
        return Fernet(self._read(path, 128))

    def put(self, reference, payload: bytes):
        destination = self._path(reference)
        cipher = self._cipher(create=True)
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= 131072:
            raise ValueError("Invalid private record")
        encrypted = cipher.encrypt(payload)
        try:
            fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except FileExistsError:
            raise DomainError(
                "credentials_exist",
                "Private configuration already exists; use controlled rotation",
                409,
            ) from None
        with os.fdopen(fd, "wb") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        return {"configured": True}

    def get(self, reference):
        """Private provisioning-only API. Must never be returned from an HTTP endpoint."""
        path = self._path(reference)
        try:
            content = self._cipher().decrypt(self._read(path, 262144))
            return content
        except (OSError, ValueError, InvalidToken):
            raise DomainError(
                "credentials_unavailable", "Private configuration is unavailable or invalid", 409
            ) from None

    def replace(self, reference, payload: bytes):
        """Atomic encrypted replacement. Caller must hold its lifecycle operation lock.

        Runtime must first be stopped/blocked. This method neither materializes
        plaintext nor automatically restores an earlier credential on failure.
        """
        destination = self._path(reference)
        cipher = self._cipher()
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= 131072:
            raise ValueError("Invalid private record")
        # Reject missing, symlinked, multiply-linked or permissive old records.
        cipher.decrypt(self._read(destination, 262144))
        encrypted = cipher.encrypt(payload)
        fd, filename = tempfile.mkstemp(prefix=".rotation-", suffix=".sealed", dir=self._root())
        pending = Path(filename)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, destination)
            if os.name != "nt":
                parent = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(parent)
                finally:
                    os.close(parent)
        finally:
            # Only the exact encrypted temporary file created above is eligible.
            pending.unlink(missing_ok=True)
        return {"configured": True}

    def status(self, reference):
        try:
            self.get(reference)
        except DomainError:
            return {"configured": False}
        return {"configured": True}

    def delete(self, reference):
        """Remove one validated encrypted record without exposing its contents."""
        path = self._path(reference)
        try:
            # Validate ownership, type, link count, size and permissions first.
            self._read(path, 262144)
        except FileNotFoundError:
            return {"configured": False}
        except (OSError, ValueError):
            raise DomainError(
                "credentials_unavailable", "Private configuration is unavailable or invalid", 409
            ) from None
        path.unlink()
        if os.name != "nt":
            parent = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
        return {"configured": False}
