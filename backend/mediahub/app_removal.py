"""Explicit, data-preserving removal through the owning Agent."""

from sqlalchemy import select

from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError
from mediahub.windows_share import PACKAGE_ID as WINDOWS_SHARE
from mediahub.windows_share import SETTING_KEY as WINDOWS_SHARE_KEY

CLOUDFLARE = "org.mediahub.cloudflared"


async def removal_status(svc, app_id):
    app = svc.apps.get(app_id)
    if app["state"] == "uninstalled":
        return {"state": "succeeded", "dataPreserved": True}
    adapter = svc.apps.adapter(app_id)
    if app["packageId"] == WINDOWS_SHARE:
        return {
            "state": "ready",
            "installationId": app_id,
            "mode": "monitoring",
            "message": "Remove the saved Windows connection and its monitoring from MediaHub. Server shares, files and Windows drive mappings are preserved.",
        }
    if app["packageId"] == CLOUDFLARE:
        return {
            "state": "ready",
            "installationId": app_id,
            "mode": "monitoring",
            "message": "Remove Cloudflare monitoring from MediaHub. The tunnel, DNS and published routes keep running.",
        }
    definition = getattr(adapter, "definition", None)
    if not definition or not hasattr(definition, "binding_key"):
        raise DomainError("uninstall_unsupported", "This app must be removed on its host", 409)
    report = await svc.hosts.client(adapter.host_id).request(
        "GET", definition.agent_prefix + "/uninstall-status"
    )
    if report.get("state") == "succeeded" and report.get("dataPreserved") is not True:
        raise DomainError(
            "removal_unverified", "Runtime removal has not passed its final checks", 409
        )
    with svc.sessions.begin() as db:
        binding = db.scalar(select(Setting).where(Setting.key == definition.binding_key))
        if not binding or report.get("installationId") != binding.value.get("installationId"):
            raise DomainError(
                "installation_changed", "Installation identity could not be verified", 409
            )
        if (
            app["state"] == "removing"
            and report.get("state") == "succeeded"
            and report.get("dataPreserved") is True
        ):
            db.get(InstalledApp, app_id).state = "uninstalled"
            db.delete(binding)
    if report.get("state") == "succeeded" and app["state"] != "removing":
        report = {
            **report,
            "state": "ready",
            "alreadyRemoved": True,
            "message": "The Agent confirms the runtime was removed. Confirm to remove its saved MediaHub registration; data stays preserved.",
        }
    return {
        **report,
        "mode": "runtime",
        "message": report.get("message")
        or "Remove the app containers and stop their services. Media, downloads, settings and credentials are preserved. Active transfers or playback will stop.",
    }


async def remove_app(svc, app_id, confirmed):
    report = await removal_status(svc, app_id)
    if not confirmed or confirmed != report.get("installationId"):
        raise DomainError("confirmation_required", "Exact installation confirmation required", 409)
    app = svc.apps.get(app_id)
    if app["packageId"] == WINDOWS_SHARE:
        with svc.sessions.begin() as db:
            binding = db.scalar(select(Setting).where(Setting.key == WINDOWS_SHARE_KEY))
            if binding:
                db.delete(binding)
            db.get(InstalledApp, app_id).state = "uninstalled"
        svc.windows_share.cached = None
        svc.apps.adapters.pop(app_id, None)
        svc.events.record(
            "app.monitoring_removed",
            app_id,
            "Windows share connection removed; server and files unchanged",
        )
        return {"state": "succeeded", "dataPreserved": True}
    if app["packageId"] == CLOUDFLARE:
        values = {
            "setup_mode": "existing-tunnel",
            "tunnel_name": "",
            "public_hostnames": "",
            "origin_url": "",
            "status_url": "",
            "tunnel_profiles": "",
        }
        svc.cloudflare_tunnel.configure(svc.catalog.save(CLOUDFLARE, values))
        with svc.sessions.begin() as db:
            db.get(InstalledApp, app_id).state = "uninstalled"
        svc.events.record(
            "app.monitoring_removed", app_id, "Cloudflare monitoring removed; tunnel unchanged"
        )
        return {"state": "succeeded", "dataPreserved": True}
    adapter = svc.apps.adapter(app_id)
    if report.get("alreadyRemoved"):
        with svc.sessions.begin() as db:
            db.get(InstalledApp, app_id).state = "uninstalled"
            binding = db.scalar(
                select(Setting).where(Setting.key == adapter.definition.binding_key)
            )
            if binding:
                db.delete(binding)
        return {"state": "succeeded", "dataPreserved": True}
    response = await svc.hosts.client(adapter.host_id).request(
        "POST",
        adapter.definition.agent_prefix + "/uninstall",
        {"confirmedInstallationId": confirmed},
    )
    with svc.sessions.begin() as db:
        db.get(InstalledApp, app_id).state = "removing"
    svc.events.record(
        "app.uninstall_requested", app_id, "Runtime removal requested; persistent data preserved"
    )
    return response
