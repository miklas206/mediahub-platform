import base64
import threading
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from mediahub.api import administrator, result, services
from mediahub.backups import CoreBackup
from mediahub.errors import DomainError
from mediahub.security_api import VerifyIdentity

router = APIRouter(prefix="/backups")
backup_lock = threading.Lock()


class BackupRequest(VerifyIdentity):
    backupPassword: str = Field(min_length=16, max_length=256)


@router.get("")
def status(user=Depends(administrator)):
    return result(
        {
            "coreExportAvailable": True,
            "encrypted": True,
            "includes": [
                "Core database",
                "Settings and logical storage mappings",
                "Encrypted Core secrets and recovery keys",
            ],
            "excludes": [
                "Media files",
                "Plex database and appdata",
                "Seedbox runtime and configuration",
                "External certificates and deployment files",
            ],
            "automaticMediaBackup": False,
            "restoreMode": "offline-only",
        }
    )


@router.post("/export")
def export(body: BackupRequest, request: Request, user=Depends(administrator)):
    svc = services(request)
    if request.url.scheme != "https" and not svc.config.dev_mode:
        raise DomainError("https_required", "Configuration backups require HTTPS", 403)
    with svc.sessions.begin() as db:
        svc.auth.reauthenticate(db, user["id"], body.password, body.code)
    if not backup_lock.acquire(blocking=False):
        raise DomainError("backup_busy", "Another configuration backup is running", 409)
    try:
        content = CoreBackup(svc).create(body.backupPassword)
    finally:
        backup_lock.release()
    svc.events.record(
        "backup.created",
        "core",
        "Encrypted Core configuration exported; media and app data excluded",
    )
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="mediahub-core.mhbackup"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.post("/apps/{application}/export")
async def export_app(
    application: Literal["plex", "seedbox"],
    body: BackupRequest,
    request: Request,
    user=Depends(administrator),
):
    from mediahub.app_backups import LIMIT, verify_archive
    from mediahub.plex_api import target as plex_target
    from mediahub.seedbox_wizard_api import target as seedbox_target

    svc = services(request)
    if request.url.scheme != "https":
        raise DomainError("https_required", "App backups require HTTPS", 403)
    with svc.sessions.begin() as db:
        svc.auth.reauthenticate(db, user["id"], body.password, body.code)
    client = plex_target(request) if application == "plex" else seedbox_target(request)
    reply = await client.request(
        "POST", f"/v1/backups/{application}/export", {"password": body.backupPassword}
    )
    try:
        encoded = reply["archiveBase64"]
        if len(encoded) > (LIMIT + 1024**2) * 4 // 3 + 4:
            raise ValueError()
        content = base64.b64decode(encoded, validate=True)
        metadata = verify_archive(content, body.backupPassword)
        if metadata["app"] != application:
            raise ValueError()
    except Exception:
        raise DomainError("backup_invalid", "Agent backup validation failed", 409) from None
    svc.events.record(
        "backup.created", application, "Encrypted app configuration exported; media excluded"
    )
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="mediahub-{application}.mhbackup"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )
