"""Plex module installation. All mutations use authenticated, CSRF-protected HTTPS."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.apps.plex import PlexInstallation, PlexInstallRequest
from mediahub.apps.remote_registry import register_remote_apps
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError

router = APIRouter(prefix="/plex", dependencies=[Depends(administrator)])


def target(request, host="local"):
    if request.url.scheme != "https":
        raise DomainError("https_required", "Use HTTPS to configure Plex", 403)
    client = services(request).hosts.client(host)
    if urlsplit(client.config.agent_url).scheme != "https":
        raise DomainError("agent_tls_required", "Plex requires a trusted HTTPS Agent", 409)
    return client


@router.get("/install-options")
async def options(request: Request, host: str = "local"):
    return result(await target(request, host).request("GET", "/v1/plex/install-options"))


@router.post("/install-plan")
async def plan(body: PlexInstallation, request: Request):
    return result(
        await target(request, body.hostId).request(
            "POST", "/v1/plex/install-plan", body.model_dump()
        )
    )


@router.post("/install", status_code=202)
async def install(body: PlexInstallRequest, request: Request):
    svc = services(request)
    payload = body.model_dump()
    if body.claimToken:
        payload["claimToken"] = body.claimToken.get_secret_value()
    response = await target(request, body.installation.hostId).request(
        "POST", "/v1/plex/install", payload
    )
    with svc.sessions.begin() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "plex_installation"))
        if binding is None:
            db.add(Setting(key="plex_installation", value=body.installation.model_dump()))
        else:
            binding.value = body.installation.model_dump()
        app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == "org.mediahub.plex"))
        if app is None:
            db.add(
                InstalledApp(
                    package_id="org.mediahub.plex",
                    name="Plex",
                    version="unknown",
                    state="starting",
                    is_mock=False,
                )
            )
        else:
            app.state, app.is_mock = "starting", False
    register_remote_apps(svc)
    svc.events.record(
        "app.installed", "org.mediahub.plex", "Plex installation started; media preserved"
    )
    return result(response)


async def installed_action(request, action):
    svc = services(request)
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "plex_installation"))
        if binding is None:
            raise DomainError("plex_not_installed", "Install Plex first", 409)
        host = binding.value["hostId"]
    response = await target(request, host).request("POST", "/v1/plex/" + action)
    svc.events.record("plex." + action, "org.mediahub.plex", "Plex " + action + " requested")
    return result(response)


@router.post("/update", status_code=202)
async def update(request: Request):
    return await installed_action(request, "update")


@router.post("/rollback")
async def rollback(request: Request):
    return await installed_action(request, "rollback")
