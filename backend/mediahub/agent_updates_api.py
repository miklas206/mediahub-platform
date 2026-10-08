import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from mediahub.agent_updates import SSHSetup
from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError

router = APIRouter(prefix="/updates/seedbox-agent", dependencies=[Depends(administrator)])


class Port(StrictModel):
    port: int = Field(default=22, ge=1, le=65535)


class SavedTrust(Port):
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")


@router.get("/generated-access")
def generated_access(request: Request):
    return result(services(request).agent_updates.generated_access())


@router.post("/generated-access")
def create_generated_access(request: Request):
    if request.url.scheme != "https":
        raise DomainError("tls_required", "Use HTTPS before entering SSH credentials", 403)
    return result(services(request).agent_updates.generated_access(create=True))


@router.post("/prepare-generated")
async def prepare_generated(body: SavedTrust, request: Request):
    if request.url.scheme != "https":
        raise DomainError("tls_required", "Use HTTPS before entering SSH credentials", 403)
    return result(
        await asyncio.to_thread(
            services(request).agent_updates.prepare_generated,
            body.fingerprint,
            body.port,
        )
    )


@router.get("")
async def check(request: Request):
    svc = services(request)
    checked = await svc.agent_updates.check()
    await svc.updates.record_app(
        {"id": "seedbox-agent", "name": "Seedbox Agent"},
        {**checked, "latestVersion": checked.get("latestCommit")},
    )
    return result(checked)


@router.post("/fingerprint")
async def fingerprint(body: Port, request: Request):
    return result(await asyncio.to_thread(services(request).agent_updates.fingerprint, body.port))


@router.post("/prepare")
async def prepare(body: SSHSetup, request: Request):
    if request.url.scheme != "https":
        raise DomainError("tls_required", "Use HTTPS before entering SSH credentials", 403)
    return result(await asyncio.to_thread(services(request).agent_updates.prepare, body))


@router.post("/install", status_code=202)
async def install(request: Request):
    return result(await services(request).agent_updates.start())


@router.get("/operation")
def operation(request: Request):
    return result(services(request).agent_updates.operation())


@router.delete("/credentials")
def forget_credentials(request: Request):
    return result(services(request).agent_updates.forget_setup())


@router.post("/prepare-saved")
async def prepare_saved(request: Request, body: SavedTrust | None = None):
    if body is not None and request.url.scheme != "https":
        raise DomainError("tls_required", "Use HTTPS before entering SSH credentials", 403)
    return result(
        await asyncio.to_thread(
            services(request).agent_updates.prepare_saved,
            **({"fingerprint": body.fingerprint, "port": body.port} if body else {}),
        )
    )
