"""Small, credential-free Plex artwork contracts shared with the paired Agent."""

from typing import Literal

from pydantic import Field

from mediahub.contracts import StrictModel

MAX_RECENT_MEDIA = 8
MAX_ARTWORK_BYTES = 512 * 1024
RATING_KEY_PATTERN = r"^[0-9]{1,20}$"


class PlexMediaItem(StrictModel):
    id: str = Field(pattern=RATING_KEY_PATTERN)
    title: str = Field(min_length=1, max_length=300)
    type: Literal["movie", "show", "season", "episode"]
    year: int | None = Field(default=None, ge=1800, le=3000)
    hasArtwork: bool = False


class PlexRecentMedia(StrictModel):
    supported: Literal[True] = True
    items: list[PlexMediaItem] = Field(max_length=MAX_RECENT_MEDIA)


class PlexArtwork(StrictModel):
    contentType: Literal["image/jpeg", "image/png", "image/webp"]
    content: str = Field(min_length=1, max_length=4 * ((MAX_ARTWORK_BYTES + 2) // 3))


def valid_artwork(content: bytes, content_type: str) -> bool:
    """Reject active formats and mismatched responses before serving same-origin images."""
    if not 0 < len(content) <= MAX_ARTWORK_BYTES:
        return False
    return (
        content_type == "image/jpeg"
        and content.startswith(b"\xff\xd8\xff")
        or content_type == "image/png"
        and content.startswith(b"\x89PNG\r\n\x1a\n")
        or content_type == "image/webp"
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    )
