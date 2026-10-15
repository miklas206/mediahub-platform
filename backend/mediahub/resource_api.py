from fastapi import APIRouter, Depends, Request
from pydantic import Field, StrictBool

from agent.resource_control import ResourceChange
from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel

router = APIRouter()


class ResourcePreference(StrictModel):
    enabled: StrictBool


class ResourceApproval(ResourceChange):
    recommendationId: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/resources")
async def resource_overview(request: Request, user=Depends(administrator)):
    return result(services(request).resources.summary())


@router.get("/resources/{app_id}")
async def resource_details(app_id: str, request: Request, user=Depends(administrator)):
    svc = services(request)
    return result(svc.resources.row(svc.apps.get(app_id)))


@router.put("/resources/{app_id}")
async def resource_limits(
    app_id: str, body: ResourceChange, request: Request, user=Depends(administrator)
):
    svc = services(request)
    return result(await svc.resources.change(svc.apps.get(app_id), body))


@router.post("/resources/{app_id}/approve")
async def resource_approve(
    app_id: str, body: ResourceApproval, request: Request, user=Depends(administrator)
):
    svc = services(request)
    change = ResourceChange(**body.model_dump(exclude={"recommendationId"}))
    return result(await svc.resources.change(svc.apps.get(app_id), change, body.recommendationId))


@router.put("/resources/{app_id}/recommendations")
async def resource_preference(
    app_id: str, body: ResourcePreference, request: Request, user=Depends(administrator)
):
    svc = services(request)
    return result(svc.resources.preference(svc.apps.get(app_id), body.enabled))
