"""Bounded, cached read-only media previews from the policy-owned Plex runtime."""

import asyncio
import base64
import re
import time
from collections import OrderedDict

import httpx
from mediahub.apps.plex_media import (
    MAX_ARTWORK_BYTES,
    MAX_RECENT_MEDIA,
    RATING_KEY_PATTERN,
    PlexMediaItem,
    PlexRecentMedia,
    valid_artwork,
)
from mediahub.errors import DomainError
from pydantic import ValidationError

# A Plex response can never turn this service into an arbitrary URL/path proxy.
THUMB_PATH = re.compile(r"^/library/metadata/[0-9]{1,20}/thumb(?:/[0-9]{1,20})?$")
RECENT_TIMEOUT = 7
ARTWORK_TIMEOUT = 18


def thumbnail_path(element):
    for key in ("grandparentThumb", "parentThumb", "thumb"):
        value = element.get(key, "")
        if THUMB_PATH.fullmatch(value):
            return value
    return None


class PlexMedia:
    def __init__(self, control):
        self.control = control
        self.recent_cache = None
        self.artwork_cache = OrderedDict()
        self.recent_lock = asyncio.Lock()
        self.artwork_slots = asyncio.Semaphore(4)

    async def policy(self):
        policy = self.control.policy()
        inspected = await self.control.inspect(policy)
        if inspected.get("State", {}).get("Running") is not True:
            raise DomainError("plex_media_unavailable", "Plex media preview is unavailable", 503)
        return policy

    @staticmethod
    def cache_key(policy):
        return (policy.installationId, policy.apiUrl, policy.apiNetwork, policy.imageId)

    async def recent(self):
        try:
            async with asyncio.timeout(RECENT_TIMEOUT):
                return await self._recent()
        except TimeoutError:
            raise DomainError(
                "plex_media_unavailable", "Plex media preview is unavailable", 503
            ) from None

    async def _recent(self):
        policy = await self.policy()
        key = self.cache_key(policy)
        async with self.recent_lock:
            now = time.monotonic()
            if self.recent_cache and self.recent_cache[0] == key and now < self.recent_cache[1]:
                return self.recent_cache[2]
            listing = await self.control.plex_get(
                policy,
                "/library/recentlyAdded",
                params={"X-Plex-Container-Start": 0, "X-Plex-Container-Size": MAX_RECENT_MEDIA},
            )
            items = []
            seen = set()
            for entry in list(listing)[:MAX_RECENT_MEDIA]:
                try:
                    item = PlexMediaItem(
                        id=entry.get("ratingKey", ""),
                        title=entry.get("title", "")[:300],
                        type=entry.get("type"),
                        year=entry.get("year"),
                        hasArtwork=thumbnail_path(entry) is not None,
                    )
                except ValidationError:
                    continue
                if item.id not in seen:
                    items.append(item)
                    seen.add(item.id)
            result = PlexRecentMedia(items=items).model_dump()
            self.recent_cache = (key, time.monotonic() + 60, result)
            return result

    async def artwork(self, rating_key):
        if not re.fullmatch(RATING_KEY_PATTERN, rating_key):
            raise DomainError("invalid_media_id", "Invalid Plex media identifier", 422)
        try:
            async with asyncio.timeout(ARTWORK_TIMEOUT):
                return await self._artwork(rating_key)
        except TimeoutError:
            raise DomainError(
                "plex_artwork_unavailable", "Plex cover is unavailable", 503
            ) from None

    async def _artwork(self, rating_key):
        policy = await self.policy()
        key = (*self.cache_key(policy), rating_key)
        async with self.artwork_slots:
            now = time.monotonic()
            for cached_key, (expires, _) in list(self.artwork_cache.items()):
                if now >= expires:
                    del self.artwork_cache[cached_key]
            cached = self.artwork_cache.get(key)
            if cached:
                self.artwork_cache.move_to_end(key)
                return cached[1]
            metadata = await self.control.plex_get(policy, "/library/metadata/" + rating_key)
            entry = next((e for e in metadata if e.get("ratingKey") == rating_key), None)
            path = thumbnail_path(entry) if entry is not None else None
            if not path:
                raise DomainError("plex_artwork_missing", "Plex cover is unavailable", 404)
            try:
                result = await asyncio.wait_for(self.fetch_artwork(policy, path), 10)
            except TimeoutError:
                raise DomainError(
                    "plex_artwork_unavailable", "Plex cover is unavailable", 503
                ) from None
            self.artwork_cache[key] = (time.monotonic() + 300, result)
            while len(self.artwork_cache) > 32:
                self.artwork_cache.popitem(last=False)
            return result

    async def fetch_artwork(self, policy, path):
        if not THUMB_PATH.fullmatch(path):
            raise DomainError("plex_artwork_missing", "Plex cover is unavailable", 404)
        try:
            api_url, token = await self.control.plex_connection(policy)
            if not token:
                raise ValueError()
            async with httpx.AsyncClient(
                timeout=8, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream(
                    "GET",
                    api_url + "/photo/:/transcode",
                    headers={"X-Plex-Token": token},
                    params={"url": path, "width": 240, "height": 360, "minSize": 1, "upscale": 0},
                ) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                        raise ValueError()
                    if int(response.headers.get("content-length", "0")) > MAX_ARTWORK_BYTES:
                        raise ValueError()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > MAX_ARTWORK_BYTES:
                            raise ValueError()
                        data.extend(chunk)
                    content = bytes(data)
                    if not valid_artwork(content, content_type):
                        raise ValueError()
                    return {
                        "contentType": content_type,
                        "content": base64.b64encode(content).decode("ascii"),
                    }
        except (OSError, ValueError, KeyError, httpx.HTTPError):
            raise DomainError(
                "plex_artwork_unavailable", "Plex cover is unavailable", 503
            ) from None
