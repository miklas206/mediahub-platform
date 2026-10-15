"""Administrator orchestration for one provider connection and paired app relays."""

import asyncio
import hashlib

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.db import Host, InstalledApp, Setting
from mediahub.errors import DomainError

router = APIRouter(prefix="/shared-vpn", dependencies=[Depends(administrator)])


class GatewayChoice(StrictModel):
    enabled: bool
    profileId: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


class AppChoice(StrictModel):
    enabled: bool
    profileId: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")


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
                installed = db.scalar(
                    select(InstalledApp).where(
                        InstalledApp.package_id == "org.mediahub." + app,
                        InstalledApp.is_mock.is_(False),
                        InstalledApp.state.not_in(
                            {"uninstalled", "removing", "installing", "failed"}
                        ),
                    )
                )
                if row and installed:
                    choices.append(
                        {
                            "id": app,
                            "name": "Plex" if app == "plex" else "Jellyfin",
                            "hostId": row.value["hostId"],
                        }
                    )
        return choices

    def assignment(self, identifier, profile=None, write=False, pending=False):
        key = "vpn_profile_" + identifier
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == key))
            if write:
                if row:
                    row.value = {"profileId": profile, "pending": pending}
                else:
                    db.add(Setting(key=key, value={"profileId": profile, "pending": pending}))
                db.commit()
            return row.value.get("profileId") if row else profile

    def assignment_pending(self, identifier):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == "vpn_profile_" + identifier))
            return bool(row and row.value.get("pending"))

    @staticmethod
    def peer_id(binding):
        return hashlib.sha256((binding["hostId"] + ":" + binding["id"]).encode()).hexdigest()[:40]

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

    def orphan_bindings(self, gateway):
        peers = {peer.get("id") for peer in gateway.get("peers", [])}
        orphans = []
        with self.svc.sessions() as db:
            hosts = list(db.scalars(select(Host)))
            for app, key in (
                ("plex", "plex_installation"),
                ("jellyfin", "container_installation_jellyfin"),
            ):
                installed = db.scalar(
                    select(InstalledApp).where(InstalledApp.package_id == "org.mediahub." + app)
                )
                binding = db.scalar(select(Setting).where(Setting.key == key))
                if (
                    not installed
                    or installed.state != "uninstalled"
                    or installed.is_mock
                    or binding
                ):
                    continue
                for host in hosts:
                    identifier = hashlib.sha256((host.id + ":" + app).encode()).hexdigest()[:40]
                    if identifier in peers:
                        orphans.append(
                            {
                                "id": identifier,
                                "app": app,
                                "name": "Plex" if app == "plex" else "Jellyfin",
                                "hostId": host.id,
                            }
                        )
        return orphans

    async def forget_peer(self, package, host):
        if package not in {"org.mediahub.plex", "org.mediahub.jellyfin"}:
            return
        policy = self.svc.managed_apps.policy.get("org.mediahub.mediavpn")
        if not policy or not policy.managementTokenFile:
            return
        identifier = hashlib.sha256((host + ":" + package.rsplit(".", 1)[-1]).encode()).hexdigest()[
            :40
        ]
        profile = self.assignment(identifier)
        gateway = await self.vpn(path="/profiles/" + profile if profile else "")
        if any(peer.get("id") == identifier for peer in gateway.get("peers", [])):
            await self.vpn("DELETE", ("/profiles/" + profile if profile else "") + "/peers/" + identifier)
        if profile:
            await self.vpn("DELETE", "/app-peers/" + identifier)
        self.assignment(identifier, None, write=True)

    async def cleanup_orphan(self, identifier):
        async with self.lock:
            orphan = next(
                (
                    item
                    for item in self.orphan_bindings(await self.vpn())
                    if item["id"] == identifier
                ),
                None,
            )
            if not orphan:
                raise DomainError(
                    "installation_changed",
                    "Connection is no longer an orphan; refresh and review again",
                    409,
                )
            client = self.svc.hosts.client(orphan["hostId"])
            if not client.trusted_transport:
                raise DomainError(
                    "agent_tls_required", "Shared VPN requires a trusted HTTPS Agent", 409
                )
            endpoint = "/v1/shared-vpn/" + orphan["app"] + "/cleanup"
            preview = await client.request("GET", endpoint)
            result = await client.request(
                "POST", endpoint, {"confirmedInstallationId": preview["installationId"]}
            )
            if result.get("state") != "succeeded" or result.get("dataPreserved") is not True:
                raise DomainError(
                    "removal_unverified", "Runtime removal has not passed its final checks", 409
                )
            await self.forget_peer("org.mediahub." + orphan["app"], orphan["hostId"])
            self.svc.events.record(
                "vpn.orphan_removed",
                orphan["app"],
                "Removed obsolete app VPN connection; data preserved",
            )
            return {"state": "succeeded", "dataPreserved": True}

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
                    "profileId": seed.get("profileId"),
                    "ready": seed.get("ready", False),
                    "phase": seed.get("phase") or ("ready" if seed.get("ready") else "idle"),
                }
            )
        profile_requests = {}
        async def app_status(item):
            try:
                _, client = self.target(item["id"])
                state = await client.request("GET", "/v1/shared-vpn/" + item["id"])
                profile = self.assignment(self.peer_id(item)) or gateway.get("profileId")
                pending = self.assignment_pending(self.peer_id(item))
                if profile and profile != gateway.get("profileId"):
                    if profile not in profile_requests:
                        profile_requests[profile] = asyncio.create_task(self.vpn(path="/profiles/" + profile))
                    app_gateway = await profile_requests[profile]
                else:
                    app_gateway = gateway
                return {
                    **item,
                    "enabled": state["enabled"],
                    "pending": pending,
                    "profileId": profile if state["enabled"] or pending else None,
                    "ready": bool(
                        not pending and app_gateway["ready"]
                        and state.get(
                            "ready", state["handshakeVerified"] and state["phase"] == "ready"
                        )
                    ),
                    "phase": state["phase"],
                    "errorCode": state.get("errorCode"),
                    "message": state.get("message"),
                }
            except DomainError:
                return {**item, "enabled": None, "ready": False, "phase": "unavailable"}
        apps.extend(await asyncio.gather(*(app_status(item) for item in self.bindings())))
        return {"gateway": gateway, "apps": apps, "orphans": self.orphan_bindings(gateway)}

    def seed_installed(self):
        with self.svc.sessions() as db:
            app = db.scalar(
                select(InstalledApp).where(InstalledApp.package_id == "org.mediahub.mediaseed")
            )
            return bool(
                app
                and not app.is_mock
                and app.state not in {"uninstalled", "removing", "installing", "failed"}
            )

    async def assign(self, app, enabled, profile_id=None):
        async with self.lock:
            if app == "mediaseed":
                if not self.seed_installed():
                    raise DomainError(
                        "vpn_app_unavailable", "Install MediaSeed before selecting its VPN", 409
                    )
                if profile_id is None:
                    gateway = await self.vpn()
                    profile_id = gateway["profileId"]
                elif not enabled:
                    actual = await self.vpn(path="/status", shared=False)
                    if actual.get("enabled") and actual.get("profileId") != profile_id:
                        raise DomainError("vpn_assignment_changed", "The app changed VPN profile; refresh before removing its assignment", 409)
                await self.vpn(
                    "PUT",
                    "/settings",
                    {"enabled": enabled, "profileId": profile_id},
                    shared=False,
                )
                return await self.public()
            binding, client = self.target(app)
            current = await client.request("GET", "/v1/shared-vpn/" + app)
            peer = None
            identifier = hashlib.sha256((binding["hostId"] + ":" + app).encode()).hexdigest()[:40]
            previous = self.assignment(identifier)
            previous_profile = previous or (await self.vpn()).get("profileId")
            if not enabled and profile_id and current.get("enabled") and previous_profile != profile_id:
                raise DomainError("vpn_assignment_changed", "The app changed VPN profile; refresh before removing its assignment", 409)
            previous_path = "/profiles/" + previous if previous else ""
            target_path = "/profiles/" + profile_id if profile_id else ""
            if enabled:
                gateway = await self.vpn("PUT", target_path) if profile_id else await self.vpn()
                if not profile_id and not gateway["ready"]:
                    raise DomainError(
                        "vpn_not_ready", "Wait for the shared VPN gateway to be verified first", 409
                    )
                peer = await self.vpn(
                    "POST",
                    target_path + "/peers",
                    {"id": identifier, "name": binding["name"], "publicKey": current["publicKey"]},
                )
                peer = {
                    key: peer[key]
                    for key in ("address", "endpointIp", "endpointPort", "gatewayKey")
                }
                # Persist routing intent before the Agent call: a timeout can occur
                # after the Agent has accepted it. Its phase reports actual readiness.
                self.assignment(identifier, profile_id or gateway["profileId"], write=True, pending=True)
            await client.request("PUT", "/v1/shared-vpn/" + app, {"enabled": enabled, "peer": peer})
            if enabled:
                self.assignment(identifier, profile_id or gateway["profileId"], write=True)
            if not enabled or previous_profile != (profile_id or gateway["profileId"]):
                await self.vpn("DELETE", previous_path + "/peers/" + identifier)
            if not enabled:
                if previous:
                    await self.vpn("DELETE", "/app-peers/" + identifier)
                self.assignment(identifier, None, write=True)
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
    return result(await secure(request).assign(app, body.enabled, body.profileId))


@router.post("/orphans/{identifier}/cleanup")
async def cleanup_orphan(identifier: str, request: Request):
    return result(await secure(request).cleanup_orphan(identifier))
