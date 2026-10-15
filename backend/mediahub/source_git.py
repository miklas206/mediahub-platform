"""Optional read-only GitHub deploy-key access, bound to one operator-approved repo."""

import asyncio
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from mediahub.errors import DomainError
from mediahub.platform_source import MAX_ARCHIVE, REPOSITORY, SHA

_WORK_LOCK = threading.Lock()
MAX_CACHE = 512 * 1024**2
OPERATION_SECONDS = 90


def source_access(config):
    """No environment or personal SSH identity is used unless explicitly configured."""
    repository = getattr(config, "source_git_repository", None)
    directory = getattr(config, "source_git_ssh_dir", None)
    if not repository and not directory:
        return None
    if not repository or not directory:
        raise DomainError("source_git_configuration", "GitHub deploy-key access is incomplete", 409)
    return GitHubSSHSource(repository, Path(directory), Path(config.data_dir))


class GitHubSSHSource:
    def __init__(self, repository, ssh_dir, data_dir):
        if not REPOSITORY.fullmatch(repository or ""):
            raise DomainError("source_git_configuration", "Invalid deploy-key repository", 409)
        self.repository = repository
        self.ssh_dir = Path(ssh_dir)
        self.cache = Path(data_dir) / "source-git-cache"

    def require_repository(self, repository):
        if repository != self.repository:
            raise DomainError(
                "source_git_repository_mismatch",
                "The configured deploy key is restricted to a different GitHub repository.",
                409,
            )

    def _remote(self):
        return f"git@github.com:{self.repository}.git"

    def _environment(self):
        key, known = self.ssh_dir / "id_ed25519", self.ssh_dir / "known_hosts"
        git = shutil.which("git")
        ssh = "C:/Windows/System32/OpenSSH/ssh.exe" if os.name == "nt" else shutil.which("ssh")
        if (
            not git
            or not ssh
            or not Path(ssh).is_file()
            or any(path.is_symlink() or not path.is_file() for path in (key, known))
            or (os.name != "nt" and key.stat().st_mode & 0o077)
        ):
            raise DomainError(
                "source_git_configuration",
                "GitHub deploy-key access requires Git, SSH, a private key and verified known_hosts.",
                409,
            )
        # An allowlist prevents inherited Git config, proxy commands and SSH agents
        # from expanding the repository/identity selected by the operator.
        environment = {
            name: os.environ[name]
            for name in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
            if name in os.environ
        }
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_SSH_VARIANT": "ssh",
                "LC_ALL": "C",
                "GIT_SSH_COMMAND": shlex.join(
                    [
                        ssh,
                        "-F",
                        os.devnull,
                        "-i",
                        key.as_posix(),
                        "-o",
                        "IdentitiesOnly=yes",
                        "-o",
                        "IdentityAgent=none",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "StrictHostKeyChecking=yes",
                        "-o",
                        "UserKnownHostsFile=" + known.as_posix(),
                        "-o",
                        "GlobalKnownHostsFile=" + os.devnull,
                        "-o",
                        "PasswordAuthentication=no",
                        "-o",
                        "KbdInteractiveAuthentication=no",
                        "-o",
                        "ConnectTimeout=10",
                        "-o",
                        "ServerAliveInterval=10",
                        "-o",
                        "ServerAliveCountMax=2",
                        "-o",
                        "LogLevel=ERROR",
                    ]
                ),
            }
        )
        return git, environment

    @staticmethod
    def _cache_size(directory):
        size = 0
        for path in directory.rglob("*"):
            try:
                if path.is_file():
                    size += path.stat().st_size
            except FileNotFoundError:
                # Git can rename a temporary pack between the listing and stat.
                continue
        return size

    def _run(self, args, directory, environment, deadline, output=None, limit=100000):
        git, env = environment
        command = [
            git,
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            *args,
        ]
        with tempfile.TemporaryFile() if output is None else output.open("xb") as stream:
            process = subprocess.Popen(
                command,
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
            try:
                while True:
                    try:
                        process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        pass
                    if (
                        time.monotonic() >= deadline
                        or stream.tell() > limit
                        or self._cache_size(self.cache) > MAX_CACHE
                    ):
                        raise ValueError("Git operation exceeded its resource budget")
                    if process.poll() is not None:
                        break
                if process.returncode:
                    raise ValueError("Git operation failed")
                if output is None:
                    stream.seek(0)
                    return stream.read(limit + 1)
            finally:
                if process.poll() is None:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.wait(timeout=5)

    def _operate(self, repository, action, commit=None, destination=None, project_path="pyproject.toml"):
        self.require_repository(repository)
        if project_path not in {"pyproject.toml", "docker/bundled/mediaseed/pyproject.toml", "docker/bundled/mediavpn/pyproject.toml"}:
            raise DomainError("invalid_source_metadata", "Unsupported project metadata path", 422)
        if commit is not None and not SHA.fullmatch(commit):
            raise DomainError("invalid_source_metadata", "Invalid pinned source commit", 502)
        if not _WORK_LOCK.acquire(timeout=10):
            raise DomainError(
                "source_git_busy", "GitHub source access is already busy; retry.", 409
            )
        try:
            environment = self._environment()
            if self.cache.is_symlink():
                raise ValueError("Invalid source cache")
            self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self._cache_size(self.cache) > MAX_CACHE:
                raise ValueError("Source cache exceeds its budget")
            deadline = time.monotonic() + OPERATION_SECONDS
            # Only one temporary bare repository exists per operation; source is
            # never checked out or executed, and is removed on success or failure.
            with tempfile.TemporaryDirectory(prefix="source-", dir=self.cache) as temporary:
                root = Path(temporary)
                remote = self._remote()
                if action in {"head", "metadata"}:
                    value = (
                        self._run(
                            ["ls-remote", "--exit-code", remote, "refs/heads/main"],
                            root,
                            environment,
                            deadline,
                        )
                        .decode()
                        .strip()
                        .split()
                    )
                    if (
                        len(value) != 2
                        or value[1] != "refs/heads/main"
                        or not SHA.fullmatch(value[0])
                    ):
                        raise ValueError("Invalid GitHub main reference")
                    commit = value[0]
                    if action == "head":
                        return commit
                self._run(["init", "--bare", "."], root, environment, deadline)
                self._run(
                    ["fetch", "--quiet", "--no-tags", "--depth=1", remote, commit],
                    root,
                    environment,
                    deadline,
                )
                fetched = (
                    self._run(
                        ["rev-parse", "FETCH_HEAD^{commit}"],
                        root,
                        environment,
                        deadline,
                    )
                    .decode()
                    .strip()
                )
                if fetched != commit:
                    raise ValueError("Fetched commit differs from requested source")
                if action == "metadata":
                    project = self._run(
                        ["show", f"{commit}:{project_path}"],
                        root,
                        environment,
                        deadline,
                    )
                    return commit, project
                self._run(
                    ["archive", "--format=tar.gz", "--prefix=github-source/", commit],
                    root,
                    environment,
                    deadline,
                    output=destination,
                    limit=MAX_ARCHIVE,
                )
                if not destination.stat().st_size:
                    raise ValueError("Empty source archive")
        except DomainError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            # Git/SSH output may include local paths or key details. Never publish it.
            raise DomainError(
                "source_git_unavailable",
                getattr(
                    self, "failure_message",
                    "GitHub source could not be read with the configured deploy key. "
                    "Check repository access, verified host key and available cache space.",
                ),
                503,
            ) from None
        finally:
            _WORK_LOCK.release()

    async def head(self, repository):
        return await asyncio.to_thread(self._operate, repository, "head")

    async def metadata(self, repository, *, project_path="pyproject.toml"):
        return await asyncio.to_thread(self._operate, repository, "metadata", project_path=project_path)

    async def archive(self, repository, commit, destination):
        return await asyncio.to_thread(self._operate, repository, "archive", commit, destination)
