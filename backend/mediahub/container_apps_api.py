from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.apps.containers import CONTAINER_APPS, ContainerInstallation, ContainerInstallRequest
from mediahub.apps.remote_registry import register_remote_apps
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError

router = APIRouter(prefix="/container-apps", dependencies=[Depends(administrator)])


def target(request, host):
    if request.url.scheme != "https":
        raise DomainError("https_required", "Use HTTPS to install container apps", 403)
    client = services(request).hosts.client(host)
    if urlsplit(client.config.agent_url).scheme != "https":
        raise DomainError("agent_tls_required", "A trusted HTTPS Agent is required", 409)
    return client


def known_app(app):
    if app not in CONTAINER_APPS:
        raise DomainError("not_found", "Container app not found", 404)


@router.get("/{app}/install-options")
async def options(app: str, request: Request, host: str = "local"):
    known_app(app)
    return result(
        await target(request, host).request("GET", f"/v1/container-apps/{app}/install-options")
    )


@router.post("/install-plan")
async def plan(body: ContainerInstallation, request: Request):
    return result(
        await target(request, body.hostId).request(
            "POST", "/v1/container-apps/install-plan", body.model_dump()
        )
    )


@router.post("/install", status_code=202)
async def install(body: ContainerInstallRequest, request: Request):
    svc, spec = services(request), body.installation
    with svc.sessions() as db:
        existing = db.scalar(
            select(Setting).where(Setting.key == "container_installation_" + spec.app)
        )
        if existing and existing.value["hostId"] != spec.hostId:
            raise DomainError(
                "installation_exists", "Remove the existing installation before changing host", 409
            )
    response = await target(request, spec.hostId).request(
        "POST", "/v1/container-apps/install", body.model_dump()
    )
    package = "org.mediahub." + spec.app
    with svc.sessions.begin() as db:
        binding_key = "container_installation_" + spec.app
        values = {**spec.model_dump(), "installationId": "mediahub-" + spec.app}
        binding = db.scalar(select(Setting).where(Setting.key == binding_key))
        if binding is None:
            db.add(Setting(key=binding_key, value=values))
        else:
            binding.value = values
        installed = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
        if installed is None:
            db.add(
                InstalledApp(
                    package_id=package,
                    name=CONTAINER_APPS[spec.app]["name"],
                    version="0.1.0",
                    state="starting",
                    is_mock=False,
                )
            )
        else:
            installed.state, installed.is_mock = "starting", False
    register_remote_apps(svc)
    svc.events.record(
        "app.install_requested", package, "Container installation accepted; verification pending"
    )
    return result(response)


@router.get("/{app}/status")
async def status(app: str, request: Request):
    known_app(app)
    svc = services(request)
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "container_installation_" + app))
        if binding is None:
            raise DomainError("not_installed", "Install this app first", 409)
        host = binding.value["hostId"]
        installation = dict(binding.value)
    report = await target(request, host).request("GET", f"/v1/container-apps/{app}/status")
    return result({**report, "installation": installation})
