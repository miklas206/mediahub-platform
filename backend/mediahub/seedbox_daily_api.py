"""Admin, CSRF and HTTPS guarded everyday operations; private inputs stay in RAM."""

from fastapi import APIRouter, Depends, Request

from mediahub.api import administrator, result
from mediahub.apps.seedbox_daily import AddTorrent, TorrentAction, VPNLocation
from mediahub.seedbox_wizard_api import target

router = APIRouter(prefix="/seedbox", dependencies=[Depends(administrator)])


@router.get("/torrents")
async def torrents(request: Request):
    return result(await target(request).request("GET", "/v1/seedbox/torrents"))


@router.post("/torrents/add")
async def add(body: AddTorrent, request: Request):
    return result(
        await target(request).request("POST", "/v1/seedbox/torrents/add", body.private_payload())
    )


@router.post("/torrents/action")
async def action(body: TorrentAction, request: Request):
    return result(
        await target(request).request("POST", "/v1/seedbox/torrents/action", body.model_dump())
    )


@router.get("/locations")
async def locations(request: Request):
    return result(await target(request).request("GET", "/v1/seedbox/locations"))


@router.post("/locations", status_code=202)
async def change_location(body: VPNLocation, request: Request):
    return result(await target(request).request("POST", "/v1/seedbox/locations", body.model_dump()))
