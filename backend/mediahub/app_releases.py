"""Read-only stable release discovery for explicitly mapped upstream projects."""

from urllib.parse import unquote, urlsplit

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
        async with httpx.AsyncClient(
            timeout=10,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
            headers={"Accept": "text/html"},
        ) as client:
            response = await cache.latest_public_release(client, repository)
            address = urlsplit(response.headers.get("Location", ""))
            prefix = "/" + repository + "/releases/tag/"
            if (
                address.scheme not in {"", "https"}
                or address.netloc not in {"", "github.com"}
                or (address.scheme and not address.netloc)
                or address.query
                or address.fragment
                or not address.path.lower().startswith(prefix.lower())
            ):
                raise ValueError()
            tag = unquote(address.path[len(prefix) :])
            if not tag or len(tag) > 128 or "/" in tag or "\\" in tag:
                raise ValueError()
            version = Version(tag.removeprefix("v"))
            if version.is_prerelease or version.is_devrelease:
                raise ValueError()
            latest = str(version)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise DomainError(
            "app_release_unavailable", "The app's GitHub release could not be verified", 503
        ) from None
    try:
        newer = Version(latest) > Version(installed or "")
    except InvalidVersion:
        newer = None
    return {
        "supported": True,
        "automaticUpdate": False,
        "updateAvailable": newer is True,
        "checkStatus": "checked" if newer is not None else "unchecked",
        "installedVersion": installed,
        "latestVersion": latest,
        "upstreamUpdateAvailable": newer,
        "repository": repository,
        "checkMethod": "public-release",
        "releaseUrl": "https://github.com/" + repository + "/releases/tag/" + tag,
        "message": "New upstream release available; update using the app's managed installer"
        if newer
        else "Latest published release verified; installed version is unknown"
        if newer is None
        else "Installed version matches or exceeds the latest published stable release",
    }
