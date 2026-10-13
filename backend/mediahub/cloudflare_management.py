"""Opt-in Cloudflare API management and app-bound origin reconciliation."""

import asyncio
import copy
import re
import time
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field, SecretStr
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

KEY = "cloudflare-management"
API = "https://api.cloudflare.com/client/v4"
APPS = {
    "mediahub": "MediaHub",
    "org.mediahub.mediaseed": "MediaSeed",
    "org.mediahub.mediavpn": "MediaVPN",
    "org.mediahub.plex": "Plex",
    "org.mediahub.jellyfin": "Jellyfin",
}


def secure_administrator(request: Request, user=Depends(administrator)):
    if request.url.scheme != "https" and not services(request).config.dev_mode:
        raise DomainError(
            "https_required", "Use HTTPS to manage Cloudflare credentials and routes", 400
        )
    return user


router = APIRouter(prefix="/cloudflare/manage", dependencies=[Depends(secure_administrator)])


def hostname(value):
    try:
        name = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise DomainError("invalid_hostname", "Use a valid public hostname", 422) from None
    if (
        len(name) > 253
        or "." not in name
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
            for part in name.split(".")
        )
    ):
        raise DomainError("invalid_hostname", "Use a valid public hostname", 422)
    return name


class Credentials(StrictModel):
    accountId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    token: SecretStr = Field(min_length=20, max_length=512)


class NewTunnel(StrictModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$")


class RouteInput(StrictModel):
    tunnelId: UUID
    zoneId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    hostname: str = Field(min_length=3, max_length=253)
    packageId: str = Field(max_length=120)
    autoSync: bool = True
    caPool: str = Field(
        default="/etc/cloudflared/mediahub-ca.pem", max_length=300, pattern=r"^/[A-Za-z0-9_/.-]+$"
    )


class RouteMode(StrictModel):
    autoSync: bool


class DNSRecord(StrictModel):
    zoneId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    hostname: str = Field(min_length=3, max_length=253)
    type: Literal["A", "AAAA", "CNAME"]
    content: str = Field(min_length=1, max_length=253)
    proxied: bool = False


class ConfiguredHostMiddleware(TrustedHostMiddleware):
    """Keep exact approved hosts current when an administrator publishes the hub."""

    def __init__(self, app, config):
        self.config = config
        super().__init__(
            app, allowed_hosts=sorted({urlsplit(origin).hostname for origin in config.origins})
        )

    async def __call__(self, scope, receive, send):
        self.allowed_hosts = sorted({urlsplit(origin).hostname for origin in self.config.origins})
        await super().__call__(scope, receive, send)


class CloudflareManagement:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()
        self.store = SecretStore((svc.config.data_dir / "cloudflare-secrets").resolve())
        self.retry_at = 0.0
        self.monitor_routes(self.state())
        for route in self.state()["routes"]:
            if route["packageId"] == "mediahub" and route.get("lastApplied"):
                self.allow_hub_origin(route["hostname"])

    def monitor_routes(self, state):
        monitor = self.svc.cloudflare_tunnel
        urls = ["https://" + row["hostname"] for row in state["routes"] if row.get("lastApplied")]
        if any(url not in monitor.probe_urls for url in urls):
            monitor.probe_urls = list(dict.fromkeys([*monitor.probe_urls, *urls]))
            monitor.cached = None

    def allow_hub_origin(self, name):
        origin = "https://" + hostname(name)
        if origin not in self.svc.config.allowed_origins:
            self.svc.config.allowed_origins.append(origin)

    def state(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            return (
                copy.deepcopy(row.value) if row else {"accountId": "", "tunnels": [], "routes": []}
            )

    def save(self, value):
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                row.value = copy.deepcopy(value)
            else:
                db.add(Setting(key=KEY, value=copy.deepcopy(value)))

    def configured(self):
        return self.store.status("api_token")["configured"]

    async def call(self, method, path, body=None, params=None, token=None):
        if time.monotonic() < self.retry_at:
            raise DomainError(
                "cloudflare_backoff",
                "Cloudflare request limit reached; waiting before retrying",
                429,
            )
        if token is None:
            if not self.configured():
                raise DomainError(
                    "cloudflare_credentials", "Connect your Cloudflare account first", 409
                )
            token = self.store.get("api_token").decode()
        try:
            async with httpx.AsyncClient(
                timeout=20, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    API + path,
                    params=params,
                    json=body,
                    headers={"Authorization": "Bearer " + token},
                )
            if response.status_code == 429:
                raw = response.headers.get("Retry-After", "60")
                self.retry_at = time.monotonic() + min(
                    3600, max(60, int(raw) if raw.isdigit() else 60)
                )
                raise DomainError(
                    "cloudflare_backoff",
                    "Cloudflare request limit reached; waiting before retrying",
                    429,
                )
            if response.status_code in {401, 403}:
                raise DomainError(
                    "cloudflare_permissions",
                    "Cloudflare rejected the API token or its permissions",
                    409,
                )
            response.raise_for_status()
            envelope = response.json()
            if not envelope.get("success"):
                raise ValueError()
            return envelope["result"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DomainError(
                "cloudflare_api",
                "Cloudflare request failed; saved configuration was preserved",
                502,
            ) from None

    async def credentials(self, body):
        async with self.lock:
            state = self.state()
            if state["accountId"] and state["accountId"] != body.accountId and state["tunnels"]:
                raise DomainError(
                    "cloudflare_account", "Use the account that owns the saved tunnels", 409
                )
            token = body.token.get_secret_value().strip()
            await self.call(
                "GET",
                "/accounts/" + body.accountId + "/cfd_tunnel",
                params={"is_deleted": "false", "per_page": 1},
                token=token,
            )
            if self.configured():
                self.store.replace("api_token", token.encode())
            else:
                self.store.put("api_token", token.encode())
            state["accountId"] = body.accountId
            self.save(state)
            return self.public()

    def public(self):
        return {
            **self.state(),
            "configured": self.configured(),
            "apps": [{"packageId": key, "name": value} for key, value in APPS.items()],
        }

    def prefix(self, state, tunnel):
        if not any(item["id"] == tunnel for item in state["tunnels"]):
            raise DomainError(
                "tunnel_not_owned", "Choose a tunnel created through this MediaHub", 409
            )
        return "/accounts/" + state["accountId"] + "/cfd_tunnel/" + tunnel

    async def create(self, name):
        async with self.lock:
            state = self.state()
            if len(state["tunnels"]) >= 8:
                raise DomainError(
                    "tunnel_limit", "At most eight managed tunnels are supported", 409
                )
            if any(item["name"] == name for item in state["tunnels"]):
                raise DomainError("tunnel_exists", "A tunnel with this name is already saved", 409)
            remote = await self.call(
                "POST",
                "/accounts/" + state["accountId"] + "/cfd_tunnel",
                {"name": name, "config_src": "cloudflare"},
            )
            tunnel = {"id": str(UUID(remote["id"])), "name": name}
            state["tunnels"].append(tunnel)
            self.save(state)
            from mediahub.apps.cloudflared import register_cloudflared_app

            register_cloudflared_app(self.svc)
            self.svc.events.record(
                "cloudflare.tunnel_created",
                tunnel["id"],
                "Cloudflare tunnel created; connector required",
            )
            return self.public()

    async def dns_record(self, body):
        async with self.lock:
            name = hostname(body.hostname)
            zone = await self.call("GET", "/zones/" + body.zoneId)
            if name != zone["name"] and not name.endswith("." + zone["name"]):
                raise DomainError(
                    "wrong_zone", "The hostname does not belong to the selected DNS zone", 422
                )
            if body.type == "CNAME":
                content = hostname(body.content)
                if content == name:
                    raise DomainError("dns_loop", "A CNAME cannot point to itself", 422)
            else:
                try:
                    address = ip_address(body.content)
                    if address.version != (4 if body.type == "A" else 6):
                        raise ValueError()
                    content = str(address)
                except ValueError:
                    raise DomainError(
                        "dns_address", "Choose an IP address matching the record type", 422
                    ) from None
            prefix = "/zones/" + body.zoneId + "/dns_records"
            existing = await self.call("GET", prefix, params={"name": name, "per_page": 100})
            values = {"type": body.type, "content": content, "proxied": body.proxied}
            if existing:
                if len(existing) == 1 and all(
                    existing[0].get(key) == value for key, value in values.items()
                ):
                    return self.public()
                raise DomainError(
                    "dns_conflict",
                    "This hostname already has DNS records; review them before replacing anything",
                    409,
                )
            remote = await self.call(
                "POST", prefix, {"name": name, **values, "ttl": 1, "comment": "Created by MediaHub"}
            )
            state = self.state()
            state.setdefault("dnsRecords", []).append(
                {"id": remote["id"], "zoneId": body.zoneId, "hostname": name, **values}
            )
            self.save(state)
            return self.public()

    async def origin(self, package):
        if package not in APPS:
            raise DomainError("unsupported_app", "Choose a supported MediaHub app", 422)
        if package == "mediahub":
            address = self.svc.config.base_url
        elif package in {"org.mediahub.plex", "org.mediahub.jellyfin"}:
            app = package.rsplit(".", 1)[-1]
            key = "plex_installation" if app == "plex" else "container_installation_" + app
            with self.svc.sessions() as db:
                binding = db.scalar(select(Setting).where(Setting.key == key))
                if not binding:
                    raise DomainError(
                        "app_unavailable", "Install the app on a paired MediaHub host first", 409
                    )
                host = binding.value["hostId"]
            client = self.svc.hosts.client(host)
            report = await client.request(
                "GET",
                "/v1/plex/status" if app == "plex" else "/v1/container-apps/" + app + "/status",
            )
            if report.get("state") != "running":
                raise DomainError(
                    "app_unavailable", "The linked app is not running; route was preserved", 409
                )
            address = report.get("url")
        else:
            with self.svc.sessions() as db:
                app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package))
                if not app or app.is_mock or app.state in {"uninstalled", "removing"}:
                    raise DomainError("app_unavailable", "The linked app is not installed", 409)
            address = self.svc.config.sso_app_urls.get(
                package
            ) or self.svc.config.operator_app_urls.get(package)
            if package in self.svc.managed_apps.policy:
                rows = await self.svc.managed_apps.containers(package)
                service, port = (
                    ("sso-proxy", "443/tcp")
                    if package.endswith("mediavpn")
                    else ("app", "18800/tcp")
                )
                row = next(
                    (
                        item
                        for item in rows
                        if item["Config"]["Labels"].get("com.docker.compose.service") == service
                    ),
                    None,
                )
                if row is None or not row["State"].get("Running"):
                    raise DomainError(
                        "app_unavailable", "The linked app is not running; route was preserved", 409
                    )
                actual = await self.svc.managed_apps.docker(
                    "GET", "/containers/" + row["Id"] + "/json"
                )
                bindings = actual.get("NetworkSettings", {}).get("Ports", {}).get(port) or []
                if not bindings:
                    raise DomainError(
                        "app_unavailable", "The app has no published local web port", 409
                    )
                binding = next(
                    (item for item in bindings if ":" not in item["HostIp"]), bindings[0]
                )
                host = binding["HostIp"]
                if host in {"", "0.0.0.0", "::"}:
                    host = urlsplit(self.svc.config.base_url).hostname
                host = "[" + host + "]" if ":" in host else host
                address = "https://" + host + ":" + binding["HostPort"]
        parsed = urlsplit(address or "")
        try:
            ip = ip_address(parsed.hostname or "")
            valid = ip.is_private and not (ip.is_unspecified or ip.is_multicast or ip.is_link_local)
            _ = parsed.port
        except ValueError:
            valid = parsed.hostname in {"localhost", "core", "agent"}
        if (
            not valid
            or parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise DomainError("app_origin", "The app needs a valid local HTTP(S) address", 409)
        return address.rstrip("/")

    async def bind(self, body):
        async with self.lock:
            state = self.state()
            tunnel = str(body.tunnelId)
            self.prefix(state, tunnel)
            name = hostname(body.hostname)
            if len(state["routes"]) >= 32 or any(
                item["hostname"] == name for item in state["routes"]
            ):
                raise DomainError(
                    "route_exists",
                    "This hostname is already linked or the route limit was reached",
                    409,
                )
            zone = await self.call("GET", "/zones/" + body.zoneId)
            if name != zone["name"] and not name.endswith("." + zone["name"]):
                raise DomainError(
                    "wrong_zone", "The hostname does not belong to the selected DNS zone", 422
                )
            origin = await self.origin(body.packageId)
            route = {
                "id": uuid4().hex,
                "tunnelId": tunnel,
                "zoneId": body.zoneId,
                "hostname": name,
                "packageId": body.packageId,
                "autoSync": body.autoSync,
                "caPool": body.caPool,
                "lastApplied": None,
                "status": "pending",
                "message": "Publishing app route",
            }
            # Persist before remote writes so partial DNS/config success can be retried.
            state["routes"].append(route)
            self.save(state)
            await self.reconcile_route(state, route, origin)
            self.save(state)
            self.monitor_routes(state)
            return self.public()

    async def reconcile_route(self, state, route, origin):
        try:
            prefix = self.prefix(state, route["tunnelId"])
            remote = await self.call("GET", prefix + "/configurations")
            config = copy.deepcopy(
                remote.get("config") or {"ingress": [{"service": "http_status:404"}]}
            )
            ingress = config.get("ingress") or [{"service": "http_status:404"}]
            config["ingress"] = ingress
            matches = [
                item for item in ingress if item.get("hostname", "").lower() == route["hostname"]
            ]
            if len(matches) > 1 or (
                matches
                and (
                    matches[0].get("path")
                    or matches[0].get("service") not in {route["lastApplied"], origin}
                )
            ):
                raise DomainError(
                    "route_conflict",
                    "This route was changed outside MediaHub; automatic changes are paused",
                    409,
                )
            records = await self.call(
                "GET",
                "/zones/" + route["zoneId"] + "/dns_records",
                params={"name": route["hostname"], "per_page": 100},
            )
            target = route["tunnelId"] + ".cfargotunnel.com"
            if records and (
                len(records) != 1
                or records[0].get("type") != "CNAME"
                or records[0].get("content", "").rstrip(".") != target
                or not records[0].get("proxied")
            ):
                raise DomainError(
                    "dns_conflict",
                    "An existing DNS record uses this hostname; it was not overwritten",
                    409,
                )
            if not records:
                await self.call(
                    "POST",
                    "/zones/" + route["zoneId"] + "/dns_records",
                    {
                        "type": "CNAME",
                        "name": route["hostname"],
                        "content": target,
                        "proxied": True,
                        "ttl": 1,
                    },
                )
            rule = matches[0] if matches else {"hostname": route["hostname"]}
            changed = rule.get("service") != origin
            rule["service"] = origin
            if not matches:
                if origin.startswith("https:"):
                    rule["originRequest"] = {"caPool": route["caPool"]}
                ingress.insert(0, rule)
            if changed:
                latest = await self.call("GET", prefix + "/configurations")
                if latest.get("version") != remote.get("version") or latest.get(
                    "config"
                ) != remote.get("config"):
                    raise DomainError(
                        "route_conflict",
                        "Tunnel configuration changed during synchronization; retry after reviewing it",
                        409,
                    )
                await self.call("PUT", prefix + "/configurations", {"config": config})
                self.svc.events.record(
                    "cloudflare.route_synced", route["id"], "Linked app origin synchronized"
                )
            route.update(
                lastApplied=origin,
                status="synced",
                message="App route is up to date",
                checkedAt=int(time.time()),
            )
            if route["packageId"] == "mediahub":
                self.allow_hub_origin(route["hostname"])
            # Publishing this app hostname explicitly configures its optional external address.
            if route["packageId"] != "mediahub":
                key = "app_address:" + route["packageId"]
                with self.svc.sessions.begin() as db:
                    row = db.scalar(select(Setting).where(Setting.key == key))
                    if row is None:
                        db.add(
                            Setting(key=key, value={"externalUrl": "https://" + route["hostname"]})
                        )
                    elif not row.value.get("externalUrl"):
                        row.value = {"externalUrl": "https://" + route["hostname"]}
        except DomainError as error:
            route.update(status="error", message=error.message, checkedAt=int(time.time()))

    async def sync(self, force=False):
        async with self.lock:
            if not self.configured():
                return self.public()
            state = self.state()
            for route in state["routes"]:
                if not (force or route["autoSync"]):
                    continue
                try:
                    origin = await self.origin(route["packageId"])
                    # No Cloudflare requests when the app endpoint is unchanged.
                    if (
                        force
                        or route.get("status") != "synced"
                        or origin != route.get("lastApplied")
                    ):
                        await self.reconcile_route(state, route, origin)
                except DomainError as error:
                    route.update(status="error", message=error.message, checkedAt=int(time.time()))
                self.save(state)
            self.monitor_routes(state)
            return self.public()

    async def poll(self):
        while True:
            try:
                await self.sync()
            except (DomainError, OSError, ValueError):
                pass
            await asyncio.sleep(60)


@router.get("")
def status(request: Request):
    return result(services(request).cloudflare_management.public())


@router.put("/credentials")
async def credentials(body: Credentials, request: Request):
    return result(await services(request).cloudflare_management.credentials(body))


@router.delete("/credentials")
async def disconnect(request: Request):
    manager = services(request).cloudflare_management
    async with manager.lock:
        manager.store.delete("api_token")
        return result(manager.public())


@router.post("/tunnels")
async def create(body: NewTunnel, request: Request):
    return result(await services(request).cloudflare_management.create(body.name))


@router.post("/dns")
async def create_dns(body: DNSRecord, request: Request):
    return result(await services(request).cloudflare_management.dns_record(body))


@router.post("/tunnels/{tunnel_id}/install-connector")
async def install_connector(tunnel_id: UUID, request: Request):
    from mediahub.cloudflare_connector import install

    manager = services(request).cloudflare_management
    async with manager.lock:
        connector = await install(manager, str(tunnel_id))
        state = manager.state()
        state.setdefault("connectors", {})[str(tunnel_id)] = connector
        manager.save(state)
        return result(manager.public())


@router.post("/tunnels/{tunnel_id}/token")
async def connector_token(tunnel_id: UUID, request: Request):
    manager = services(request).cloudflare_management
    state = manager.state()
    token = await manager.call("GET", manager.prefix(state, str(tunnel_id)) + "/token")
    return Response(
        str(token),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="cloudflared-token.txt"',
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/routes")
async def bind(body: RouteInput, request: Request):
    return result(await services(request).cloudflare_management.bind(body))


@router.put("/routes/{route_id}")
async def mode(route_id: str, body: RouteMode, request: Request):
    manager = services(request).cloudflare_management
    async with manager.lock:
        state = manager.state()
        row = next((item for item in state["routes"] if item["id"] == route_id), None)
        if not row:
            raise DomainError("route_not_found", "Route not found", 404)
        row["autoSync"] = body.autoSync
        manager.save(state)
        return result(manager.public())


@router.post("/sync")
async def sync(request: Request):
    return result(await services(request).cloudflare_management.sync(force=True))
