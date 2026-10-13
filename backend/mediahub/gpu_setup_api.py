from fastapi import APIRouter, Depends, Request
from pydantic import Field

from mediahub.api import administrator, result, services
from mediahub.container_apps_api import target
from mediahub.contracts import StrictModel

router = APIRouter(prefix="/gpu-setup", dependencies=[Depends(administrator)])


class GPUTest(StrictModel):
    hostId: str = Field(default="local", min_length=1, max_length=80)
    gpuId: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,80}$")


@router.get("")
async def status(request: Request, host: str = "local"):
    return result(await target(request, host).request("GET", "/v1/gpu-setup"))


@router.post("/test", status_code=202)
async def test(body: GPUTest, request: Request):
    svc = services(request)
    svc.setup.require_complete()
    response = await target(request, body.hostId).request(
        "POST", "/v1/gpu-setup/test", {"gpuId": body.gpuId}
    )
    svc.events.record("gpu.test_requested", body.hostId, "Synthetic GPU transcoding test requested")
    return result(response)
