from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.db import InstalledApp, Setting
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
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"} or port == 0:
        raise DomainError("invalid_app_address", "Use an HTTPS origin without credentials, path or query")
    host = "[" + hostname + "]" if ":" in hostname else hostname
    return "https://" + host + (":" + str(port) if port and port != 443 else "")


def saved_address(svc, package_id):
    with svc.sessions() as db:
        row = db.scalar(select(Setting).where(Setting.key == "app_address:" + package_id))
        return row.value.get("externalUrl", "") if row else ""


def describe(svc, package_id):
    with svc.sessions() as db:
        installed = db.scalar(select(InstalledApp).where(InstalledApp.package_id == package_id, InstalledApp.state != "uninstalled"))
        connected = package_id in svc.config.operator_app_urls or package_id in svc.config.sso_app_urls
        if not installed and not connected:
            raise DomainError("app_not_found", "This app is not installed or connected", 404)
        name = installed.name if installed else {"org.mediahub.mediaseed": "MediaSeed", "org.mediahub.mediavpn": "MediaVPN"}.get(package_id, package_id)
        removable = None
        if installed and not installed.is_mock:
            adapter = svc.apps.adapters.get(installed.id)
            definition = getattr(adapter, "definition", None)
            if hasattr(definition, "binding_key") or package_id in {"org.mediahub.cloudflared", "org.mediahub.windows-share"}:
                removable = svc.apps.get(installed.id)
    return {
        "packageId": package_id,
        "name": name,
        "externalUrl": saved_address(svc, package_id),
        "localUrl": svc.config.operator_app_urls.get(package_id),
        "ssoOrigin": svc.config.sso_app_urls.get(package_id),
        "ssoManaged": package_id in svc.config.sso_app_urls,
        "routingManaged": False,
        "removableApp": removable,
        "configurationPath": {"org.mediahub.cloudflared": "/store/cloudflare", "org.mediahub.plex": "/apps/install/plex", "org.mediahub.jellyfin": "/apps/install/jellyfin", "org.mediahub.seedbox": "/apps/install/seedbox"}.get(package_id),
    }


class AddressSettings(StrictModel):
    externalUrl: str = Field(default="", max_length=2048)


@router.get("/{package_id}")
def settings(package_id: str, request: Request):
    return result(describe(services(request), package_id))


@router.put("/{package_id}")
def save(package_id: str, body: AddressSettings, request: Request):
    svc = services(request)
    current = describe(svc, package_id)
    address = normalize_address(body.externalUrl)
    if address and current["ssoManaged"] and address != normalize_address(current["ssoOrigin"]):
        raise DomainError("sso_origin_change_required", "Configure and verify this HTTPS origin in the app and its SSO registration before changing its address", 409)
    key = "app_address:" + package_id
    with svc.sessions.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key == key))
        if row:
            row.value = {"externalUrl": address}
        else:
            db.add(Setting(key=key, value={"externalUrl": address}))
    svc.events.record("app.address_saved", package_id, "App opening address updated; DNS and proxy configuration unchanged")
    return result(describe(svc, package_id))