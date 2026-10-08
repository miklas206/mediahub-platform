"""Read-only media previews; Core never exposes a Plex address or credential."""

import base64
import binascii
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import ValidationError

from mediahub.api import authenticated, result, services
from mediahub.apps.plex_media import (
    RATING_KEY_PATTERN,
    PlexArtwork,
    PlexRecentMedia,
    valid_artwork,
)
from mediahub.apps.remote_adapter import RemoteAppAdapter
from mediahub.errors import DomainError

router = APIRouter(dependencies=[Depends(authenticated)])


def plex_target(request, app_id):
    adapter = services(request).apps.adapter(app_id)
    if (
        not isinstance(adapter, RemoteAppAdapter)
        or adapter.definition.package_id != "org.mediahub.plex"
    ):
        raise DomainError("plex_media_unavailable", "This app has no Plex media preview", 404)
    return adapter.client_factory(adapter.host_id)


@router.get("/apps/{app_id}/plex/recent-media")
async def recent_media(app_id: str, request: Request):
    client = plex_target(request, app_id)
    try:
        payload = await client.request("GET", "/v1/plex/recent-media")
    except DomainError as error:
        if error.status in {404, 405, 501}:
            # Older paired Agents remain usable before their next update.
            return result({"supported": False, "items": []})
        raise
    try:
        media = PlexRecentMedia.model_validate(payload)
    except ValidationError:
        raise DomainError("plex_media_invalid", "Plex media preview is unavailable", 502) from None
    prefix = "/api/v1/apps/" + quote(app_id, safe="") + "/plex/artwork/"
    return result(
        {
            "supported": True,
            "items": [
                {
                    **item.model_dump(exclude={"hasArtwork"}),
                    "thumbnailUrl": prefix + item.id if item.hasArtwork else None,
                }
                for item in media.items
            ],
        }
    )


@router.get("/apps/{app_id}/plex/artwork/{rating_key}")
async def artwork(
    app_id: str,
    rating_key: Annotated[str, Path(pattern=RATING_KEY_PATTERN)],
    request: Request,
):
    payload = await plex_target(request, app_id).request("GET", "/v1/plex/artwork/" + rating_key)
    try:
        image = PlexArtwork.model_validate(payload)
        content = base64.b64decode(image.content, validate=True)
        if not valid_artwork(content, image.contentType):
            raise ValueError()
    except (ValidationError, ValueError, binascii.Error):
        raise DomainError("plex_artwork_invalid", "Plex cover is unavailable", 502) from None
    return Response(
        content,
        media_type=image.contentType,
        headers={
            "Cache-Control": "no-store",
            "Vary": "Cookie",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
