"""Authenticated self-service security. Responses never expose stored credentials."""

import secrets
import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import delete, select

from mediahub.api import administrator, authenticated, result, services
from mediahub.auth import COOKIE, digest, hasher
from mediahub.contracts import StrictModel
from mediahub.db import Session, Setting, UserSecurity
from mediahub.errors import DomainError
from mediahub.network import cookie_options

router = APIRouter(prefix="/security")


class VerifyIdentity(StrictModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(default="", max_length=32)


class ConfirmCode(StrictModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


class NewPassword(VerifyIdentity):
    newPassword: str = Field(min_length=12, max_length=256)


class SecurityPolicy(VerifyIdentity):
    requireTotp: bool


def sensitive(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.get("")
def status(request: Request, user=Depends(authenticated)):
    with services(request).sessions() as db:
        row = db.get(UserSecurity, user["id"])
        policy = db.scalar(select(Setting).where(Setting.key == "authentication_policy"))
        return result(
            {
                "totpEnabled": bool(row and row.enabled),
                "requireTotp": bool(policy and policy.value.get("requireTotp")),
                "recoveryCodesRemaining": len(row.recovery_hashes) if row and row.enabled else 0,
            }
        )


@router.post("/policy")
def policy(body: SecurityPolicy, request: Request, user=Depends(administrator)):
    svc = services(request)
    with svc.sessions.begin() as db:
        svc.auth.reauthenticate(db, user["id"], body.password, body.code)
        security = db.get(UserSecurity, user["id"])
        if body.requireTotp and not (security and security.enabled):
            raise DomainError(
                "enroll_first", "Enable your own authenticator before requiring it", 409
            )
        row = db.scalar(select(Setting).where(Setting.key == "authentication_policy"))
        if row is None:
            db.add(Setting(key="authentication_policy", value={"requireTotp": body.requireTotp}))
        else:
            row.value = {"requireTotp": body.requireTotp}
    return result({"requireTotp": body.requireTotp})


@router.post("/totp/disable")
def disable(
    body: VerifyIdentity, request: Request, response: Response, user=Depends(authenticated)
):
    svc = services(request)
    with svc.sessions.begin() as db:
        svc.auth.reauthenticate(db, user["id"], body.password, body.code)
        policy = db.scalar(select(Setting).where(Setting.key == "authentication_policy"))
        if policy and policy.value.get("requireTotp"):
            raise DomainError(
                "totp_required", "Your security policy requires two-factor authentication", 409
            )
        row = db.get(UserSecurity, user["id"])
        if row:
            row.enabled = False
            row.secret_reference = None
            row.recovery_hashes = []
            row.pending_expires = 0
        db.execute(delete(Session).where(Session.user_id == user["id"]))
    response.delete_cookie(COOKIE, path="/")
    svc.events.record(
        "security.totp_disabled", "auth", "Two-factor authentication disabled; sessions revoked"
    )
    return result({"signInAgain": True})


@router.post("/totp/enroll")
def enroll(body: VerifyIdentity, request: Request, response: Response, user=Depends(authenticated)):
    svc = services(request)
    with svc.sessions.begin() as db:
        account = svc.auth.reauthenticate(db, user["id"], body.password, body.code)
        data = svc.auth.mfa.begin(db, account)
    sensitive(response)
    return result(data)


@router.post("/totp/confirm")
def confirm(body: ConfirmCode, request: Request, response: Response, user=Depends(authenticated)):
    svc = services(request)
    svc.auth.throttle("security:" + user["id"])
    with svc.sessions.begin() as db:
        data = svc.auth.mfa.confirm(db, user["id"], body.code)
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.add(
            Session(
                user_id=user["id"],
                token_hash=digest(token),
                csrf_token=csrf,
                expires_at=int(time.time() + svc.config.session_hours * 3600),
            )
        )
        data.update(signInAgain=False, csrf=csrf)
    sensitive(response)
    response.set_cookie(
        COOKIE,
        token,
        **cookie_options(request, svc.config),
        max_age=svc.config.session_hours * 3600,
    )
    svc.events.record("security.totp_enabled", "auth", "Two-factor authentication enabled")
    return result(data)


@router.post("/totp/recovery-codes")
def recovery(
    body: VerifyIdentity, request: Request, response: Response, user=Depends(authenticated)
):
    svc = services(request)
    with svc.sessions.begin() as db:
        svc.auth.reauthenticate(db, user["id"], body.password, body.code)
        row = db.get(UserSecurity, user["id"])
        if not row or not row.enabled:
            raise DomainError("totp_not_enabled", "Enable two-factor authentication first", 409)
        codes = svc.auth.mfa.recovery_codes(row)
    sensitive(response)
    return result({"recoveryCodes": codes})


@router.post("/password")
def password(body: NewPassword, request: Request, response: Response, user=Depends(authenticated)):
    svc = services(request)
    with svc.sessions.begin() as db:
        account = svc.auth.reauthenticate(db, user["id"], body.password, body.code)
        account.password_hash = hasher.hash(body.newPassword)
        db.execute(delete(Session).where(Session.user_id == account.id))
    response.delete_cookie(COOKIE, path="/")
    svc.events.record("security.password_changed", "auth", "Password changed; sessions revoked")
    return result({"signInAgain": True})


@router.get("/sessions")
def sessions(request: Request, user=Depends(authenticated)):
    current = digest(request.cookies.get(COOKIE, ""))
    with services(request).sessions() as db:
        rows = db.scalars(
            select(Session).where(
                Session.user_id == user["id"], Session.expires_at > int(time.time())
            )
        )
        return result(
            [
                {
                    "id": s.id,
                    "createdAt": s.created_at,
                    "expiresAt": s.expires_at,
                    "current": s.token_hash == current,
                }
                for s in rows
            ]
        )


@router.delete("/sessions/{session_id}")
def revoke(session_id: str, request: Request, user=Depends(authenticated)):
    with services(request).sessions.begin() as db:
        db.execute(delete(Session).where(Session.id == session_id, Session.user_id == user["id"]))
    return result({"revoked": True})
