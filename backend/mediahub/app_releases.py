"""Read-only stable release discovery for explicitly mapped upstream projects."""

import httpx
from packaging.version import InvalidVersion, Version

from mediahub.errors import DomainError
from mediahub.github_metadata import GitHubMetadata

REPOSITORIES = {
    "org.mediahub.jellyfin": "jellyfin/jellyfin",
    "org.mediahub.prowlarr": "Prowlarr/Prowlarr",
    "org.mediahub.radarr": "Radarr/Radarr",
    "org.mediahub.sonarr": "Sonarr/Sonarr",
    "org.mediahub.autobrr": "autobrr/autobrr",
}


async def latest_release(package, installed, cache=None, transport=None):
    repository = REPOSITORIES[package]
    cache = cache or GitHubMetadata()
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False,
                                    transport=transport, headers={"Accept": "application/vnd.github+json"}) as client:
            response = await cache.get(client, "/repos/" + repository + "/releases/latest")
            response.raise_for_status()
            release = response.json()
        latest = str(Version(release["tag_name"].removeprefix("v")))
        if release.get("draft") or release.get("prerelease"):
            raise ValueError()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise DomainError("app_release_unavailable", "The app's GitHub release could not be verified", 503) from None
    try:
        newer = Version(latest) > Version(installed or "")
    except InvalidVersion:
        newer = None
    return {
        "supported": True, "automaticUpdate": False, "updateAvailable": newer is True,
        "checkStatus": "checked" if newer is not None else "unchecked",
        "installedVersion": installed, "latestVersion": latest,
        "upstreamUpdateAvailable": newer, "repository": repository,
        "message": "New upstream release available; update using the app's managed installer" if newer else
                   "Latest GitHub release verified; installed version is unknown" if newer is None else
                   "Installed version matches or exceeds the latest stable GitHub release",
    }
