import json
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request

from mediahub.api import authenticated, result, services

router = APIRouter()


def app_origin(value):
    if not value:
        return None
    parsed = urlsplit(value)
    try:
        address = ip_address(parsed.hostname or "")
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not (address.is_private or address.is_loopback)
        or address.is_unspecified
        or address.is_multicast
        or address.is_link_local
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return value.rstrip("/")


async def available(origin):
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", origin + "/healthz") as response:
                if response.status_code != 200:
                    return False
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 4096:
                        return False
                    content.extend(chunk)
                payload = json.loads(content)
                return isinstance(payload, dict) and payload.get("status") == "healthy" and isinstance(payload.get("version"), str)
    except (httpx.HTTPError, ValueError):
        return False


@router.get("/mediaseed/status")
async def status(request: Request, user=Depends(authenticated)):
    origin = app_origin(services(request).config.operator_app_urls.get("org.mediahub.mediaseed"))
    if origin is None:
        return result({"configured": False, "available": False, "url": None})
    return result({"configured": True, "available": await available(origin), "url": origin, "preview": True})


@router.get("/mediavpn/status")
async def vpn_status(request: Request, user=Depends(authenticated)):
    origin = app_origin(services(request).config.operator_app_urls.get("org.mediahub.mediavpn"))
    if origin is None:
        return result({"configured": False, "available": False, "url": None})
    return result({"configured": True, "available": await available(origin), "url": origin, "preview": True})