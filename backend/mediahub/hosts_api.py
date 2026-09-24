from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from mediahub.api import authenticated, result, services
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError

router = APIRouter()


class Invitation(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(max_length=300)


class Pair(StrictModel):
    token: str = Field(min_length=40, max_length=200)
    address: str = Field(max_length=300)
    agent_token: str = Field(min_length=40, max_length=200)


class LogicalInput(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["appdata", "downloads", "movies", "tv", "backups", "temp", "custom"]
    dataset_ref: str = Field(min_length=1, max_length=200)


class ResolveInput(StrictModel):
    host_id: str = Field(max_length=80)
    access: Literal["ro", "rw"] = "ro"


class MappingInput(ResolveInput):
    path: str = Field(min_length=1, max_length=4096)


@router.get("/hosts")
async def hosts(request: Request, user=Depends(authenticated)):
    return result(services(request).hosts.list())


@router.post("/hosts/refresh")
async def refresh(request: Request, user=Depends(authenticated)):
    await services(request).hosts.refresh()
    return result(services(request).hosts.list())


@router.post("/hosts/pairing")
async def invite(body: Invitation, request: Request, user=Depends(authenticated)):
    if request.url.scheme != "https":
        raise DomainError(
            "tls_required",
            "Pairing requires HTTPS; local HTTP deployment cannot enroll remote agents",
            403,
        )
    return result(services(request).hosts.invitation(body.name, body.address))


@router.post("/hosts/pair")
async def pair(body: Pair, request: Request):
    if request.url.scheme != "https":
        raise DomainError("tls_required", "Pairing requires HTTPS", 403)
    return result(await services(request).hosts.pair(body.token, body.address, body.agent_token))


@router.get("/storage/logical")
async def logical(request: Request, user=Depends(authenticated)):
    return result(services(request).hosts.storage())


@router.post("/storage/logical")
async def add_logical(body: LogicalInput, request: Request, user=Depends(authenticated)):
    return result(services(request).hosts.add_storage(**body.model_dump()))


@router.put("/storage/logical/{logical_id}/mapping")
async def mapping(
    logical_id: str, body: MappingInput, request: Request, user=Depends(authenticated)
):
    return result(services(request).hosts.map_storage(logical_id, **body.model_dump()))


@router.post("/storage/logical/{logical_id}/validate")
async def validate(
    logical_id: str, body: ResolveInput, request: Request, user=Depends(authenticated)
):
    return result(await services(request).hosts.resolve(logical_id, body.host_id, body.access))
