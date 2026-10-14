import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import delete, select

from mediahub.api import authenticated, result, services
from mediahub.auth import COOKIE, digest
from mediahub.contracts import StrictModel
from mediahub.db import Session, Setting, User
from mediahub.errors import DomainError
from mediahub.shared_vpn import AppChoice, GatewayChoice
from mediahub.vpn_gateway import Credentials as GatewayCredentials
from mediahub.vpn_gateway import GatewayConfig, PlexPortChoice

router = APIRouter()


class Exchange(StrictModel):
    packageId: str = Field(max_length=120)
    code: str = Field(min_length=40, max_length=128)
    verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")


def configured_app(svc, package_id, app_origin=None):
    from mediahub.app_settings import saved_address
    from mediahub.managed_apps import unavailable

    origin = svc.config.sso_app_urls.get(package_id)
    if not origin or unavailable(svc, package_id):
        raise DomainError("sso_unavailable", "SSO is not configured for this installed app", 409)
    canonical = saved_address(svc, package_id) or origin
    if app_origin is not None:
        allowed = {origin, canonical, svc.config.operator_app_urls.get(package_id)}
        if app_origin not in allowed or not app_origin.startswith("https://"):
            raise DomainError("sso_origin", "This app login address is not registered", 403)
        return app_origin
    return canonical


@router.get("/sso/origin")
def app_origin(request: Request, packageId: str, appOrigin: str | None = Query(default=None, max_length=2048)):
    # Public configuration only; identities and grants remain authenticated.
    return result({"origin": configured_app(services(request), packageId, appOrigin)})


def identity(svc, db, grant):
    parent = db.get(Session, grant["sessionId"])
    if parent is None or parent.expires_at <= int(time.time()):
        raise DomainError("unauthorized", "Hub session expired", 401)
    user = db.get(User, parent.user_id)
    if user is None:
        raise DomainError("unauthorized", "User no longer exists", 401)
    svc.auth.authenticate_session_policy(db, user)
    role = svc.auth.app_role(user.id, grant["packageId"])
    preferences = svc.settings.user_preferences(user.id)
    return {"id": user.id, "username": user.username, "role": role,
            "language": preferences.language,
            "appearance": preferences.appearance.model_dump(mode="json") if preferences.appearance else None,
            "theme": svc.settings.get().theme}


@router.get("/sso/authorize")
def authorize(request: Request, packageId: str, state: str = Query(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"), challenge: str = Query(pattern=r"^[A-Za-z0-9_-]{43}$"), appOrigin: str | None = Query(default=None, max_length=2048)):
    svc = services(request)
    origin = configured_app(svc, packageId, appOrigin)
    try:
        user = authenticated(request)
    except DomainError as error:
        if error.status != 401 and error.code != "enrollment_required":
            raise
        resume = "/api/v1/sso/authorize?" + urlencode({"packageId": packageId, "state": state, "challenge": challenge, **({"appOrigin": origin} if appOrigin is not None else {})})
        return RedirectResponse("/?" + urlencode({"sso": resume}), status_code=303)
    svc.auth.app_role(user["id"], packageId)
    code = secrets.token_urlsafe(48)
    with svc.sessions.begin() as db:
        parent = db.scalar(select(Session).where(Session.token_hash == digest(request.cookies[COOKIE])))
        if parent is None or parent.expires_at <= int(time.time()):
            raise DomainError("unauthorized", "Hub session expired", 401)
        db.execute(delete(Setting).where(Setting.key.like("sso:%"), Setting.value["expires"].as_integer() <= int(time.time())))
        db.add(Setting(key="sso:code:" + digest(code), value={"sessionId": parent.id, "packageId": packageId, "challenge": challenge, "expires": int(time.time()) + 60}))
    return RedirectResponse(origin + "/auth/hub/callback?" + urlencode({"code": code, "state": state}), status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/sso/exchange")
def exchange(body: Exchange, request: Request):
    svc = services(request)
    configured_app(svc, body.packageId)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(body.verifier.encode()).digest()).decode().rstrip("=")
    token = secrets.token_urlsafe(48)
    with svc.sessions.begin() as db:
        grant = db.execute(delete(Setting).where(Setting.key == "sso:code:" + digest(body.code), Setting.value["packageId"].as_string() == body.packageId, Setting.value["challenge"].as_string() == challenge, Setting.value["expires"].as_integer() > int(time.time())).returning(Setting.value)).scalar_one_or_none()
        if grant is None:
            raise DomainError("invalid_sso_code", "Login code is invalid or expired", 401)
        public = identity(svc, db, grant)
        parent = db.get(Session, grant["sessionId"])
        expires = min(parent.expires_at, int(time.time()) + 43200)
        db.add(Setting(key="sso:session:" + digest(token), value={"sessionId": parent.id, "packageId": body.packageId, "expires": expires}))
    return result({"token": token, "expires": expires, "user": public})


@router.get("/sso/session")
def session_identity(request: Request, packageId: str):
    svc = services(request)
    configured_app(svc, packageId)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not 40 <= len(token) <= 128:
        raise DomainError("unauthorized", "SSO session required", 401)
    with svc.sessions() as db:
        row = db.scalar(select(Setting).where(Setting.key == "sso:session:" + digest(token)))
        if row is None or row.value["packageId"] != packageId or row.value["expires"] <= int(time.time()):
            raise DomainError("unauthorized", "SSO session expired", 401)
        public = identity(svc, db, row.value)
        if row.value.get("scope"):
            public["scope"] = row.value["scope"]
        return result(public)


def vpn_administrator(request):
    svc = services(request)
    if request.url.scheme != "https" and not svc.config.dev_mode:
        raise DomainError("https_required", "Use HTTPS to manage shared VPN", 403)
    public = session_identity(request, "org.mediahub.mediavpn")["data"]
    with svc.sessions() as db:
        user = db.get(User, public["id"])
        if not user or user.role != "administrator" or public.get("scope"):
            raise DomainError("forbidden", "MediaHub administrator access required", 403)
    return svc.shared_vpn


@router.get("/sso/vpn/apps")
async def vpn_apps(request: Request):
    return result(await vpn_administrator(request).public())


@router.put("/sso/vpn/apps/{app_id}")
async def vpn_app_choice(app_id: str, body: AppChoice, request: Request):
    return result(await vpn_administrator(request).assign(app_id, body.enabled))


@router.put("/sso/vpn/gateway")
async def vpn_gateway_choice(body: GatewayChoice, request: Request):
    # Reuse the same orchestration lock and dedicated-Plex conflict checks.
    from mediahub.shared_vpn import gateway

    vpn_administrator(request)
    return await gateway(body, request)


@router.get("/sso/vpn-gateway")
async def web_gateway_status(request: Request):
    vpn_administrator(request)
    return result(await services(request).vpn_gateway.public())


@router.put("/sso/vpn-gateway/credentials")
async def web_gateway_credentials(body: GatewayCredentials, request: Request):
    vpn_administrator(request)
    return result(await services(request).vpn_gateway.credentials(body))


@router.put("/sso/vpn-gateway/config", status_code=202)
async def web_gateway_config(body: GatewayConfig, request: Request):
    vpn_administrator(request)
    return result(await services(request).vpn_gateway.configure(body))


@router.post("/sso/vpn-gateway/reconcile", status_code=202)
async def web_gateway_reconcile(request: Request):
    vpn_administrator(request)
    services(request).vpn_gateway.schedule()
    return result(services(request).vpn_gateway.snapshot())


@router.put("/sso/vpn-gateway/plex-port", status_code=202)
async def web_gateway_plex_port(body: PlexPortChoice, request: Request):
    vpn_administrator(request)
    return result(await services(request).vpn_gateway.configure_plex_port(body.enabled))
