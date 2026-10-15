"""Read-only Git-over-HTTPS version discovery, without GitHub REST requests."""

import asyncio
import base64
import hashlib
import os
import shutil
import time
from pathlib import Path

from mediahub.errors import DomainError
from mediahub.platform_source import REPOSITORY
from mediahub.source_git import GitHubSSHSource


class GitHubHTTPSSource(GitHubSSHSource):
    failure_message = (
        "GitHub could not be checked using Git over HTTPS. Check network access and Git. "
        "For a private repository, grant the stored GitHub token read access to that repository."
    )

    def __init__(self, repository, data_dir, token=None):
        super().__init__(repository, Path(data_dir), data_dir)
        self.token = token

    def _remote(self):
        return f"https://github.com/{self.repository}.git"

    def _environment(self):
        git = shutil.which("git")
        if not git:
            raise DomainError(
                "source_git_configuration",
                "Git-based update checks require Git in the Core image; install the latest Core release.",
                409,
            )
        environment = {
            name: os.environ[name]
            for name in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
            if name in os.environ
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_ATTR_NOSYSTEM="1",
            LC_ALL="C",
        )
        settings = [
            ("credential.helper", ""),
            ("http.sslVerify", "true"),
            ("http.followRedirects", "false"),
            ("protocol.allow", "never"),
            ("protocol.https.allow", "always"),
        ]
        if self.token:
            value = base64.b64encode(("x-access-token:" + self.token).encode()).decode()
            settings.append(
                ("http.https://github.com/.extraHeader", "Authorization: Basic " + value)
            )
        # Child-only configuration: no token in argv, URLs, files, logs or inherited helpers.
        environment["GIT_CONFIG_COUNT"] = str(len(settings))
        for index, (key, value) in enumerate(settings):
            environment[f"GIT_CONFIG_KEY_{index}"] = key
            environment[f"GIT_CONFIG_VALUE_{index}"] = value
        return git, environment


class GitHubGitChecks:
    method = "git"

    def __init__(self, data_dir, credentials, clock=time.monotonic):
        self.data_dir, self.credentials, self.clock = Path(data_dir), credentials, clock
        self.lock = asyncio.Lock()
        self.cache = {}
        self.failures = {}

    @property
    def private_access_configured(self):
        return bool(self.credentials())

    async def read(self, repository, project_path=None):
        if not REPOSITORY.fullmatch(repository or ""):
            raise DomainError("invalid_repository", "Invalid GitHub repository", 422)
        token = self.credentials()
        identity = (repository, hashlib.sha256((token or "").encode()).digest())
        key = (*identity, project_path)
        async with self.lock:
            now = self.clock()
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                return cached[1]
            failure = self.failures.get(identity)
            if failure and failure[0] > now:
                raise DomainError(failure[1], failure[2], failure[3])
            source = GitHubHTTPSSource(repository, self.data_dir, token)
            action = "metadata" if project_path else "head"
            try:
                result = await asyncio.to_thread(
                    source._operate,
                    repository,
                    action,
                    project_path=project_path or "pyproject.toml",
                )
            except DomainError as error:
                self.failures[identity] = (self.clock() + 60, error.code, error.message, error.status)
                while len(self.failures) > 32:
                    self.failures.pop(next(iter(self.failures)))
                raise
            self.cache[key] = (self.clock() + 300, result)
            if project_path:
                self.cache[(*identity, None)] = (self.clock() + 300, result[0])
            self.failures.pop(identity, None)
            while len(self.cache) > 64:
                self.cache.pop(next(iter(self.cache)))
            return result

    async def metadata(self, repository, *, project_path="pyproject.toml"):
        return await self.read(repository, project_path)

    async def head(self, repository):
        return await self.read(repository)
