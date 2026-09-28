"""Read-only GitHub release discovery for MediaHub itself.

The provider never accepts a URL from the browser. It talks only to GitHub's
fixed API origin and prefers bounded, SHA-256 identified source assets, retaining
legacy image discovery for migration. Applying the release is a separate
host-updater responsibility with its own rollback boundary.
"""

import re
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
            "assets": {},
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
        accepted = {
            "mediahub-source-release.json": 1024 * 1024,
            "mediahub-source.tar.gz": 256 * 1024**2,
            "mediahub-release.json": 1024 * 1024,
            "mediahub-core-image.tar.gz": 2 * 1024**3,
            "mediahub-agent-image.tar.gz": 2 * 1024**3,
        }
        assets = {}
        for asset in payload.get("assets", []):
            if not isinstance(asset, dict) or asset.get("name") not in accepted:
                continue
            name = asset["name"]
            digest = asset.get("digest")
            download_url = asset.get("browser_download_url")
            api_url = asset.get("url")
            size = asset.get("size")
            parsed_download = urlsplit(download_url or "")
            parsed_api = urlsplit(api_url or "")
            if (
                isinstance(digest, str)
                and re.fullmatch(r"sha256:[a-f0-9]{64}", digest)
                and type(size) is int
                and 0 < size <= accepted[name]
                and parsed_download.scheme == "https"
                and parsed_download.hostname == "github.com"
                and parsed_download.path.startswith(f"/{repository}/releases/download/")
                and parsed_api.scheme == "https"
                and parsed_api.hostname == "api.github.com"
                and parsed_api.path.startswith(f"/repos/{repository}/releases/assets/")
            ):
                assets[name] = {
                    "name": name,
                    "digest": digest,
                    "size": size,
                    "downloadUrl": download_url,
                    "apiUrl": api_url,
                }
        source_names = {"mediahub-source-release.json", "mediahub-source.tar.gz"}
        image_names = {
            "mediahub-release.json",
            "mediahub-core-image.tar.gz",
            "mediahub-agent-image.tar.gz",
        }
        source_mode = source_names <= set(assets)
        selected = source_names if source_mode else image_names
        assets = {name: value for name, value in assets.items() if name in selected}
        manifest = assets.get(
            "mediahub-source-release.json" if source_mode else "mediahub-release.json"
        )
        complete = set(assets) == selected
        available = latest > installed
        return {
            **base,
            "latestVersion": str(latest),
            "updateAvailable": available,
            "releaseUrl": release_url,
            "publishedAt": payload.get("published_at"),
            "manifest": manifest,
            "assets": assets,
            "updateMethod": "source" if source_mode else "legacy-images",
            # A host-side transactional updater is deliberately a separate gate.
            "installReady": False,
            "message": (
                "New source code is available; MediaHub will build it on this server."
                if available and complete and source_mode
                else "A newer complete, digest-verified release is available."
                if available and complete
                else "A newer release exists, but one or more verified MediaHub assets are missing."
                if available
                else "MediaHub is up to date."
            ),
        }
