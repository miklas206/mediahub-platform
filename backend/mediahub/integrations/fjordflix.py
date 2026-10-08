"""Bounded FjordFlix metadata and same-origin, fixed-path poster handling."""

import math
import re
from urllib.parse import urlsplit

import httpx

from mediahub.integrations.fjordhub import ProviderFailure

POSTER_PATH = "/api/integrations/v1/app-data/fjordflix/posters/"
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
ERRORS = {
    401: "FjordHub Access Token is invalid or expired.",
    403: "Select FjordFlix for this token and ensure LAN access.",
    404: "FjordFlix is missing or needs an update.",
    503: "FjordFlix data is unavailable.",
}


def poster_id(url, origin):
    if not isinstance(url, str) or len(url) > 1000:
        return None
    # Reject noncanonical and encoded paths rather than trying to decode them.
    if any(ord(c) < 33 for c in url) or any(c in url for c in "%\\?#"):
        return None
    try:
        parsed, base = urlsplit(url), urlsplit(origin)
        if parsed.scheme or parsed.netloc:
            if (
                parsed.scheme != base.scheme
                or parsed.netloc != base.netloc
                or parsed.username
                or parsed.password
            ):
                return None
        suffix = parsed.path.removeprefix(POSTER_PATH)
        return (
            suffix if parsed.path.startswith(POSTER_PATH) and IDENTIFIER.fullmatch(suffix) else None
        )
    except ValueError:
        return None


def normalize(client, body):
    if not isinstance(body, dict) or body.get("ok") is not True:
        status = body.get("status", 503) if isinstance(body, dict) else 503
        status = status if type(status) is int and status in ERRORS else 503
        return {"ok": False, "status": status, "error": ERRORS[status]}
    if not isinstance(body.get("items"), list) or not isinstance(body.get("streams"), list):
        return {"ok": False, "status": 503, "error": ERRORS[503]}

    def rows(values, limit, stream=False):
        output = []
        strings = ["id", "title", "overview", "release_date", "media_type", "series_title"]
        numbers = ["rating", "season", "episode"]
        if stream:
            strings = [
                "id",
                "movie_id",
                "title",
                "user",
                "client",
                "state",
                "mode",
                "video",
                "audio",
                "subtitle",
                "encoder",
            ]
            numbers = ["position", "duration", "height", "mbps"]
        for value in values[:limit]:
            if not isinstance(value, dict):
                continue
            row = {
                key: client.text(value[key], 2000 if key == "overview" else 300)
                for key in strings
                if isinstance(value.get(key), str)
            }
            for key in numbers:
                number = value.get(key)
                if (
                    isinstance(number, (int, float))
                    and not isinstance(number, bool)
                    and 0 <= number < 1e12
                    and math.isfinite(number)
                ):
                    row[key] = number
            if not stream and isinstance(value.get("genres"), list):
                row["genres"] = [
                    client.text(genre, 80)
                    for genre in value["genres"][:20]
                    if isinstance(genre, str)
                ]
            identifier = poster_id(value.get("poster_url"), client.base_url)
            if identifier and client._access_token not in identifier:
                row["poster_id"] = identifier
            output.append(row)
        return output

    count = body.get("library_count")
    return {
        "ok": True,
        "stale": False,
        "generated_at": client.text(body.get("generated_at"), 80),
        "library_count": count if type(count) is int and 0 <= count < 1e12 else None,
        "items": rows(body["items"], 10),
        "streams": rows(body["streams"], 100, True),
    }


async def fetch_poster(client, identifier):
    if not IDENTIFIER.fullmatch(identifier) or client._access_token in identifier:
        raise ProviderFailure("poster_unavailable")
    async with httpx.AsyncClient(
        base_url=client.base_url,
        headers={"Authorization": "Bearer " + client._access_token},
        timeout=5,
        follow_redirects=False,
        trust_env=False,
        transport=client._transport,
    ) as transport:
        async with transport.stream("GET", POSTER_PATH + identifier) as response:
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if response.status_code != 200 or content_type not in {
                "image/jpeg",
                "image/png",
                "image/webp",
            }:
                raise ProviderFailure("poster_unavailable")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 5 * 1024 * 1024:
                    raise ProviderFailure("poster_unavailable")
            signatures = {
                "image/jpeg": data.startswith(b"\xff\xd8\xff"),
                "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
                "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
            }
            if not signatures[content_type]:
                raise ProviderFailure("poster_unavailable")
            return bytes(data), content_type
