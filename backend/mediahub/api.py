import asyncio
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import text

from mediahub import __version__
from mediahub.auth import COOKIE
from mediahub.contracts import PlatformSettings, StorageInput, StrictModel
from mediahub.errors import DomainError
from mediahub.logging import recent_logs
from mediahub.network import cookie_options
from mediahub.platform_updates import GitHubReleaseProvider

router = APIRouter()


def result(data):
    return {"data": data, "error": None, "metadata": {"version": __version__}}


def services(request: Request):
    return request.app.state.services


def authenticated(request: Request):
    svc = services(request)
    user = svc.auth.authenticate(request.cookies.get(COOKIE))
    if user.get("totpRequired") and not user.get("totpEnabled"):
        path = request.url.path.removeprefix("/api/v1").removeprefix("/api")
        if not (path.startswith("/security") or path in {"/auth/me", "/auth/logout"}):
            raise DomainError(
                "enrollment_required", "Set up two-factor authentication to continue", 403
            )
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-mediahub-csrf", "")
        if not secrets.compare_digest(csrf, user["csrf"]):
            raise DomainError(
                "csrf_rejected", "Session verification failed. Reload and try again.", 403
            )
    return user


def administrator(user=Depends(authenticated)):
    if user.get("role") != "administrator":
        raise DomainError("administrator_required", "Administrator access is required", 403)
    return user


class Credentials(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    secondFactor: str = Field(default="", max_length=32)


class PathRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)


class GitHubTokenRequest(StrictModel):
    token: str = Field(min_length=20, max_length=512)


class RemoveRuntimeRequest(StrictModel):
    confirmedInstallationId: str = Field(min_length=1, max_length=80)


@router.get("/health")
async def health(request: Request):
    with services(request).sessions() as db:
        db.execute(text("SELECT 1"))
    return result({"status": "healthy", "version": __version__})


@router.get("/auth/status")
async def auth_status(request: Request):
    return result({"needsSetup": services(request).auth.needs_setup()})


@router.post("/auth/login")
async def login(body: Credentials, request: Request, response: Response):
    svc = services(request)
    cookies = cookie_options(request, svc.config)
    client = request.client.host if request.client else "local"
    token, user = svc.auth.login(body.username, body.password, client, body.secondFactor)
    response.set_cookie(
        COOKIE,
        token,
        **cookies,
        max_age=svc.config.session_hours * 3600,
    )
    return result(user)


@router.get("/auth/me")
async def me(user=Depends(authenticated)):
    return result(user)


@router.post("/auth/logout")
async def logout(request: Request, response: Response, user=Depends(authenticated)):
    services(request).auth.logout(request.cookies[COOKIE])
    response.delete_cookie(COOKIE, path="/")
    return result({"signedOut": True})


@router.get("/system/status")
async def system_status(request: Request, user=Depends(authenticated)):
    return result(services(request).snapshot)


@router.get("/apps")
async def apps(request: Request, user=Depends(authenticated)):
    svc = services(request)
    return result(
        [
            {**app, "health": (await svc.apps.health(app["id"])).model_dump()}
            for app in svc.apps.list()
        ]
    )


@router.get("/apps/{app_id}")
async def app_detail(app_id: str, request: Request, user=Depends(authenticated)):
    return result(services(request).apps.get(app_id))


@router.get("/apps/{app_id}/health")
async def app_health(app_id: str, request: Request, user=Depends(authenticated)):
    return result((await services(request).apps.health(app_id)).model_dump())


@router.get("/apps/{app_id}/runtime")
async def app_runtime(app_id: str, request: Request, user=Depends(authenticated)):
    adapter = services(request).apps.adapter(app_id)
    if not hasattr(adapter, "definition"):
        raise DomainError("runtime_unavailable", "This app has no remote runtime view", 404)
    return result(
        {
            "view": adapter.definition.view_id,
            "report": await adapter.status(),
            "operatorUrl": services(request).config.operator_app_urls.get(
                adapter.definition.package_id
            ),
        }
    )


@router.post("/apps/{app_id}/actions/{action}")
async def app_action(
    app_id: str,
    action: Literal["start", "stop", "restart", "restart-vpn", "restart-qbittorrent", "test-vpn"],
    request: Request,
    user=Depends(administrator),
):
    return result({"state": await services(request).apps.action(app_id, action)})


@router.get("/apps/{app_id}/logs")
async def app_logs(app_id: str, request: Request, user=Depends(authenticated)):
    from mediahub.apps.remote_status import RuntimeEvent

    payload = await services(request).apps.adapter(app_id).logs()
    return result(
        {
            "entries": [
                RuntimeEvent.model_validate(row).model_dump()
                for row in payload.get("entries", [])[-100:]
            ]
        }
    )


@router.post("/apps/{app_id}/update-check")
async def app_update_check(app_id: str, request: Request, user=Depends(administrator)):
    return result(await services(request).apps.adapter(app_id).updateCheck())


@router.post("/apps/{app_id}/uninstall")
async def remove_runtime(
    app_id: str, body: RemoveRuntimeRequest, request: Request, user=Depends(administrator)
):
    adapter = services(request).apps.adapter(app_id)
    if not hasattr(adapter, "definition"):
        raise DomainError(
            "unsupported_action", "Runtime-only removal is not supported by this app", 400
        )
    return result(await adapter.uninstall(body.confirmedInstallationId))


@router.get("/storage")
async def storage(request: Request, user=Depends(authenticated)):
    return result(services(request).storage.list())


@router.post("/storage/validate")
async def storage_validate(body: PathRequest, request: Request, user=Depends(authenticated)):
    return result(services(request).storage.validate(body.path))


@router.post("/storage", status_code=201)
async def storage_register(body: StorageInput, request: Request, user=Depends(authenticated)):
    return result(services(request).storage.register(body))


@router.get("/activity")
async def activity(
    request: Request, limit: int | None = Query(None, ge=1, le=100), user=Depends(authenticated)
):
    svc = services(request)
    return result(svc.events.activity(limit or svc.settings.get().activity_page_size))


@router.get("/settings")
async def settings(request: Request, user=Depends(authenticated)):
    return result(services(request).settings.get().model_dump())


@router.get("/updates/platform")
async def platform_update(request: Request, user=Depends(authenticated)):
    svc = services(request)
    repository = svc.settings.get().release_repository
    return result(
        await GitHubReleaseProvider(__version__).check(repository, svc.release_credentials.token())
    )


@router.get("/updates/platform/credentials")
async def platform_update_credentials(request: Request, user=Depends(administrator)):
    return result(services(request).release_credentials.status())


@router.put("/updates/platform/credentials")
async def save_platform_update_credentials(
    body: GitHubTokenRequest, request: Request, user=Depends(administrator)
):
    configured = services(request).release_credentials.save(body.token)
    services(request).events.record(
        "updates.credentials.changed", "core", "Private release access was replaced"
    )
    return result(configured)


@router.delete("/updates/platform/credentials")
async def remove_platform_update_credentials(request: Request, user=Depends(administrator)):
    configured = services(request).release_credentials.remove()
    services(request).events.record(
        "updates.credentials.removed", "core", "Private release access was removed"
    )
    return result(configured)


@router.put("/settings")
async def save_settings(body: PlatformSettings, request: Request, user=Depends(authenticated)):
    svc = services(request)
    saved = svc.settings.save(body)
    svc.events.record("settings.updated", "core", "Platform settings updated")
    return result(saved.model_dump())


@router.get("/logs")
async def logs(request: Request, user=Depends(authenticated)):
    return result(list(recent_logs)[-100:])


@router.get("/events/stream")
async def stream(request: Request, user=Depends(authenticated)):
    svc = services(request)
    token = request.cookies.get(COOKIE)
    if len(svc.events.subscribers) >= 32:
        raise DomainError("stream_limit", "Too many live connections", 429)

    async def generate():
        queue = asyncio.Queue(maxsize=32)
        svc.events.subscribers.add(queue)
        try:
            yield "retry: 5000\n\n"
            yield svc.events.encode({"type": "system.status", "data": svc.snapshot})
            for app in svc.apps.list():
                yield svc.events.encode(
                    {
                        "type": "app.health.changed",
                        "data": {
                            "id": app["id"],
                            "health": (await svc.apps.health(app["id"])).model_dump(),
                        },
                    }
                )
            while not await request.is_disconnected():
                try:
                    svc.auth.authenticate(token)
                except DomainError:
                    yield "event: session.expired\ndata: {}\n\n"
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=svc.config.sample_seconds)
                    yield svc.events.encode(event)
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            svc.events.subscribers.discard(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
