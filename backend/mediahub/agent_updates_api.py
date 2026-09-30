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
