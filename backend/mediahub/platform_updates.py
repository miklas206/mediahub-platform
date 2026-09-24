"""Read-only GitHub release discovery for MediaHub itself.

The provider never accepts a URL from the browser. It talks only to GitHub's
fixed API origin and reports a release as installable only when the release
contains the expected SHA-256 identified manifest. Applying the release is a
separate host-updater responsibility with its own rollback boundary.
"""

from urllib.parse import urlsplit

import httpx
from packaging.version import InvalidVersion, Version

from mediahub.errors import DomainError


class GitHubReleaseProvider:
    def __init__(self, current_version: str, transport=None):
        self.current_version = current_version
        self.transport = transport

    async def check(self, repository: str | None, token: str | None = None):
        base = {
            "provider": "github",
            "installedVersion": self.current_version,
            "configured": bool(repository),
            "repository": repository,
            "latestVersion": None,
            "updateAvailable": False,
            "releaseUrl": None,
            "publishedAt": None,
            "manifest": None,
            "installReady": False,
            "privateAccessConfigured": bool(token),
        }
        if not repository:
            return {
                **base,
                "message": "Choose the GitHub repository that will publish MediaHub releases.",
            }
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"MediaHub/{self.current_version}",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(
                base_url="https://api.github.com",
                headers=headers,
                timeout=httpx.Timeout(8.0),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get(f"/repos/{repository}/releases/latest")
        except httpx.HTTPError:
            raise DomainError(
                "release_provider_unavailable",
                "GitHub release information is temporarily unavailable.",
                503,
            ) from None
        if response.status_code == 404:
            return {
                **base,
                "message": (
                    "No published MediaHub release was found yet."
                    if token
                    else "No release was found. Private repositories require read-only GitHub access."
                ),
            }
        if response.status_code in {401, 403}:
            raise DomainError(
                "github_credentials_rejected",
                "GitHub rejected the stored private access. Replace it in Updates.",
                409,
            )
        if response.status_code != 200:
            raise DomainError(
                "release_provider_unavailable",
                "GitHub release information is temporarily unavailable.",
                503,
            )
        try:
            payload = response.json()
            tag = str(payload["tag_name"])
            latest = Version(tag.removeprefix("v"))
            installed = Version(self.current_version)
        except (KeyError, TypeError, ValueError, InvalidVersion):
            raise DomainError(
                "invalid_release_metadata",
                "The latest GitHub release does not contain valid MediaHub version metadata.",
                502,
            ) from None
        release_url = payload.get("html_url")
        parsed_release = urlsplit(release_url or "")
        if parsed_release.scheme != "https" or parsed_release.hostname != "github.com":
            release_url = None
        manifest = None
        for asset in payload.get("assets", []):
            if not isinstance(asset, dict) or asset.get("name") != "mediahub-release.json":
                continue
            digest = asset.get("digest")
            download_url = asset.get("browser_download_url")
            api_url = asset.get("url")
            parsed_download = urlsplit(download_url or "")
            parsed_api = urlsplit(api_url or "")
            if (
                isinstance(digest, str)
                and digest.startswith("sha256:")
                and len(digest) == 71
                and parsed_download.scheme == "https"
                and parsed_download.hostname == "github.com"
                and parsed_api.scheme == "https"
                and parsed_api.hostname == "api.github.com"
            ):
                manifest = {
                    "name": "mediahub-release.json",
                    "digest": digest,
                    "downloadUrl": download_url,
                    "apiUrl": api_url,
                }
            break
        available = latest > installed
        return {
            **base,
            "latestVersion": str(latest),
            "updateAvailable": available,
            "releaseUrl": release_url,
            "publishedAt": payload.get("published_at"),
            "manifest": manifest,
            # A host-side transactional updater is deliberately a separate gate.
            "installReady": False,
            "message": (
                "A newer verified release is available. Host update activation is still required."
                if available and manifest
                else "A newer release exists, but its verified MediaHub manifest is missing."
                if available
                else "MediaHub is up to date."
            ),
        }
