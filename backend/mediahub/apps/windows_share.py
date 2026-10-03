"""A genuine saved connection, with no authority to modify the SMB server."""

from dataclasses import dataclass

from sqlalchemy import select

from mediahub.contracts import Health, HealthCheck
from mediahub.db import InstalledApp
from mediahub.errors import DomainError
from mediahub.windows_share import APP_ID, PACKAGE_ID


@dataclass(frozen=True)
class WindowsShareDefinition:
    package_id: str = PACKAGE_ID
    view_id: str = "windows-share"


class WindowsShareAdapter:
    definition = WindowsShareDefinition()

    def __init__(self, service):
        self.service = service

    async def status(self):
        report = await self.service.status()
        return {
            "health": "unknown" if report["tcpReachable"] is not False else "degraded",
            "available": report["configured"],
            "observedAt": report["checkedAt"],
            "cached": report["cached"],
            "windowsShare": report,
        }

    async def health(self):
        report = await self.service.status()
        return Health(
            status="degraded" if report["tcpReachable"] is False else "unknown",
            summary=report["message"],
            checks=[
                HealthCheck(
                    name="core-tcp-445",
                    status="healthy"
                    if report["tcpReachable"]
                    else "unhealthy"
                    if report["tcpReachable"] is False
                    else "unknown",
                    message=report["message"],
                ),
                HealthCheck(
                    name="windows-folder-access",
                    status="unknown",
                    message="Run the Windows diagnostic helper on your PC to check local folder access",
                ),
            ],
        )

    async def logs(self):
        return {"entries": []}

    async def updateCheck(self):
        return {
            "supported": False,
            "reason": "Windows folder access is included with MediaHub; the SMB server is managed separately",
        }

    async def action(self, _action):
        raise DomainError(
            "read_only_app", "Windows folder access does not control the SMB server", 400
        )

    async def start(self):
        return await self.action("start")

    async def stop(self):
        return await self.action("stop")

    async def restart(self):
        return await self.action("restart")


def register_windows_share_app(svc):
    if svc.windows_share.configuration() is None:
        return
    manifest = svc.catalog.get(PACKAGE_ID)
    with svc.sessions.begin() as db:
        app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == PACKAGE_ID))
        if app is None:
            app = InstalledApp(
                id=APP_ID,
                package_id=PACKAGE_ID,
                name=manifest.name,
                version=manifest.version,
                state="configured",
                is_mock=False,
            )
            db.add(app)
        else:
            app.name, app.version, app.state = manifest.name, manifest.version, "configured"
        db.flush()
        app_id = app.id
    svc.apps.adapters[app_id] = WindowsShareAdapter(svc.windows_share)
