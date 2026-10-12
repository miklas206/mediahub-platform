import json
import asyncio
import secrets
import ssl
import time
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Request

from mediahub.api import authenticated, result, services
from mediahub.managed_apps import unavailable
from mediahub.auth import COOKIE, digest
from mediahub.db import Session, Setting
from mediahub.errors import DomainError
from sqlalchemy import delete, select

router = APIRouter()


async def overview_for(request, user, package):
    svc = services(request)
    token = secrets.token_urlsafe(48)
    key = "sso:session:" + digest(token)
    try:
        from mediahub.sso import configured_app
        origin = configured_app(svc, package)
        svc.auth.app_role(user["id"], package)
        with svc.sessions.begin() as db:
            db.execute(delete(Setting).where(Setting.key.like("sso:session:%"), Setting.value["scope"].as_string() == "overview", Setting.value["expires"].as_integer() <= int(time.time())))
            parent = db.scalar(select(Session).where(Session.token_hash == digest(request.cookies.get(COOKIE, ""))))
            if parent is None or parent.expires_at <= int(time.time()):
                return {"status": "unavailable"}
            db.add(Setting(key=key, value={"sessionId": parent.id, "packageId": package, "scope": "overview", "expires": min(parent.expires_at, int(time.time()) + 30)}))
        verify = ssl.create_default_context(cafile=str(svc.config.agent_ca_file)) if svc.config.agent_ca_file else True
        async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False, verify=verify) as client:
            async with client.stream("GET", origin + "/api/hub/overview", headers={"Authorization": "Bearer " + token}) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > 1024 * 1024:
                        raise ValueError("Overview response too large")
                    content.extend(chunk)
                data = json.loads(content)
                if not isinstance(data, dict):
                    raise ValueError("Invalid overview")
                return {"status": "ok", "data": data}
    except DomainError as error:
        return {"status": "denied" if error.status == 403 else "not_configured"}
    except (httpx.HTTPError, ValueError, OSError):
        return {"status": "unavailable"}
    finally:
        with svc.sessions.begin() as db:
            db.execute(delete(Setting).where(Setting.key == key))


@router.get("/app-overview")
async def app_overview(request: Request, user=Depends(authenticated)):
    seed, vpn = await asyncio.gather(*(overview_for(request, user, "org.mediahub." + app) for app in ("mediaseed", "mediavpn")))
    return result({"mediaseed": seed, "mediavpn": vpn})


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


async def available(origin, ca_file=None):
    try:
        verify = ssl.create_default_context(cafile=str(ca_file)) if ca_file else True
        async with httpx.AsyncClient(timeout=3, follow_redirects=False, trust_env=False, verify=verify) as client:
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
    if unavailable(services(request), "org.mediahub.mediaseed", removed_only=True):
        return result({"configured": False, "available": False, "url": None})
    origin = app_origin(services(request).config.operator_app_urls.get("org.mediahub.mediaseed"))
    if origin is None:
        return result({"configured": False, "available": False, "url": None})
    sso_origin = services(request).config.sso_app_urls.get("org.mediahub.mediaseed")
    if sso_origin:
        from mediahub.sso import configured_app
        sso_origin = configured_app(services(request), "org.mediahub.mediaseed")
    health = await available(origin, services(request).config.agent_ca_file) if sso_origin else await available(origin)
    return result({"configured": True, "available": health, "url": origin, **({"openUrl": sso_origin + "/auth/hub/start"} if sso_origin else {}), "preview": True})


@router.get("/mediavpn/status")
async def vpn_status(request: Request, user=Depends(authenticated)):
    if unavailable(services(request), "org.mediahub.mediavpn", removed_only=True):
        return result({"configured": False, "available": False, "url": None})
    origin = app_origin(services(request).config.operator_app_urls.get("org.mediahub.mediavpn"))
    if origin is None:
        return result({"configured": False, "available": False, "url": None})
    from mediahub.app_settings import saved_address

    sso_origin = services(request).config.sso_app_urls.get("org.mediahub.mediavpn")
    if sso_origin:
        from mediahub.sso import configured_app
        sso_origin = configured_app(services(request), "org.mediahub.mediavpn")
    external = sso_origin + "/auth/hub/start" if sso_origin else saved_address(services(request), "org.mediahub.mediavpn")
    return result({"configured": True, "available": await available(origin), "url": origin, **({"openUrl": external} if external else {}), "preview": True})
