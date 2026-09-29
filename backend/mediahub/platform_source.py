"""Commit-pinned main-branch updates; no release or mutable archive URLs."""

import base64
import hashlib
import re
import tarfile
import tomllib
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import httpx

from mediahub.errors import DomainError

SHA = re.compile(r"^[a-f0-9]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SOURCE_ROOTS = {
    "backend",
    "agent",
    "apps",
    "frontend",
    "docker",
    "pyproject.toml",
    "requirements.lock",
    "README.md",
    "LICENSE",
    "alembic.ini",
    ".dockerignore",
}
MAX_ARCHIVE = 256 * 1024**2


def headers(token=None):
    value = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        value["Authorization"] = "Bearer " + token
    return value


async def metadata(client, path):
    response = await client.get("https://api.github.com" + path)
    if response.status_code in (401, 403):
        raise DomainError(
            "github_credentials_rejected",
            "GitHub rejected access or its rate limit was reached.",
            409,
        )
    if response.status_code != 200:
        raise DomainError(
            "source_provider_unavailable",
            "GitHub main could not be checked. Check repository access.",
            503,
        )
    return response.json()


class GitHubSourceProvider:
    def __init__(self, current_version, installed_commit=None, transport=None):
        self.version = current_version
        self.commit = installed_commit if SHA.fullmatch(installed_commit or "") else None
        self.transport = transport

    async def check(self, repository, token=None):
        result = {
            "provider": "github",
            "configured": bool(repository),
            "repository": repository,
            "branch": "main",
            "installedVersion": self.version,
            "installedCommit": self.commit,
            "latestVersion": None,
            "latestCommit": None,
            "updateAvailable": False,
            "releaseUrl": None,
            "publishedAt": None,
            "manifest": None,
            "assets": {},
            "installReady": False,
            "updateMethod": "source",
            "sourceChannel": "main",
            "privateAccessConfigured": bool(token),
        }
        if not repository:
            return {**result, "message": "Choose the GitHub repository to follow its main branch."}
        if not REPOSITORY.fullmatch(repository):
            raise DomainError("invalid_repository", "Invalid GitHub repository", 422)
        try:
            async with httpx.AsyncClient(
                headers=headers(token),
                timeout=10,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                head = await metadata(client, f"/repos/{repository}/commits/main")
                commit = head["sha"]
                if not isinstance(commit, str) or not SHA.fullmatch(commit):
                    raise ValueError("Invalid commit")
                project = await metadata(
                    client, f"/repos/{repository}/contents/pyproject.toml?ref={commit}"
                )
                if project.get("encoding") != "base64" or len(project["content"]) > 100000:
                    raise ValueError("Invalid project")
                version = tomllib.loads(base64.b64decode(project["content"]).decode())["project"][
                    "version"
                ]
                if not isinstance(version, str) or not re.fullmatch(
                    r"[0-9]+\.[0-9]+\.[0-9]+", version
                ):
                    raise ValueError("Invalid version")
                available = commit != self.commit
                return {
                    **result,
                    "latestVersion": version,
                    "latestCommit": commit,
                    "updateAvailable": available,
                    "releaseUrl": f"https://github.com/{repository}/commit/{commit}",
                    "message": (
                        "New code on main is available; no release is required."
                        if available
                        else "MediaHub matches the latest commit on main."
                    ),
                }
        except httpx.HTTPError:
            raise DomainError(
                "source_provider_unavailable", "GitHub main is temporarily unavailable.", 503
            ) from None
        except (ValueError, KeyError, TypeError):
            raise DomainError(
                "invalid_source_metadata", "GitHub main returned invalid source metadata.", 502
            ) from None


async def download_source(client, repository, commit, destination, token):
    if not REPOSITORY.fullmatch(repository or "") or not SHA.fullmatch(commit or ""):
        raise DomainError("invalid_source_metadata", "Invalid source target", 502)
    url = f"https://api.github.com/repos/{repository}/tarball/{commit}"
    request_headers = headers(token)
    for attempt in range(2):
        async with client.stream("GET", url, headers=request_headers) as response:
            if response.status_code in (301, 302, 303, 307, 308) and attempt == 0:
                url = response.headers.get("location", "")
                target = urlsplit(url)
                if (
                    target.scheme != "https"
                    or target.hostname != "codeload.github.com"
                    or target.port not in (None, 443)
                    or target.username
                    or target.password
                    or target.fragment
                    or target.path != f"/{repository}/legacy.tar.gz/{commit}"
                ):
                    raise DomainError(
                        "source_redirect_rejected", "GitHub source redirect was rejected", 502
                    )
                # Private archive redirects carry GitHub's temporary authorization in the URL.
                # Never forward the repository token to another host or log the redirect URL.
                request_headers = {}
                continue
            if response.status_code != 200:
                raise DomainError(
                    "source_download_failed", "Pinned GitHub source is unavailable", 503
                )
            written = 0
            with destination.open("xb") as output:
                async for block in response.aiter_bytes(1024 * 1024):
                    written += len(block)
                    if written > MAX_ARCHIVE:
                        raise DomainError(
                            "source_too_large", "Source archive exceeds the size limit", 502
                        )
                    output.write(block)
            if not written:
                raise DomainError("source_download_failed", "Source archive is empty", 502)
            return
    raise DomainError("source_redirect_rejected", "Nested source redirect was rejected", 502)


def normalize_source(download, destination):
    """Repackage approved build inputs without ever extracting untrusted paths."""
    seen, prefix, total = set(), None, 0
    with tarfile.open(download, "r:gz") as incoming, tarfile.open(destination, "w:gz") as outgoing:
        for index, member in enumerate(incoming):
            path = PurePosixPath(member.name)
            if (
                index >= 50000
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or ":" in member.name
                or not path.parts
                or not (member.isfile() or member.isdir())
                or path in seen
            ):
                raise ValueError("Unsafe GitHub archive entry")
            seen.add(path)
            prefix = prefix or path.parts[0]
            if path.parts[0] != prefix:
                raise ValueError("Multiple archive roots")
            total += member.size
            if member.size < 0 or total > 2 * 1024**3:
                raise ValueError("Expanded archive exceeds limit")
            if len(path.parts) == 1:
                if not member.isdir():
                    raise ValueError("Invalid archive root")
                continue
            if path.parts[1] not in SOURCE_ROOTS:
                continue
            member.name = str(PurePosixPath("mediahub-source", *path.parts[1:]))
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            member.pax_headers = {}
            if member.isfile():
                with incoming.extractfile(member) as data:
                    outgoing.addfile(member, data)
            else:
                outgoing.addfile(member)
    with destination.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
