from fastapi import APIRouter, Depends, Request

from mediahub.api import administrator, result, services
from mediahub.fjordhub_deploy import DeployRequest, SSHAddress, probe

router = APIRouter(prefix="/fjordhub/deployment", dependencies=[Depends(administrator)])


@router.get("")
def status(request: Request):
    return result(services(request).fjordhub_deploy.latest())


@router.post("/fingerprint")
def host_fingerprint(body: SSHAddress):
    return result(probe(body))


@router.post("")
def start(body: DeployRequest, request: Request):
    return result(services(request).fjordhub_deploy.start(body))
