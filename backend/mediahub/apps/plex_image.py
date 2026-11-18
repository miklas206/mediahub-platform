"""Read Plex package versions from immutable LinuxServer image metadata."""

import hashlib
import re

import httpx

DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
VERSION = re.compile(r"(?<![\w.])(1\.\d+\.\d+\.\d+)(?![\w.])")
REGISTRY = "https://lscr.io/v2/linuxserver/plex"
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def package_version(config):
    labels = config.get("Labels") or {}
    for name in ("build_version", "org.opencontainers.image.version"):
        match = VERSION.search(labels.get(name) or "")
        if match:
            return match.group(1)
    return None


async def publisher_version(digest, platform):
    if not DIGEST.fullmatch(digest or "") or not platform:
        return None
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
            token = await client.get(
                "https://ghcr.io/token",
                params={"service": "ghcr.io", "scope": "repository:linuxserver/plex:pull"},
            )
            token.raise_for_status()
            headers = {"Authorization": "Bearer " + token.json()["token"], "Accept": ACCEPT}

            async def read(path, expected):
                if not DIGEST.fullmatch(expected):
                    raise ValueError("Invalid Plex image digest")
                response = await client.get(f"{REGISTRY}/{path}/{expected}", headers=headers)
                if path == "blobs" and response.status_code in (302, 307):
                    location = httpx.URL(response.headers["location"])
                    if (
                        location.scheme != "https"
                        or location.host != "pkg-containers.githubusercontent.com"
                    ):
                        raise ValueError("Unexpected Plex registry redirect")
                    response = await client.get(location)
                response.raise_for_status()
                if "sha256:" + hashlib.sha256(response.content).hexdigest() != expected:
                    raise ValueError("Plex image metadata digest mismatch")
                return response.json()

            manifest = await read("manifests", digest)
            if "manifests" in manifest:
                matches = [
                    item
                    for item in manifest["manifests"]
                    if all(
                        item.get("platform", {}).get(key, "") == platform.get(key, "")
                        for key in ("os", "architecture", "variant")
                    )
                ]
                if len(matches) != 1:
                    return None
                manifest = await read("manifests", matches[0]["digest"])
            metadata = await read("blobs", manifest["config"]["digest"])
            return package_version(metadata["config"])
    except (httpx.HTTPError, KeyError, TypeError, ValueError, AttributeError):
        return None
