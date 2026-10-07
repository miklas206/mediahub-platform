"""Composition root: package bindings live here, not in dashboard conditionals."""

from sqlalchemy import select

from mediahub.apps.containers import CONTAINER_APPS
from mediahub.apps.remote_adapter import RemoteAppAdapter, RemoteAppDefinition
from mediahub.apps.remote_status import RemoteStatusCache
from mediahub.db import InstalledApp, Setting

DEFINITIONS = (
    RemoteAppDefinition(
        "org.mediahub.plex",
        "plex_installation",
        "/v1/plex",
        view_id="plex",
        supports_update_check=True,
    ),
    RemoteAppDefinition(
        "org.mediahub.seedbox",
        "seedbox_installation",
        "/v1/seedbox",
        ("restart-vpn", "restart-qbittorrent", "test-vpn"),
    ),
) + tuple(
    RemoteAppDefinition(
        "org.mediahub." + app, "container_installation_" + app,
        "/v1/container-apps/" + app, view_id="container",
    ) for app in CONTAINER_APPS
)


def register_remote_apps(svc):
    if not hasattr(svc, "runtime_status_cache"):
        svc.runtime_status_cache = RemoteStatusCache()
    with svc.sessions() as db:
        for definition in DEFINITIONS:
            binding = db.scalar(select(Setting).where(Setting.key == definition.binding_key))
            app = db.scalar(
                select(InstalledApp).where(InstalledApp.package_id == definition.package_id)
            )
            if binding is not None and app is not None:
                svc.apps.adapters[app.id] = RemoteAppAdapter(
                    definition,
                    binding.value["hostId"],
                    svc.hosts.client,
                    svc.runtime_status_cache,
                    svc.events,
                    app.id,
                )
