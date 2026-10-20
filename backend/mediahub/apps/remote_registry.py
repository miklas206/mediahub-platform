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
    RemoteAppDefinition(
        "org.mediahub.plex-gpu-transcoder", "plex_gpu_installation",
        "/v1/plex-gpu", view_id="plex-gpu",
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
                from mediahub.apps.plex_gpu import PlexGPUAdapter

                adapter_type = PlexGPUAdapter if definition.package_id == "org.mediahub.plex-gpu-transcoder" else RemoteAppAdapter
                svc.apps.adapters[app.id] = adapter_type(
                    definition,
                    binding.value["hostId"],
                    svc.hosts.client,
                    svc.runtime_status_cache,
                    svc.events,
                    app.id,
                    status_enricher=(
                        svc.vpn_gateway.plex_forwarding.runtime_status
                        if definition.package_id == "org.mediahub.plex" else None
                    ),
                    metadata_cache=getattr(getattr(svc, "updates", None), "github_metadata", None),
                )
