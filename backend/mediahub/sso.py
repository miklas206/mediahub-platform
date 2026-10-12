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

router = APIRouter()


class Exchange(StrictModel):
    packageId: str = Field(max_length=120)
    code: str = Field(min_length=40, max_length=128)
    verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")


def configured_app(svc, package_id):
    from mediahub.app_settings import saved_address
    from mediahub.managed_apps import unavailable

    origin = svc.config.sso_app_urls.get(package_id)
    if not origin or unavailable(svc, package_id):
        raise DomainError("sso_unavailable", "SSO is not configured for this installed app", 409)
    return saved_address(svc, package_id) or origin


@router.get("/sso/origin")
def app_origin(request: Request, packageId: str):
    # Public configuration only; identities and grants remain authenticated.
    return result({"origin": configured_app(services(request), packageId)})


def identity(svc, db, grant):
    parent = db.get(Session, grant["sessionId"])
    if parent is None or parent.expires_at <= int(time.time()):
        raise DomainError("unauthorized", "Hub session expired", 401)
    user = db.get(User, parent.user_id)
    if user is None:
        raise DomainError("unauthorized", "User no longer exists", 401)
    svc.auth.authenticate_session_policy(db, user)
    role = svc.auth.app_role(user.id, grant["packageId"])
    return {"id": user.id, "username": user.username, "role": role,
            "language": svc.settings.user_preferences(user.id).language}


@router.get("/sso/authorize")
def authorize(request: Request, packageId: str, state: str = Query(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"), challenge: str = Query(pattern=r"^[A-Za-z0-9_-]{43}$")):
    svc = services(request)
    origin = configured_app(svc, packageId)
    try:
        user = authenticated(request)
    except DomainError as error:
        if error.status != 401 and error.code != "enrollment_required":
            raise
        resume = "/api/v1/sso/authorize?" + urlencode({"packageId": packageId, "state": state, "challenge": challenge})
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
