"""Stage verified release bundles for the root-owned transactional host updater."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import time
import uuid
from typing import Literal
from urllib.parse import urlsplit

import httpx
from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mediahub import __version__
from mediahub.errors import DomainError

IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}$")
RUNNING = {"downloading", "staged", "installing", "verifying", "rolling_back"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Bundle(StrictModel):
    name: str = Field(pattern=r"^mediahub-(core|agent)-image\.tar\.gz$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReleaseManifest(StrictModel):
    schemaVersion: Literal[1] = 1
    version: str
    images: dict[str, str]
    bundles: dict[str, Bundle]
    updatePolicy: dict[str, bool]

    @model_validator(mode="after")
    def safe_release(self):
        if set(self.images) != {"core", "agent"} or set(self.bundles) != {"core", "agent"}:
            raise ValueError("Release must contain Core and Agent")
        if any(self.bundles[role].name != f"mediahub-{role}-image.tar.gz" for role in self.bundles):
            raise ValueError("Release bundle roles do not match their files")
        if not all(IMAGE.fullmatch(value) for value in self.images.values()):
            raise ValueError("Release image is not immutable")
        if self.updatePolicy != {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        }:
            raise ValueError("Release policy is unsafe")
        Version(self.version)
        return self


class PlatformUpdateRuntime:
    def __init__(self, services):
        self.services = services
        self.root = services.config.platform_update_spool
        self.task = None

    def _available_root(self):
        if self.root is None:
            return None
        root = self.root
        try:
            details = root.lstat()
        except OSError:
            return None
        if (
            not stat.S_ISDIR(details.st_mode)
            or root.is_symlink()
            or details.st_uid != os.geteuid()
            or details.st_mode & 0o022
        ):
            return None
        return root

    @property
    def available(self):
        return self._available_root() is not None

    def _status_path(self):
        return self.root / "status.json"

    def _staging_root(self):
        """Return a private Core-owned staging directory or fail with a useful error.

        The host updater runs as root while Core deliberately runs as uid 10001.
        A root-owned staging directory would otherwise surface as an opaque
        PermissionError after the user starts an update.
        """
        root = self.root / "staging"
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        except PermissionError:
            raise DomainError(
                "platform_update_storage",
                "Update staging storage is not writable by MediaHub",
                500,
            ) from None
        try:
            details = root.lstat()
        except OSError:
            raise DomainError(
                "platform_update_storage",
                "Update staging storage is unavailable",
                500,
            ) from None
        posix_metadata_invalid = os.name != "nt" and (
            details.st_uid != os.geteuid() or details.st_mode & 0o077
        )
        if not stat.S_ISDIR(details.st_mode) or root.is_symlink() or posix_metadata_invalid:
            raise DomainError(
                "platform_update_storage",
                "Update staging storage has invalid ownership or permissions",
                500,
            )
        return root

    def status(self):
        root = self._available_root()
        if root is None:
            return {
                "enabled": False,
                "state": "unavailable",
                "progress": 0,
                "message": "The transactional host updater is not installed",
                "steps": [],
            }
        path = self._status_path()
        if not path.exists():
            return {
                "enabled": True,
                "state": "idle",
                "progress": 0,
                "message": "Ready for a verified release",
                "steps": [],
            }
        try:
            if path.is_symlink() or path.stat().st_size > 65536:
                raise ValueError()
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            return {
                "enabled": True,
                "state": str(value.get("state") or "unknown")[:32],
                "progress": max(0, min(100, int(value.get("progress") or 0))),
                "message": str(value.get("message") or "Update state unavailable")[:300],
                "fromVersion": str(value.get("fromVersion") or "")[:64] or None,
                "toVersion": str(value.get("toVersion") or "")[:64] or None,
                "operationId": str(value.get("operationId") or "")[:64] or None,
                "steps": list(value.get("steps") or [])[:10],
                "updatedAt": value.get("updatedAt"),
            }
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {
                "enabled": True,
                "state": "invalid",
                "progress": 0,
                "message": "Update state could not be validated",
                "steps": [],
            }

    def _write_status(self, state, progress, message, operation, target, steps):
        payload = {
            "schemaVersion": 1,
            "state": state,
            "progress": progress,
            "message": message,
            "operationId": operation,
            "fromVersion": __version__,
            "toVersion": target,
            "steps": steps,
            "updatedAt": time.time(),
        }
        temporary = self.root / (".status-" + uuid.uuid4().hex)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._status_path())

    @staticmethod
    def _redirect_url(value):
        parsed = urlsplit(value)
        allowed = {
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
            "github-releases.githubusercontent.com",
        }
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise DomainError(
                "release_redirect_rejected", "GitHub asset redirect was rejected", 502
            )
        return value

    async def _download(self, client, asset, destination, token):
        headers = {
            "Accept": "application/octet-stream",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"MediaHub/{__version__}",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        expected = int(asset["size"])
        if expected > 2 * 1024**3:
            raise DomainError(
                "release_size_mismatch", "Release asset size verification failed", 502
            )
        temporary = destination.parent / ("." + destination.name + "-" + uuid.uuid4().hex)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        digest = hashlib.sha256()
        written = 0

        async def receive(url, request_headers, allow_redirect):
            nonlocal written
            async with client.stream("GET", url, headers=request_headers) as response:
                if response.status_code in {301, 302, 303, 307, 308} and allow_redirect:
                    return self._redirect_url(response.headers.get("location", ""))
                if response.status_code != 200:
                    raise DomainError(
                        "release_download_failed", "A verified release asset was unavailable", 503
                    )
                length = response.headers.get("content-length")
                if length and int(length) != expected:
                    raise DomainError(
                        "release_size_mismatch", "Release asset size verification failed", 502
                    )
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    async for block in response.aiter_bytes(1024 * 1024):
                        written += len(block)
                        if written > expected:
                            raise DomainError(
                                "release_size_mismatch",
                                "Release asset size verification failed",
                                502,
                            )
                        digest.update(block)
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                return None

        try:
            redirect = await receive(asset["apiUrl"], headers, True)
            if redirect:
                redirect_headers = {"User-Agent": headers["User-Agent"]}
                second = await receive(redirect, redirect_headers, False)
                if second:
                    raise DomainError(
                        "release_redirect_rejected", "Nested asset redirect was rejected", 502
                    )
            os.close(fd)
            if written != expected:
                raise DomainError(
                    "release_size_mismatch", "Release asset size verification failed", 502
                )
            value = digest.hexdigest()
            if "sha256:" + value != asset["digest"]:
                raise DomainError(
                    "release_digest_mismatch", "Release asset digest verification failed", 502
                )
            os.replace(temporary, destination)
            return value
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)
            raise

    async def install(self, release):
        root = self._available_root()
        if root is None:
            raise DomainError("platform_updater_unavailable", "Host updater is not installed", 409)
        current = self.status()
        if current["state"] in RUNNING or (self.task and not self.task.done()):
            raise DomainError("platform_update_busy", "A platform update is already running", 409)
        if not release.get("updateAvailable"):
            raise DomainError("platform_update_not_needed", "MediaHub is already up to date", 409)
        assets = release.get("assets") or {}
        if set(assets) != {
            "mediahub-release.json",
            "mediahub-core-image.tar.gz",
            "mediahub-agent-image.tar.gz",
        }:
            raise DomainError("platform_release_incomplete", "Release assets are incomplete", 409)
        operation = uuid.uuid4().hex
        target = str(release["latestVersion"])
        steps = [
            {"id": "download", "label": "Download verified release", "state": "running"},
            {"id": "backup", "label": "Back up configuration", "state": "pending"},
            {"id": "replace", "label": "Replace Core and Agent", "state": "pending"},
            {"id": "verify", "label": "Verify health or roll back", "state": "pending"},
        ]
        self._write_status(
            "downloading", 5, "Downloading verified release assets", operation, target, steps
        )
        self.task = asyncio.create_task(self._stage(operation, target, assets, steps))
        return self.status()

    async def _stage(self, operation, target, assets, steps):
        stage = self.root / "staging" / operation
        try:
            self._staging_root()
            stage.mkdir(mode=0o700)
            required = sum(int(asset["size"]) for asset in assets.values()) + 1024**3
            if shutil.disk_usage(self.root).free < required:
                raise DomainError(
                    "platform_update_space",
                    "Insufficient system space for update and rollback",
                    507,
                )
            token = self.services.release_credentials.token()
            timeout = httpx.Timeout(connect=10, read=180, write=30, pool=10)
            async with httpx.AsyncClient(
                timeout=timeout, follow_redirects=False, trust_env=False
            ) as client:
                manifest_digest = await self._download(
                    client,
                    assets["mediahub-release.json"],
                    stage / "mediahub-release.json",
                    token,
                )
                raw = (stage / "mediahub-release.json").read_bytes()
                if len(raw) > 1024 * 1024:
                    raise DomainError(
                        "platform_manifest_invalid", "Release manifest is invalid", 502
                    )
                manifest = ReleaseManifest.model_validate_json(raw)
                if Version(manifest.version) != Version(target) or Version(target) <= Version(
                    __version__
                ):
                    raise DomainError(
                        "platform_manifest_invalid", "Release version is invalid", 502
                    )
                for index, role in enumerate(("core", "agent"), start=1):
                    bundle = manifest.bundles[role]
                    asset = assets[bundle.name]
                    digest = await self._download(client, asset, stage / bundle.name, token)
                    if digest != bundle.sha256:
                        raise DomainError(
                            "platform_bundle_mismatch", "Release bundle verification failed", 502
                        )
                    self._write_status(
                        "downloading",
                        15 + index * 20,
                        f"Verified {role} update bundle",
                        operation,
                        target,
                        steps,
                    )
            request = {
                "schemaVersion": 1,
                "operationId": operation,
                "fromVersion": __version__,
                "toVersion": target,
                "stage": f"staging/{operation}",
                "manifestSha256": manifest_digest,
            }
            request_path = self.root / "request.json"
            if request_path.exists():
                raise DomainError("platform_update_busy", "Host updater already has a request", 409)
            temporary = self.root / (".request-" + operation)
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(request, stream)
                stream.flush()
                os.fsync(stream.fileno())
            steps[0]["state"] = "complete"
            steps[1]["state"] = "running"
            self._write_status(
                "staged",
                60,
                "Release verified; waiting for the host updater",
                operation,
                target,
                steps,
            )
            os.replace(temporary, request_path)
        except Exception as error:
            shutil.rmtree(stage, ignore_errors=True)
            if isinstance(error, DomainError):
                message = error.message
            elif isinstance(error, PermissionError):
                message = "Update staging storage is not writable by MediaHub"
            else:
                message = "Release staging failed"
            steps[0]["state"] = "error"
            self._write_status("failed", 100, message, operation, target, steps)
