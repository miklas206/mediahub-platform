"""Fetch approved publishers at install time and retain immutable runtime pins.

Docker streams layers straight into its content store; no tarball or source
archive is staged on the media disk. Runtime layers must not be pruned.
"""

import json
import re

import httpx
from mediahub.errors import DomainError

PUBLISHERS = frozenset({
    "lscr.io/linuxserver/plex", "jellyfin/jellyfin", "linuxserver/prowlarr",
    "linuxserver/radarr", "linuxserver/sonarr", "ghcr.io/autobrr/autobrr",
    "qmcgaw/gluetun", "lscr.io/linuxserver/qbittorrent", "cloudflare/cloudflared",
})


def resolved_seedbox_policy(policy, images):
    if not isinstance(images, dict) or set(images) != {"vpnImage", "torrentImage"}:
        raise ValueError("Invalid installed image bindings")
    policy.paths = type(policy.paths).model_validate({**policy.paths.model_dump(), **images})
    return policy


def publisher_reference(image, repository):
    """Reject unverified cache metadata; create from the pulled digest, not a tag."""
    if repository not in PUBLISHERS or not isinstance(image, dict):
        raise DomainError("install_image_invalid", "Publisher image could not be verified", 503)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image.get("Id", "")):
        raise DomainError("install_image_invalid", "Publisher image could not be verified", 503)
    for reference in image.get("RepoDigests", []):
        if not isinstance(reference, str):
            continue
        name, _, digest = reference.partition("@")
        name = name.removeprefix("docker.io/").removeprefix("index.docker.io/")
        if name == repository and re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
            return repository + "@" + digest
    raise DomainError("install_image_invalid", "Publisher digest could not be verified", 503)


async def pull_latest(socket, repository):
    """Always contact upstream, including warm-cache installs; never fall back."""
    if repository not in PUBLISHERS:
        raise DomainError("install_image_denied", "Unsupported image publisher", 403)
    try:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket)), base_url="http://docker",
            timeout=httpx.Timeout(600, connect=5), trust_env=False,
        ) as client:
            async with client.stream("POST", "/images/create", params={
                "fromImage": repository, "tag": "latest",
            }) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if len(line) > 65536:
                        raise ValueError("Oversized pull response")
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get("error") or event.get("errorDetail"):
                        raise ValueError("Publisher pull failed")
            response = await client.get("/images/" + repository + ":latest/json")
            response.raise_for_status()
            if len(response.content) > 4 * 1024**2:
                raise ValueError("Oversized image metadata")
            image = response.json()
            publisher_reference(image, repository)
            return image
    except (httpx.HTTPError, ValueError, TypeError):
        raise DomainError(
            "install_image_download_failed",
            "The latest publisher image could not be downloaded; installation was stopped", 503,
        ) from None
