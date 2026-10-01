from typing import Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import DeployRequest, SSHAddress, probe
from mediahub.fjordhub_inspect import InspectDeployment, inspect_deployment

router = APIRouter(prefix="/fjordhub/deployment", dependencies=[Depends(administrator)])


@router.get("/target")
async def suggested_target(request: Request, target: Literal["lxc", "linux"] = "lxc"):
    svc = services(request)
    # Reuse only completed deployments of the requested type, never a failed guess.
    with svc.sessions() as db:
        jobs = db.scalars(
            select(Setting)
            .where(Setting.key.startswith("fjordhub.deployment."))
            .order_by(Setting.created_at.desc())
        )
        for row in jobs:
            job = row.value
            if job.get("state") == "succeeded" and job.get("config", {}).get("target") == target:
                try:
                    host = SSHAddress(host=job.get("host", "")).host
                except ValueError:
                    continue
                return result({"host": host, "source": "previous-installation"})
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        host_id = binding.value.get("hostId") if binding else None
    if target == "lxc" and host_id:
        try:
            report = await svc.hosts.client(host_id).request("GET", "/v1/seedbox/status")
            source = report.get("storage", {}).get("source", "")
            address, separator, export = source.partition(":/")
            if separator and export:
                host = SSHAddress(host=address).host
                # A storage server is a candidate, not proof of a Proxmox node.
                # The installer still checks Proxmox after pinned SSH login.
                return result({"host": host, "source": "configured-storage"})
        except (DomainError, ValueError, TypeError, AttributeError):
            pass
    return result({"host": None, "source": None})


@router.get("")
def status(request: Request):
    return result(services(request).fjordhub_deploy.latest())


@router.post("/fingerprint")
def host_fingerprint(body: SSHAddress):
    return result(probe(body))


@router.post("")
def start(body: DeployRequest, request: Request):
    return result(services(request).fjordhub_deploy.start(body))


@router.post("/inspect")
def inspect_existing(body: InspectDeployment, request: Request):
    return result(inspect_deployment(services(request).fjordhub_deploy, body))
