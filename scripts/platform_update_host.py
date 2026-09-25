#!/usr/bin/env python3
"""Root-owned transactional MediaHub image updater.

The networkless host helper consumes only Core-staged, digest-verified release
bundles. It never receives a GitHub token and never traverses media mounts.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - the host updater runs only on Linux
    fcntl = None

IMAGE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ID = re.compile(r"^[a-f0-9]{32}$")
MAX_BUNDLE = 2 * 1024**3
LOADED_IMAGE = re.compile(r"^sha256:[a-f0-9]{64}$")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def version_key(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError("Invalid update version")
    return tuple(map(int, value.split(".")))


class HostUpdater:
    def __init__(self, root, runner=None, sleeper=time.sleep):
        self.root = Path(root)
        self.updates = self.root / "updates"
        self.backups = self.root / "update-backups"
        self.compose = self.root / "compose.json"
        self.policy = self.root / "update-policy.json"
        self.installed_version = self.root / "installed-version"
        self.runner = runner or self._run
        self.sleep = sleeper
        self.operation = None
        self.target = None
        self.steps = []

    @staticmethod
    def _run(args, capture=True):
        result = subprocess.run(
            args,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
            timeout=600,
        )
        output = result.stdout or ""
        if len(output) > 65536:
            raise ValueError("Command output exceeded safety limit")
        return output.strip()

    def command(self, *args, capture=True):
        return self.runner(list(map(str, args)), capture=capture)

    @staticmethod
    def _directory(path, owner=None):
        details = path.lstat()
        if not stat.S_ISDIR(details.st_mode) or path.is_symlink():
            raise ValueError("Unsafe update directory")
        if owner is not None and details.st_uid != owner:
            raise ValueError("Unexpected update directory owner")
        return path

    @staticmethod
    def _read_json(path, limit=1024 * 1024):
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or path.is_symlink()
            or details.st_nlink != 1
            or not 0 < details.st_size <= limit
        ):
            raise ValueError("Unsafe update file")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid update document")
        return value

    @staticmethod
    def _atomic_json(path, value, uid=10001, gid=10001):
        temporary = path.parent / ("." + path.name + "-" + uuid.uuid4().hex)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)

    @staticmethod
    def _atomic_text(path, value, uid=0, gid=0):
        temporary = path.parent / ("." + path.name + "-" + uuid.uuid4().hex)
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)

    @staticmethod
    def _trusted_file(path, limit=65536):
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or path.is_symlink()
            or details.st_nlink != 1
            or details.st_uid != 0
            or details.st_mode & 0o022
            or not 0 < details.st_size <= limit
        ):
            raise ValueError("Unsafe root-owned update policy")
        return path.read_text(encoding="utf-8")

    def _trusted_policy(self):
        value = json.loads(self._trusted_file(self.policy))
        if set(value) != {"coreRepository", "agentRepository"}:
            raise ValueError("Invalid update policy")
        expected = {
            "core": value["coreRepository"],
            "agent": value["agentRepository"],
        }
        if not all(
            isinstance(repository, str)
            and re.fullmatch(r"ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+", repository)
            for repository in expected.values()
        ):
            raise ValueError("Invalid trusted image repository")
        return expected

    def status(self, state, progress, message):
        self._atomic_json(
            self.updates / "status.json",
            {
                "schemaVersion": 1,
                "state": state,
                "progress": progress,
                "message": message,
                "operationId": self.operation,
                "fromVersion": self.request.get("fromVersion"),
                "toVersion": self.target,
                "steps": self.steps,
                "updatedAt": time.time(),
            },
        )

    @staticmethod
    def _tree_size(path):
        total = 0
        for root, directories, files in os.walk(path, followlinks=False):
            current = Path(root)
            for name in directories + files:
                candidate = current / name
                details = candidate.lstat()
                if stat.S_ISLNK(details.st_mode):
                    raise ValueError("Configuration backup contains a symbolic link")
                if stat.S_ISREG(details.st_mode):
                    total += details.st_size
                    if total > 8 * 1024**3:
                        raise ValueError("Configuration backup is unexpectedly large")
        return total

    def _validate_request(self):
        request_path = self.updates / "request.json"
        request = self._read_json(request_path, 65536)
        if set(request) != {
            "schemaVersion",
            "operationId",
            "fromVersion",
            "toVersion",
            "stage",
            "manifestSha256",
        }:
            raise ValueError("Unexpected update request fields")
        if request["schemaVersion"] != 1 or not ID.fullmatch(request["operationId"]):
            raise ValueError("Invalid update request")
        if not VERSION.fullmatch(request["fromVersion"]) or not VERSION.fullmatch(
            request["toVersion"]
        ):
            raise ValueError("Invalid update version")
        expected_stage = f"staging/{request['operationId']}"
        if request["stage"] != expected_stage:
            raise ValueError("Invalid update stage")
        if not re.fullmatch(r"[a-f0-9]{64}", request["manifestSha256"]):
            raise ValueError("Invalid manifest digest")
        stage = self.updates / "staging" / request["operationId"]
        self._directory(stage, owner=10001)
        manifest_path = stage / "mediahub-release.json"
        if sha256(manifest_path) != request["manifestSha256"]:
            raise ValueError("Manifest digest mismatch")
        manifest = self._read_json(manifest_path)
        if set(manifest) != {
            "schemaVersion",
            "version",
            "images",
            "bundles",
            "updatePolicy",
        }:
            raise ValueError("Unexpected release manifest fields")
        if manifest["schemaVersion"] != 1 or manifest["version"] != request["toVersion"]:
            raise ValueError("Release manifest version mismatch")
        if manifest["updatePolicy"] != {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        }:
            raise ValueError("Unsafe release policy")
        if set(manifest["images"]) != {"core", "agent"} or not all(
            isinstance(value, str) and IMAGE.fullmatch(value)
            for value in manifest["images"].values()
        ):
            raise ValueError("Unsafe image references")
        if set(manifest["bundles"]) != {"core", "agent"}:
            raise ValueError("Release bundles are incomplete")
        for role in ("core", "agent"):
            bundle = manifest["bundles"][role]
            expected_name = f"mediahub-{role}-image.tar.gz"
            if set(bundle) != {"name", "sha256"} or bundle["name"] != expected_name:
                raise ValueError("Unexpected release bundle")
            if not re.fullmatch(r"[a-f0-9]{64}", bundle["sha256"]):
                raise ValueError("Invalid bundle digest")
            path = stage / expected_name
            details = path.lstat()
            if (
                not stat.S_ISREG(details.st_mode)
                or path.is_symlink()
                or details.st_nlink != 1
                or not 0 < details.st_size <= MAX_BUNDLE
                or sha256(path) != bundle["sha256"]
            ):
                raise ValueError("Release bundle verification failed")
        running = self.updates / ("running-" + request["operationId"] + ".json")
        os.replace(request_path, running)
        return request, manifest, stage

    def _compose_command(self, *args, capture=True):
        return self.command("docker", "compose", "-f", self.compose, *args, capture=capture)

    def _load_release_image(self, role, stage, manifest):
        """Load a verified offline bundle and give its image an immutable local tag.

        Docker archives exported from a registry digest can legitimately load by
        image ID only.  The bundle hash has already been validated against the
        trusted release manifest, so the loaded ID is safe to bind to a local,
        version-and-bundle-specific tag without contacting a registry.
        """
        bundle = manifest["bundles"][role]
        output = self.command("docker", "load", "--input", stage / bundle["name"])
        candidates = []
        for line in output.splitlines():
            for prefix in ("Loaded image ID: ", "Loaded image: "):
                if line.startswith(prefix):
                    candidates.append(line.removeprefix(prefix).strip())
        if len(candidates) != 1:
            raise ValueError("Offline image bundle did not identify exactly one image")
        image_id = self.command("docker", "image", "inspect", "--format", "{{.Id}}", candidates[0])
        if not LOADED_IMAGE.fullmatch(image_id):
            raise ValueError("Offline image bundle returned an invalid image ID")
        local_tag = f"mediahub-{role}:release-{manifest['version']}-{bundle['sha256'][:12]}"
        self.command("docker", "tag", image_id, local_tag)
        inspected = self.command("docker", "image", "inspect", "--format", "{{.Id}}", local_tag)
        if inspected != image_id:
            raise ValueError("Offline image tag verification failed")
        return local_tag

    def _wait(self, service, health=False, timeout=150):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            identifier = self._compose_command("ps", "-q", service)
            if identifier:
                template = "{{.State.Health.Status}}" if health else "{{.State.Running}}"
                state = self.command("docker", "inspect", "--format", template, identifier)
                if state == ("healthy" if health else "true"):
                    return
            self.sleep(2)
        raise ValueError(f"{service} did not become healthy")

    def _backup_preflight(self):
        total = sum(self._tree_size(self.root / name) for name in ("data", "agent"))
        if shutil.disk_usage(self.root).free < total * 2 + 1024**3:
            raise ValueError("Insufficient space for rollback snapshot")
        return total

    def _copy_configuration(self, backup):
        temporary = self.backups / ("." + self.operation + "-preparing")
        if backup.exists() or temporary.exists():
            raise ValueError("Rollback snapshot destination already exists")
        temporary.mkdir(mode=0o700, parents=True)
        try:
            shutil.copy2(self.compose, temporary / "compose.json")
            for name in ("data", "agent"):
                shutil.copytree(self.root / name, temporary / name, symlinks=False)
            os.replace(temporary, backup)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _restore_configuration(self, backup):
        self._compose_command("stop", "-t", "30", "core", "agent", capture=False)
        shutil.copy2(backup / "compose.json", self.compose)
        for name in ("data", "agent"):
            current = self.root / name
            failed = self.root / f"{name}.failed-{self.operation}"
            if failed.exists():
                raise ValueError("Rollback destination already exists")
            os.replace(current, failed)
            try:
                shutil.copytree(backup / name, current, symlinks=False)
            except Exception:
                if current.exists():
                    shutil.rmtree(current)
                os.replace(failed, current)
                raise
        self._compose_command("up", "-d", "--no-deps", "agent", capture=False)
        self._wait("agent")
        self._compose_command("up", "-d", "--no-deps", "core", capture=False)
        self._wait("core", health=True)

    def process(self):
        if fcntl is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise ValueError("Host updater must run as root")
        self._directory(self.root)
        self._directory(self.updates, owner=10001)
        if self.root == Path("/") or self.root.is_symlink() or not self.compose.is_file():
            raise ValueError("Unsafe MediaHub root")
        self.backups.mkdir(mode=0o700, exist_ok=True)
        lock_path = self.updates / "host-updater.lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = manifest = stage = backup = None
            services_stopped = False
            try:
                request, manifest, stage = self._validate_request()
                self.request = request
                self.operation = request["operationId"]
                self.target = request["toVersion"]
                self.steps = [
                    {"id": "download", "label": "Download verified release", "state": "complete"},
                    {"id": "backup", "label": "Back up configuration", "state": "running"},
                    {"id": "replace", "label": "Replace Core and Agent", "state": "pending"},
                    {"id": "verify", "label": "Verify health or roll back", "state": "pending"},
                ]
                installed = self._trusted_file(self.installed_version, 128).strip()
                if request["fromVersion"] != installed:
                    raise ValueError("Installed version does not match the update request")
                if version_key(self.target) <= version_key(installed):
                    raise ValueError("Update must move to a newer stable version")
                trusted_repositories = self._trusted_policy()
                for role in ("core", "agent"):
                    repository = manifest["images"][role].partition("@")[0]
                    if repository != trusted_repositories[role]:
                        raise ValueError("Release image is outside the trusted repository")
                self.status("installing", 65, "Stopping control services for a safe snapshot")
                compose = self._read_json(self.compose, 2 * 1024 * 1024)
                if compose.get("name") != "mediahub-platform" or set(
                    compose.get("services", {})
                ) < {"core", "agent"}:
                    raise ValueError("Compose ownership validation failed")
                self._backup_preflight()
                services_stopped = True
                self._compose_command("stop", "-t", "30", "core", "agent", capture=False)
                backup_destination = self.backups / self.operation
                self._copy_configuration(backup_destination)
                backup = backup_destination
                self.steps[1]["state"] = "complete"
                self.steps[2]["state"] = "running"
                self.status("installing", 72, "Loading immutable Core and Agent images")
                for role in ("core", "agent"):
                    compose["services"][role]["image"] = self._load_release_image(
                        role, stage, manifest
                    )
                    compose["services"][role]["pull_policy"] = "never"
                self._atomic_json(self.compose, compose, uid=0, gid=0)
                self._compose_command("up", "-d", "--no-deps", "agent", capture=False)
                self._wait("agent")
                self._compose_command("up", "-d", "--no-deps", "core", capture=False)
                self.steps[2]["state"] = "complete"
                self.steps[3]["state"] = "running"
                self.status("verifying", 90, "Verifying the updated MediaHub services")
                self._wait("core", health=True)
                self._atomic_text(self.installed_version, self.target)
                self.steps[3]["state"] = "complete"
                self.status("succeeded", 100, f"MediaHub {self.target} installed successfully")
                shutil.rmtree(stage)
                backups = sorted(
                    (path for path in self.backups.iterdir() if path.is_dir()),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )
                for old in backups[2:]:
                    shutil.rmtree(old)
            except Exception:
                if request is None:
                    raise
                if not services_stopped:
                    self.steps[1]["state"] = "error"
                    self.status(
                        "failed",
                        100,
                        "Update was rejected before any running service was changed",
                    )
                    return
                try:
                    self.steps[3]["state"] = "running"
                    self.status("rolling_back", 95, "Update failed; restoring the previous version")
                    if backup and backup.is_dir():
                        self._restore_configuration(backup)
                    elif services_stopped:
                        self._compose_command("up", "-d", "--no-deps", "agent", capture=False)
                        self._wait("agent")
                        self._compose_command("up", "-d", "--no-deps", "core", capture=False)
                        self._wait("core", health=True)
                    self.steps[3]["state"] = "complete"
                    self.status(
                        "rolled_back", 100, "Update failed and the previous version was restored"
                    )
                except Exception:
                    self.steps[3]["state"] = "error"
                    self.status(
                        "failed",
                        100,
                        "Update and automatic rollback failed; administrator recovery is required",
                    )
                    raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/opt/mediahub")
    args = parser.parse_args()
    root = Path(args.root)
    if not root.is_absolute() or root == Path("/") or ".." in root.parts:
        raise ValueError("Use a bounded absolute MediaHub root")
    HostUpdater(root).process()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        print("MediaHub host update failed; inspect the protected status file", file=sys.stderr)
        raise SystemExit(1)
