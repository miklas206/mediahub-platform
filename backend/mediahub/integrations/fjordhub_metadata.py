"""Allowlisted integration metadata and public updater status (not updater logs)."""

import math
import re
from urllib.parse import urlsplit

from mediahub.integrations.fjordhub import ProviderFailure

APP_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
ICON_PATH = re.compile(r"/static/logos/(?:icons/)?[A-Za-z0-9_.-]+\.(?:png|jpg|jpeg|webp)\Z")
REGISTRY_ICONS = {
    "fjordflix": "/qlerup/fjordflix/main/app/static/logos/icons/fjordflix-mark-transparent-512.png",
    "fjordlens": "/qlerup/fjordlens/main/static/logos/icons/fjordlens-mark-transparent-512.png",
    "fjord3d": "/qlerup/fjord3d/main/static/logos/icons/fjord3D-mark-transparent-512.png",
    "fjordparcel": "/qlerup/fjordparcel/main/static/logos/icons/fjordparcel-mark-transparent-512.png",
    "orbitmap": "/qlerup/orbitmap/main/app/public/hub-icon.png",
    "urban-explorer": "/qlerup/urban-explorer/main/app/public/hub-icon.png",
    "fjordbudget": "/qlerup/fjordbudget/main/static/logos/icon-512.png",
    "fjordvpn": "/qlerup/fjordvpn/main/static/brand/fjordvpn-icon-512.png",
}


def icon_path(value, client, app_id=None):
    if not isinstance(value, str) or len(value) > 500 or any(c in value for c in "%\\"):
        return None
    if any(ord(c) < 33 for c in value) or (client._access_token and client._access_token in value):
        return None
    try:
        url, base = urlsplit(value), urlsplit(client.base_url)
        if not url.scheme and not url.netloc and value.startswith("/") and not value.startswith("//"):
            url = urlsplit(client.base_url + value)
        if url.fragment or (url.query and not re.fullmatch(r"v=[A-Za-z0-9_.-]{1,80}", url.query)):
            return None
        if (url.scheme, url.netloc) == ("https", "raw.githubusercontent.com"):
            paths = [REGISTRY_ICONS.get(app_id)] if app_id else REGISTRY_ICONS.values()
            return value if url.path in paths else None
        if (url.scheme, url.netloc) != (base.scheme, base.netloc) or not ICON_PATH.fullmatch(url.path):
            return None
        return url.path + ("?" + url.query if url.query else "")
    except ValueError:
        return None


def app_info(client, body):
    if not isinstance(body, dict):
        raise ProviderFailure("invalid_response")
    result = {}
    for key, item in list(body.items())[:200]:
        if not APP_ID.fullmatch(key) or not isinstance(item, dict) or item.get("id") != key:
            continue
        if client._access_token and client._access_token in key:
            continue
        permissions = item.get("permissions") or {}
        if not isinstance(permissions, dict):
            permissions = {}
        port = item.get("port")
        result[key] = {
            "id": key,
            "name": client.text(item.get("name")) or key,
            "installed": item.get("installed") is True,
            "port": port if type(port) is int and 1 <= port <= 65535 else None,
            "icon_path": icon_path(item.get("icon_url"), client, key),
            "permissions": {
                "updates": permissions.get("updates") is True,
                "app_data": permissions.get("app_data") is True,
            },
        }
    return result


def update_status(client, body, identifier):
    if not isinstance(body, dict) or body.get("app_id") != identifier:
        raise ProviderFailure("invalid_response")
    if (
        type(body.get("ok")) is not bool
        or type(body.get("running")) is not bool
        or type(body.get("update_available")) is not bool
    ):
        raise ProviderFailure("invalid_response")
    result = {
        "app_id": identifier,
        "ok": body["ok"],
        "running": body["running"],
        "update_available": body["update_available"],
        "stale": False,
    }
    for field in (
        "state",
        "label",
        "current_rev",
        "remote_rev",
        "checked_at",
        "started_at",
        "finished_at",
    ):
        if isinstance(body.get(field), str):
            result[field] = client.text(body[field], 100)
        elif (
            field.endswith("_at")
            and type(body.get(field)) in (int, float)
            and math.isfinite(body[field])
            and 0 <= body[field] < 1e12
        ):
            result[field] = body[field]
    for field in ("available", "dirty"):
        if type(body.get(field)) is bool:
            result[field] = body[field]
    if not result["ok"]:
        result["error"] = "Opdateringen kunne ikke udføres. Se status i FjordHub."
    return result


def updates(client, body):
    if not isinstance(body, dict):
        raise ProviderFailure("invalid_response")
    result = {}
    for key, value in list(body.items())[:200]:
        if not APP_ID.fullmatch(key) or (client._access_token and client._access_token in key):
            continue
        result[key] = update_status(client, value, key)
    return result
