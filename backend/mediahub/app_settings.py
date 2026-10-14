import time
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.db import ExternalIntegration, InstalledApp, Setting
from mediahub.errors import DomainError

router = APIRouter(prefix="/app-settings", dependencies=[Depends(administrator)])


def normalize_address(value):
    value = value.strip()
    if not value:
        return ""
    if any(ord(char) <= 32 for char in value) or "\\" in value:
        raise DomainError("invalid_app_address", "Use a complete HTTPS address without whitespace")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = (parsed.hostname or "").encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        raise DomainError("invalid_app_address", "Invalid app address") from None
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port == 0
    ):
        raise DomainError(
            "invalid_app_address", "Use an HTTPS origin without credentials, path or query"
        )
    host = "[" + hostname + "]" if ":" in hostname else hostname
    return "https://" + host + (":" + str(port) if port and port != 443 else "")


def saved_address(svc, package_id):
    with svc.sessions() as db:
        row = db.scalar(select(Setting).where(Setting.key == "app_address:" + package_id))
        return row.value.get("externalUrl", "") if row else ""


def describe(svc, package_id):
    with svc.sessions() as db:
        installed = db.scalar(
            select(InstalledApp).where(
                InstalledApp.package_id == package_id, InstalledApp.state != "uninstalled"
            )
        )
        integration = (
            db.scalar(
                select(ExternalIntegration).where(
                    ExternalIntegration.provider == "fjordhub",
                    ExternalIntegration.enabled.is_(True),
                )
            )
            if package_id == "org.mediahub.fjordhub"
            else None
        )
        deployment = (
            svc.fjordhub_deploy.latest()
            if package_id == "org.mediahub.fjordhub" and hasattr(svc, "fjordhub_deploy")
            else None
        )
        deployed = bool(
            deployment
            and deployment.get("state") == "succeeded"
            and (deployment.get("verification") or {}).get("state") != "removed"
            and (deployment.get("uninstall") or {}).get("state") != "removed"
        )
        connected = (
            package_id in svc.config.operator_app_urls
            or package_id in svc.config.sso_app_urls
            or integration is not None
            or deployed
        )
        if not installed and not connected:
            raise DomainError("app_not_found", "This app is not installed or connected", 404)
        name = (
            installed.name
            if installed
            else {
                "org.mediahub.mediaseed": "MediaSeed",
                "org.mediahub.mediavpn": "MediaVPN",
                "org.mediahub.fjordhub": "FjordHub",
            }.get(package_id, package_id)
        )
        removable = None
        if installed and svc.apps.supports_removal(installed):
            removable = svc.apps.get(installed.id)
    manager = getattr(svc, "cloudflare_management", None)
    routing_managed = bool(
        manager
        and any(
            route["packageId"] == package_id
            and route.get("status") == "synced"
            and "https://" + route["hostname"] == saved_address(svc, package_id)
            for route in manager.state()["routes"]
        )
    )
    return {
        "installationId": installed.id if installed else None,
        "state": installed.state if installed else "connected",
        "version": installed.version if installed else None,
        "packageId": package_id,
        "name": name,
        "externalUrl": saved_address(svc, package_id),
        "localUrl": svc.config.operator_app_urls.get(package_id)
        or (integration.base_url if integration else None),
        "ssoOrigin": (saved_address(svc, package_id) or svc.config.sso_app_urls[package_id])
        if package_id in svc.config.sso_app_urls
        else None,
        "ssoManaged": package_id in svc.config.sso_app_urls,
        "routingManaged": routing_managed,
        "removableApp": removable,
        "configurationPath": {
            "org.mediahub.fjordhub": f"/integrations/{integration.id}"
            if integration
            else "/store/fjordhub",
            "org.mediahub.cloudflared": "/store/cloudflare",
            "org.mediahub.plex": f"/apps/{installed.id}" if installed else "/apps/install/plex",
            "org.mediahub.jellyfin": "/apps/install/jellyfin",
            "org.mediahub.seedbox": "/apps/install/seedbox",
        }.get(package_id),
    }


class AddressSettings(StrictModel):
    externalUrl: str = Field(default="", max_length=2048)


def controls(svc, app):
    try:
        adapter = svc.apps.adapter(app["id"])
        actions = (
            ["start", "stop", "restart"]
            if (
                getattr(adapter, "managed", False)
                or (
                    hasattr(adapter, "action")
                    and hasattr(getattr(adapter, "definition", None), "binding_key")
                )
            )
            else []
        )
        package = app["packageId"]
        return {
            "actions": actions,
            "logs": callable(getattr(adapter, "logs", None)),
            "updateCheck": callable(getattr(adapter, "updateCheck", None)),
            "updatePath": "/settings?section=Updates"
            if getattr(adapter, "managed", False)
            else "/apps/install/" + package.removeprefix("org.mediahub.")
            if getattr(getattr(adapter, "definition", None), "view_id", None) == "container"
            else None,
        }
    except DomainError:
        return {"actions": [], "logs": False, "updateCheck": False, "updatePath": None}


async def runtime_summary(svc, app):
    unknown = {"running": None, "startedAt": None, "runtimeAvailable": False}
    try:
        adapter = svc.apps.adapter(app["id"])
        if hasattr(adapter, "runtime_summary"):
            report = await adapter.runtime_summary()
        elif hasattr(adapter, "definition") and hasattr(adapter, "status"):
            report = await adapter.status()
        else:
            return unknown
        if (
            not isinstance(report, dict)
            or report.get("available") is False
            or report.get("agentOnline") is False
        ):
            return unknown
        plex = report.get("plex") or {}
        torrent = report.get("qBittorrent") or {}
        state = report.get("state")
        running = (
            plex.get("running")
            if plex
            else torrent.get("running")
            if state is None
            and torrent
            and getattr(getattr(adapter, "definition", None), "view_id", None) == "seedbox"
            else state == "running"
            if state
            else None
        )
        started = report.get("startedAt") or plex.get("startedAt")
        try:
            moment = datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None
            if moment and (moment.tzinfo is None or not 0 < moment.timestamp() <= time.time() + 5):
                started = None
        except (ValueError, AttributeError, OverflowError):
            started = None
        return {
            "running": running,
            "startedAt": started if running is True else None,
            "runtimeAvailable": True,
            "runtimeState": state,
            "localUrl": svc.config.operator_app_urls.get(app["packageId"]) or report.get("url"),
            "containers": report.get("containers", []),
            "observedAt": report.get("observedAt", time.time()),
        }
    except DomainError:
        return unknown


@router.get("/{package_id}")
async def settings(package_id: str, request: Request):
    svc = services(request)
    data = describe(svc, package_id)
    if data["installationId"]:
        app = svc.apps.get(data["installationId"])
        data["controls"] = controls(svc, app)
        summary = await runtime_summary(svc, app)
        data.update(summary)
        if summary["runtimeAvailable"]:
            data["health"] = (await svc.apps.health(app["id"])).model_dump()
        else:
            data["health"] = {"status": "unknown", "summary": "Status unavailable", "checks": []}
    else:
        data.update(running=None, startedAt=None, runtimeAvailable=False)
    return result(data)


@router.put("/{package_id}")
def save(package_id: str, body: AddressSettings, request: Request):
    svc = services(request)
    describe(svc, package_id)
    address = normalize_address(body.externalUrl)
    key = "app_address:" + package_id
    with svc.sessions.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key == key))
        if row:
            row.value = {"externalUrl": address}
        else:
            db.add(Setting(key=key, value={"externalUrl": address}))
    svc.events.record(
        "app.address_saved",
        package_id,
        "App opening address updated; DNS and proxy configuration unchanged",
    )
    return result(describe(svc, package_id))
