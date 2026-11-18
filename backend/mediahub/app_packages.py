"""Administrator interface for the host's reviewed optional app packages."""

import json
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.responses import JSONResponse

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from mediahub.platform_update_runtime import RUNNING

App = Literal["plex-gpu-transcoder", "video-downloader", "mediaupload"]
router = APIRouter(prefix="/app-packages", dependencies=[Depends(administrator)])


class Selection(StrictModel):
    location: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_-]*$")


def status(root: Path, app: App):
    path = root / ("package-" + app + ".json")
    saved = json.loads(path.read_text()) if path.is_file() else {}
    for pending in [root / "request.json", *root.glob("package-running-*.json")]:
        try:
            job = json.loads(pending.read_text())
        except FileNotFoundError:
            continue
        if job.get("action") == "app_package" and job.get("app") == app:
            if job.get("operationId") != saved.get("operationId"):
                return {"state": "queued", "operationId": job["operationId"]}
    return {
        k: v for k, v in saved.items() if k in ("state", "version", "message", "operationId", "url")
    } or {"state": "ready"}


@router.get("/{app}")
def details(app: App, request: Request):
    updater = services(request).platform_update
    enabled = updater.available and updater._host_capability("publicAppPackages")
    return result(
        {
            "available": enabled,
            "firstLogin": enabled and (updater.root / ("first-login-" + app + ".json")).is_file(),
            **(status(updater.root, app) if enabled else {"state": "unavailable"}),
        }
    )


@router.post("/{app}", status_code=202)
def queue(app: App, body: Selection, request: Request):
    svc = services(request)
    svc.setup.require_complete()
    updater = svc.platform_update
    if not updater.available or not updater._host_capability("publicAppPackages"):
        raise DomainError(
            "app_packages_unavailable",
            "Update the Linux MediaHub host to enable app installation.",
            409,
        )
    operation = uuid.uuid4().hex
    root = updater.root
    if any(root.glob("package-running-*.json")) or updater.status()["state"] in RUNNING:
        raise DomainError("host_busy", "Wait for the current host operation to finish.", 409)
    job = {"action": "app_package", "app": app, "operationId": operation, "location": body.location}
    path = root / ("package-request-" + operation)
    try:
        with path.open("x") as f:
            json.dump(job, f)
        path.chmod(0o600)
        os.link(path, root / "request.json")
    except FileExistsError:
        raise DomainError(
            "host_busy", "Wait for the current host operation to finish.", 409
        ) from None
    finally:
        path.unlink(missing_ok=True)
    return result({"state": "queued", "operationId": operation})


@router.post("/{app}/first-login")
def first_login(app: App, request: Request):
    root = services(request).platform_update.root
    if root is None:
        raise DomainError("first_login_used", "The setup details have already been opened.", 409)
    claim = root / ("claimed-login-" + uuid.uuid4().hex)
    try:
        (root / ("first-login-" + app + ".json")).rename(claim)
    except FileNotFoundError:
        raise DomainError(
            "first_login_used", "The setup details have already been opened.", 409
        ) from None
    try:
        value = json.loads(claim.read_text())
        return JSONResponse(result(value), headers={"Cache-Control": "no-store"})
    finally:
        claim.unlink(missing_ok=True)
