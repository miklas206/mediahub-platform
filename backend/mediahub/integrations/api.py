from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, SecretStr, field_validator
from sqlalchemy import select

from mediahub.api import authenticated, result, services
from mediahub.contracts import StrictModel
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.integrations.fjordhub import validate_url

router = APIRouter(prefix="/integrations")


class IntegrationInput(StrictModel):
    name: str = Field(default="FjordHub", min_length=1, max_length=80)
    baseUrl: str = Field(min_length=8, max_length=500)
    accessToken: SecretStr = Field(min_length=16, max_length=8192, exclude=True)
    allowHttp: bool = False

    @field_validator("accessToken")
    @classmethod
    def token_header(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value.get_secret_value()):
            raise ValueError("Invalid Access Token format")
        return value


class AppLaunchInput(StrictModel):
    url: SecretStr | None = Field(default=None, max_length=500, exclude=True)


class DetectionInput(StrictModel):
    name: str = Field(default="FjordHub", min_length=1, max_length=80)
    baseUrl: str = Field(min_length=8, max_length=500)
    allowHttp: bool = False


def require_https(request):
    if request.url.scheme != "https" and not services(request).config.dev_mode:
        raise DomainError("https_required", "Credential submission requires HTTPS", 403)


def require_admin(user):
    if user.get("role") != "administrator":
        raise DomainError(
            "administrator_required", "Integration changes require administrator access", 403
        )


@router.get("")
async def listing(request: Request, user=Depends(authenticated)):
    return result(services(request).integrations.list())


@router.get("/fjordhub/defaults")
async def defaults(request: Request, user=Depends(authenticated)):
    svc = services(request)
    with svc.sessions() as db:
        jobs = db.scalars(
            select(Setting)
            .where(Setting.key.startswith("fjordhub.deployment."))
            .order_by(Setting.created_at.desc())
            .limit(1)
        )
        for row in jobs:
            job = row.value
            if job.get("uninstall", {}).get("state") == "removed":
                return result({"baseUrl": None})
            # The guest emits this marker only after its health check. Proxmox
            # setup can fail afterwards, without making the guest URL invalid.
            # Never fall back to a different, older installation's address.
            for line in reversed(job.get("logs", [])):
                if line.startswith("MEDIAHUB_FJORDHUB_URL="):
                    try:
                        return result({"baseUrl": validate_url(line.split("=", 1)[1], True)})
                    except ValueError:
                        continue
            return result({"baseUrl": None})
    return result({"baseUrl": svc.config.fjordhub_url})


@router.post("/fjordhub/test")
async def test(body: IntegrationInput, request: Request, user=Depends(authenticated)):
    require_admin(user)
    require_https(request)
    return result(await services(request).integrations.test(body))


@router.post("/fjordhub/detect")
async def detect(body: DetectionInput, request: Request, user=Depends(authenticated)):
    require_admin(user)
    return result(await services(request).integrations.detect(body, reconnect=True))


@router.post("/fjordhub")
async def save(body: IntegrationInput, request: Request, user=Depends(authenticated)):
    require_admin(user)
    require_https(request)
    return result(services(request).integrations.save(body))


@router.get("/{identifier}/fjordflix/posters/{movie_id}")
async def poster(identifier: str, movie_id: str, request: Request, user=Depends(authenticated)):
    data, content_type = await services(request).integrations.poster(identifier, movie_id)
    return Response(
        data,
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.get("/{identifier}/updates")
async def updates(identifier: str, request: Request, user=Depends(authenticated)):
    return result(await services(request).integrations.updates(identifier))


@router.post("/{identifier}/updates/{app_id}/{action}")
async def update_action(
    identifier: str, app_id: str, action: str, request: Request, user=Depends(authenticated)
):
    require_admin(user)
    if action not in {"check", "start"}:
        raise DomainError("invalid_action", "Ugyldig opdateringshandling", 422)
    data = await services(request).integrations.updates(identifier, app_id, action)
    from fastapi.responses import JSONResponse

    accepted = data["updates"].get(app_id, {}).get("accepted") is True
    return JSONResponse(result(data), status_code=202 if accepted else 200)


@router.get("/{identifier}/apps/{app_id}/icon")
async def app_icon(identifier: str, app_id: str, request: Request, user=Depends(authenticated)):
    data, content_type = await services(request).integrations.icon(identifier, app_id)
    return Response(
        data,
        media_type=content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.put("/{identifier}/apps/{app_id}/launch-url")
async def app_launch_url(
    identifier: str,
    app_id: str,
    body: AppLaunchInput,
    request: Request,
    user=Depends(authenticated),
):
    require_admin(user)
    value = body.url.get_secret_value() if body.url is not None else None
    return result(services(request).integrations.set_launch_url(identifier, app_id, value))


@router.post("/{identifier}/refresh")
async def refresh(identifier: str, request: Request, user=Depends(authenticated)):
    require_admin(user)
    return result(await services(request).integrations.refresh(identifier))


@router.delete("/{identifier}")
async def remove(identifier: str, request: Request, user=Depends(authenticated)):
    require_admin(user)
    return result(services(request).integrations.remove(identifier))


@router.post("/{identifier}/disconnect")
async def disconnect(identifier: str, request: Request, user=Depends(authenticated)):
    require_admin(user)
    return result(services(request).integrations.disconnect(identifier))
