"""Authenticated HTTPS-only forwarding. Core never persists credential import bodies."""

import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import ConfigDict, Field, SecretStr
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.apps.seedbox_wizard import (
    ClientImport,
    VPNImport,
    WizardAdvance,
    WizardConfiguration,
    WizardExecute,
)
from mediahub.contracts import StrictModel
from mediahub.db import Host, HostStorage, InstalledApp, Setting
from mediahub.errors import DomainError

router = APIRouter(prefix="/seedbox/wizard", dependencies=[Depends(administrator)])


class TargetSelection(StrictModel):
    hostId: str = Field(min_length=1, max_length=80)


@router.get("/targets")
async def targets(request: Request):
    svc = services(request)
    with svc.sessions() as db:
        selected = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        hosts = [
            {"id": h.id, "name": h.name}
            for h in db.scalars(select(Host).where(Host.local.is_(False)))
            if h.encrypted_token
        ]
    return result({"bound": selected is not None, "hosts": hosts})


@router.post("/target")
async def choose_target(body: TargetSelection, request: Request):
    svc = services(request)
    if request.url.scheme != "https" or body.hostId == "local":
        raise DomainError("seedbox_target_denied", "Choose a separately paired HTTPS host", 403)
    with svc.sessions() as db:
        if db.scalar(select(Setting).where(Setting.key == "seedbox_installation")):
            raise DomainError(
                "seedbox_already_bound", "Existing Seedbox delegation cannot be replaced here", 409
            )
    client = svc.hosts.client(body.hostId)
    if urlsplit(client.config.agent_url).scheme != "https":
        raise DomainError("agent_tls_required", "Verified HTTPS Agent required", 403)
    wizard = await client.request("GET", "/v1/seedbox/wizard")
    installation = wizard["installation"]
    if installation["hostId"] != body.hostId:
        raise DomainError("host_mismatch", "Agent policy belongs to another host", 409)
    with svc.sessions.begin() as db:
        mapping = db.scalar(
            select(HostStorage).where(
                HostStorage.host_id == body.hostId,
                HostStorage.logical_id == installation["downloadsStorageId"],
            )
        )
        if not mapping or mapping.access != "rw":
            raise DomainError(
                "storage_required", "Register the approved Downloads read/write mapping first", 409
            )
        if db.scalar(select(Setting).where(Setting.key == "seedbox_installation")):
            raise DomainError("seedbox_already_bound", "Seedbox is already delegated", 409)
        db.add(Setting(key="seedbox_installation", value=installation))
    svc.events.record(
        "seedbox.delegated", "seedbox", "Dedicated host selected for guided installation"
    )
    return result({"bound": True})


def target(request):
    svc = services(request)
    if request.url.scheme != "https":
        raise DomainError(
            "https_required", "Use HTTPS for installation and private configuration", 403
        )
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        if binding is None:
            raise DomainError(
                "host_required",
                "Delegate a dedicated Agent and logical downloads storage first",
                409,
            )
        host = binding.value["hostId"]
    if svc.config.seedbox_requires_remote_host and host == "local":
        raise DomainError("seedbox_target_denied", "Seedbox requires its separate host", 403)
    client = svc.hosts.client(host)
    if urlsplit(client.config.agent_url).scheme != "https":
        raise DomainError(
            "agent_tls_required", "Pair the Agent with valid internal HTTPS first", 409
        )
    return client


async def forward(request, path="", payload=None, method="POST"):
    return result(await target(request).request(method, "/v1/seedbox/wizard" + path, payload))


@router.get("")
async def status(request: Request):
    return await forward(request, method="GET")


@router.get("/review")
async def review(request: Request):
    return await forward(request, "/review", method="GET")


@router.post("/configure")
async def configure(body: WizardConfiguration, request: Request):
    return await forward(request, "/configure", body.model_dump())


@router.post("/advance")
async def advance(body: WizardAdvance, request: Request):
    return await forward(request, "/advance", body.model_dump())


@router.post("/vpn")
async def vpn(body: VPNImport, request: Request):
    return await forward(
        request, "/vpn", {"revision": body.revision, "vpnConfig": body.vpnConfig.get_secret_value()}
    )


class MediaHubClientImport(StrictModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    revision: int = Field(ge=0)
    operation: Literal["install", "rotate"]
    password: SecretStr = Field(exclude=True, min_length=1, max_length=256)
    secondFactor: SecretStr = Field(
        default_factory=lambda: SecretStr(""), exclude=True, max_length=32
    )


@router.post("/client/mediahub", status_code=202)
async def mediahub_client(
    body: MediaHubClientImport, request: Request, user=Depends(administrator)
):
    # Resolve the verified HTTPS target before consuming a recovery code.
    agent = target(request)
    svc = services(request)
    password = body.password.get_secret_value()
    with svc.sessions.begin() as db:
        account = svc.auth.reauthenticate(
            db, user["id"], password, body.secondFactor.get_secret_value()
        )
        if account.role != "administrator":
            raise DomainError("administrator_required", "Administrator access is required", 403)
        username = account.username
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username) or not (
        16 <= len(password) <= 256 and all(ord(char) >= 32 for char in password)
    ):
        raise DomainError(
            "seedbox_login_incompatible",
            "Your MediaHub login is incompatible: qBittorrent requires a username of "
            "1–64 letters, digits, dots, underscores or hyphens and a 16–256 character "
            "password without control characters. Use separate credentials instead.",
            422,
        )
    path = "/rotate/client" if body.operation == "rotate" else "/client"
    return result(
        await agent.request(
            "POST",
            "/v1/seedbox/wizard" + path,
            {"revision": body.revision, "webUsername": username, "webPassword": password},
        )
    )


@router.post("/client")
async def client(body: ClientImport, request: Request):
    return await forward(
        request,
        "/client",
        {
            "revision": body.revision,
            "webUsername": body.webUsername,
            "webPassword": body.webPassword.get_secret_value(),
        },
    )


@router.post("/preflight", status_code=202)
async def preflight(body: WizardExecute, request: Request):
    return await forward(request, "/preflight", body.model_dump())


@router.post("/install", status_code=202)
async def install(body: WizardExecute, request: Request):
    response = await forward(request, "/install", body.model_dump())
    register_installation(request)
    return response


@router.post("/adopt", status_code=202)
async def adopt(request: Request):
    response = await forward(request, "/adopt")
    register_installation(request)
    return response


def register_installation(request):
    from mediahub.apps.remote_registry import register_remote_apps

    svc = services(request)
    with svc.sessions.begin() as db:
        if not db.scalar(
            select(InstalledApp).where(InstalledApp.package_id == "org.mediahub.seedbox")
        ):
            db.add(
                InstalledApp(
                    package_id="org.mediahub.seedbox",
                    name="Seedbox",
                    version="unknown",
                    state="starting",
                    is_mock=False,
                )
            )
    register_remote_apps(svc)


@router.post("/rotate/client", status_code=202)
async def rotate_client(body: ClientImport, request: Request):
    return await forward(
        request,
        "/rotate/client",
        {
            "revision": body.revision,
            "webUsername": body.webUsername,
            "webPassword": body.webPassword.get_secret_value(),
        },
    )


@router.post("/rotate/vpn", status_code=202)
async def rotate_vpn(body: VPNImport, request: Request):
    return await forward(
        request,
        "/rotate/vpn",
        {"revision": body.revision, "vpnConfig": body.vpnConfig.get_secret_value()},
    )


@router.post("/rollback", status_code=202)
async def rollback(request: Request):
    return await forward(request, "/rollback")
