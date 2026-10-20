"""Register a real linked sidecar; an address never implies an installation."""

from sqlalchemy import select

from mediahub.apps.remote_adapter import RemoteAppAdapter
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError

PACKAGE = "org.mediahub.plex-gpu-transcoder"


class PlexGPUAdapter(RemoteAppAdapter):
    removal_supported = False


async def discover(svc):
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "plex_gpu_installation"))
        if binding is None:
            return
        host_id = binding.value["hostId"]
    try:
        report = await svc.hosts.client(host_id).request("GET", "/v1/plex-gpu/status")
    except DomainError:
        return
    if report.get("installed") is not True:
        return
    with svc.sessions.begin() as db:
        key = "plex_gpu_installation"
        binding = db.scalar(select(Setting).where(Setting.key == key))
        value = {"hostId": report["hostId"], "installationId": report["installationId"]}
        if binding is None:
            db.add(Setting(key=key, value=value))
        else:
            binding.value = value
        app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == PACKAGE))
        if app is None:
            db.add(InstalledApp(package_id=PACKAGE, name="Plex GPU Transcoder",
                                version=report.get("version", "unknown"),
                                state=report["state"], is_mock=False))
        else:
            app.version, app.state, app.is_mock = report.get("version", "unknown"), report["state"], False
