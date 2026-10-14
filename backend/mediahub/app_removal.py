"""Explicit app reset through the owning Agent; external media is preserved."""

from sqlalchemy import select

from mediahub.db import AppConfiguration, InstalledApp, Setting
from mediahub.errors import DomainError
from mediahub.windows_share import PACKAGE_ID as WINDOWS_SHARE
from mediahub.windows_share import SETTING_KEY as WINDOWS_SHARE_KEY

CLOUDFLARE = "org.mediahub.cloudflared"


def forget_settings(db, package):
    changed = False
    for model, column, key in [(Setting, Setting.key, "app_address:" + package),
                               (AppConfiguration, AppConfiguration.package_id, package)]:
        row = db.scalar(select(model).where(column == key))
        if row:
            db.delete(row)
            changed = True
    gateway = db.scalar(select(Setting).where(Setting.key == "vpn-web-gateway"))
    if gateway:
        value = dict(gateway.value)
        removed = [row for row in value.get("routes", []) if row["packageId"] == package]
        if removed:
            retired = {row["id"]: row for row in value.get("retired", [])}
            retired.update({row["id"]: {**row, "previousExternalUrl": ""} for row in removed})
            value.update(routes=[row for row in value["routes"] if row["packageId"] != package], retired=list(retired.values()))
            changed = True
        if package == "org.mediahub.plex" and any(value.get(key) for key in
                ("plexPortEnabled", "plexPortManaged", "plexPortApplied", "plexPortStatus")):
            value.update(plexPortEnabled=False, plexPortManaged=False, plexPortApplied=False, plexPortStatus={})
            changed = True
        if changed:
            value["revision"] = value.get("revision", 0) + 1
            gateway.value = value
    return changed


def reconcile_removed_settings(svc):
    # Old releases could finish runtime removal but retain an opening address
    # and selected VPN domain. Repair only confirmed uninstalled remote apps.
    bindings = {"org.mediahub.plex": "plex_installation", "org.mediahub.jellyfin": "container_installation_jellyfin", "org.mediahub.seedbox": "seedbox_installation"}
    with svc.sessions.begin() as db:
        packages = db.scalars(select(InstalledApp.package_id).where(
            InstalledApp.state == "uninstalled", InstalledApp.is_mock.is_(False),
            InstalledApp.package_id.in_(bindings))).all()
        for package in set(packages):
            if db.scalar(select(InstalledApp.id).where(InstalledApp.package_id == package, InstalledApp.state != "uninstalled")):
                continue
            forget_settings(db, package)
            binding = db.scalar(select(Setting).where(Setting.key == bindings[package]))
            if binding:
                db.delete(binding)


async def removal_status(svc, app_id):
    app = svc.apps.get(app_id)
    if app["state"] == "uninstalled":
        return {"state": "succeeded", "dataPreserved": True}
    adapter = svc.apps.adapter(app_id)
    if getattr(adapter, "managed", False):
        try:
            return await svc.managed_apps.status(app["packageId"])
        except DomainError as error:
            if error.code != "app_dependency":
                raise
            return {
                "state": "blocked",
                "mode": "runtime",
                "message": error.message,
                "configurationPath": "/store/mediavpn",
            }
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
    if report.get("state") == "succeeded" and report.get("configurationReset") is not True:
        raise DomainError("reset_unverified", "App configuration reset has not been verified. Update the Agent and retry removal.", 409)
    if report.get("state") == "succeeded":
        with svc.sessions() as db:
            binding = db.scalar(select(Setting).where(Setting.key == definition.binding_key))
            if not binding or report.get("installationId") != binding.value.get("installationId"):
                raise DomainError("installation_changed", "Installation identity could not be verified", 409)
        await svc.shared_vpn.forget_peer(app["packageId"], adapter.host_id)
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
            forget_settings(db, app["packageId"])
    if report.get("state") == "succeeded" and app["state"] == "removing":
        svc.vpn_gateway.schedule()
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
        or "Remove the app containers and stop their services. App settings and credentials are removed for a fresh installation. Media and downloads are preserved. Active transfers or playback will stop.",
    }


async def remove_app(svc, app_id, confirmed):
    app = svc.apps.get(app_id)
    adapter = svc.apps.adapters.get(app_id)
    if getattr(adapter, "managed", False):
        response = await svc.managed_apps.remove(app["packageId"], confirmed)
        if response["state"] in {"accepted", "running"}:
            with svc.sessions.begin() as db:
                db.get(InstalledApp, app_id).state = "removing"
        return response
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
            configuration = db.scalar(select(AppConfiguration).where(AppConfiguration.package_id == app["packageId"]))
            if configuration:
                db.delete(configuration)
        return {"state": "succeeded", "dataPreserved": True, "configurationReset": True}
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
