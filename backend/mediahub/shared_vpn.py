"""Administrator orchestration for one provider connection and paired app relays."""

import asyncio
import hashlib

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError

router = APIRouter(prefix="/shared-vpn", dependencies=[Depends(administrator)])


class GatewayChoice(StrictModel):
    enabled: bool
    profileId: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


class AppChoice(StrictModel):
    enabled: bool


class SharedVPN:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()

    async def vpn(self, method="GET", path="", body=None, shared=True):
        policy = self.svc.managed_apps.policy.get("org.mediahub.mediaseed")
        if not policy or not policy.integrationUrl or not policy.integrationTokenFile:
            raise DomainError("vpn_integration_required", "Install and connect MediaVPN first", 409)
        try:
            management = self.svc.managed_apps.policy.get("org.mediahub.mediavpn")
            key_path = (
                management.managementTokenFile
                if shared and management
                else policy.integrationTokenFile
            )
            if shared and (not management or not management.managementTokenFile):
                raise DomainError(
                    "vpn_upgrade_required",
                    "Wait for MediaVPN prerequisites to finish updating",
                    409,
                )
            token = key_path.read_text().strip()
            async with httpx.AsyncClient(
                timeout=45, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    policy.integrationUrl
                    + "/api/integration"
                    + ("/shared" if shared else "")
                    + path,
                    headers={"X-MediaHub-Key" if shared else "X-MediaSeed-Key": token},
                    json=body,
                )
            if not response.is_success:
                # Never relay raw third-party responses or request headers containing keys.
                raise DomainError(
                    "vpn_not_ready",
                    "MediaVPN could not apply the shared VPN choice; check its profile and runtime",
                    409,
                )
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, httpx.HTTPError, ValueError):
            raise DomainError(
                "vpn_unavailable", "Update MediaVPN and check its private integration address", 503
            ) from None

    def bindings(self):
        choices = []
        with self.svc.sessions() as db:
            for app, key in (
                ("plex", "plex_installation"),
                ("jellyfin", "container_installation_jellyfin"),
            ):
                row = db.scalar(select(Setting).where(Setting.key == key))
                installed = db.scalar(select(InstalledApp).where(
                    InstalledApp.package_id == "org.mediahub." + app,
                    InstalledApp.is_mock.is_(False),
                    InstalledApp.state.not_in({"uninstalled", "removing", "installing", "failed"}),
                ))
                if row and installed:
                    choices.append(
                        {
                            "id": app,
                            "name": "Plex" if app == "plex" else "Jellyfin",
                            "hostId": row.value["hostId"],
                        }
                    )
        return choices

    def target(self, app):
        binding = next((item for item in self.bindings() if item["id"] == app), None)
        if not binding:
            raise DomainError(
                "vpn_app_unavailable", "Install the app on a paired MediaHub host first", 409
            )
        client = self.svc.hosts.client(binding["hostId"])
        if not client.trusted_transport:
            raise DomainError(
                "agent_tls_required", "Shared VPN requires a trusted HTTPS Agent", 409
            )
        return binding, client

    async def public(self):
        gateway = await self.vpn()
        apps = []
        if self.seed_installed():
            try:
                seed = await self.vpn(path="/status", shared=False)
            except DomainError:
                seed = {"enabled": None, "ready": False, "phase": "unavailable"}
            apps.append(
                {
                    "id": "mediaseed",
                    "name": "MediaSeed",
                    "hostId": "local",
                    "enabled": seed.get("enabled", False),
                    "ready": seed.get("ready", False),
                    "phase": seed.get("phase") or ("ready" if seed.get("ready") else "idle"),
                }
            )
        for item in self.bindings():
            try:
                _, client = self.target(item["id"])
                state = await client.request("GET", "/v1/shared-vpn/" + item["id"])
                apps.append(
                    {
                        **item,
                        "enabled": state["enabled"],
                        "ready": bool(gateway["ready"] and state["handshakeVerified"]),
                        "phase": state["phase"],
                    }
                )
            except DomainError:
                apps.append({**item, "enabled": None, "ready": False, "phase": "unavailable"})
        return {"gateway": gateway, "apps": apps}

    def seed_installed(self):
        with self.svc.sessions() as db:
            app = db.scalar(
                select(InstalledApp).where(InstalledApp.package_id == "org.mediahub.mediaseed")
            )
            return bool(app and not app.is_mock and app.state not in {"uninstalled", "removing", "installing", "failed"})

    async def assign(self, app, enabled):
        async with self.lock:
            if app == "mediaseed":
                if not self.seed_installed():
                    raise DomainError(
                        "vpn_app_unavailable", "Install MediaSeed before selecting its VPN", 409
                    )
                gateway = await self.vpn()
                await self.vpn(
                    "PUT",
                    "/settings",
                    {"enabled": enabled, "profileId": gateway["profileId"]},
                    shared=False,
                )
                return await self.public()
            binding, client = self.target(app)
            current = await client.request("GET", "/v1/shared-vpn/" + app)
            peer = None
            identifier = hashlib.sha256((binding["hostId"] + ":" + app).encode()).hexdigest()[:40]
            if enabled:
                gateway = await self.vpn()
                if not gateway["ready"]:
                    raise DomainError(
                        "vpn_not_ready", "Wait for the shared VPN gateway to be verified first", 409
                    )
                peer = await self.vpn(
                    "POST",
                    "/peers",
                    {"id": identifier, "name": binding["name"], "publicKey": current["publicKey"]},
                )
                peer = {
                    key: peer[key]
                    for key in ("address", "endpointIp", "endpointPort", "gatewayKey")
                }
            await client.request("PUT", "/v1/shared-vpn/" + app, {"enabled": enabled, "peer": peer})
            if not enabled:
                await self.vpn("DELETE", "/peers/" + identifier)
            self.svc.events.record(
                "vpn.app_changed", app, "Shared VPN application selection updated"
            )
            return await self.public()


def secure(request):
    if request.url.scheme != "https" and not services(request).config.dev_mode:
        raise DomainError("https_required", "Use HTTPS to manage shared VPN", 403)
    return services(request).shared_vpn


@router.get("")
async def status(request: Request):
    return result(await secure(request).public())


@router.put("/gateway")
async def gateway(body: GatewayChoice, request: Request):
    service = secure(request)
    async with service.lock:
        if body.enabled:
            for binding in service.bindings():
                if binding["id"] == "plex":
                    _, client = service.target("plex")
                    status = await client.request("GET", "/v1/plex/status")
                    if status.get("vpn"):
                        raise DomainError(
                            "vpn_conflict",
                            "Disable the old dedicated Plex VPN before enabling shared VPN",
                            409,
                        )
        await service.vpn("PUT", body=body.model_dump())
        return result(await service.public())


@router.put("/apps/{app}")
async def application(app: str, body: AppChoice, request: Request):
    return result(await secure(request).assign(app, body.enabled))
