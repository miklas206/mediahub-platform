"""Optional Cloudflare Tunnel app backed by the read-only status helper."""

from dataclasses import dataclass

from packaging.version import Version
from sqlalchemy import select

from mediahub.apps.manifest import parse_manifest
from mediahub.contracts import Health, HealthCheck
from mediahub.db import InstalledApp
from mediahub.errors import DomainError


@dataclass(frozen=True)
class CloudflaredAppDefinition:
    package_id: str = "org.mediahub.cloudflared"
    view_id: str = "cloudflare"


class CloudflaredAppAdapter:
    definition = CloudflaredAppDefinition()

    def __init__(self, monitor, events, app_id):
        self.monitor, self.events, self.app_id = monitor, events, app_id

    async def status(self):
        tunnel = await self.monitor.status()
        health = tunnel["status"]
        if health == "not_configured":
            health = "unknown"
        return {
            "health": health,
            "available": bool(tunnel["configured"]),
            "observedAt": tunnel["checkedAt"],
            "cached": tunnel.get("cached", False),
            "agentOnline": bool(tunnel.get("metricsReachable")),
            "cloudflare": tunnel,
        }

    async def health(self):
        report = await self.monitor.status()
        state = report["status"]
        overall = {
            "healthy": "healthy",
            "degraded": "degraded",
            "critical": "unhealthy",
            "not_configured": "unknown",
        }.get(state, "unknown")
        checks = [
            HealthCheck(
                name="tunnel",
                status=(
                    "healthy"
                    if report.get("metricsReachable") and report.get("connections", 0) > 0
                    else "unhealthy"
                    if report.get("configured")
                    else "unknown"
                ),
                message=(
                    f"{report.get('connections', 0)} Cloudflare connection(s)"
                    if report.get("metricsReachable")
                    else "The local cloudflared status helper is unavailable"
                    if report.get("configured")
                    else "Monitoring is not configured"
                ),
            )
        ]
        checks.extend(
            HealthCheck(
                name=f"route:{route['hostname']}",
                status="healthy" if route["reachable"] else "unhealthy",
                message=route["message"],
            )
            for route in report.get("routes", [])
        )
        return Health(status=overall, summary=report["message"], checks=checks)

    async def updateCheck(self):
        return await self.monitor.update_check(force=True)

    async def logs(self):
        return {"entries": []}

    async def action(self, _action):
        raise DomainError(
            "read_only_app",
            "Cloudflare Tunnel is monitored read-only; service control remains on its host",
            400,
        )

    async def start(self):
        return await self.action("start")

    async def stop(self):
        return await self.action("stop")

    async def restart(self):
        return await self.action("restart")

    async def install(self):
        return await self.action("install")

    async def uninstall(self, confirmed_installation_id=None):
        return await self.action("uninstall")

    async def update(self, version):
        return await self.action("update")

    async def configure(self, settings):
        return await self.action("configure")


def register_cloudflared_app(svc):
    """Expose configured monitoring as an app without granting tunnel control."""

    manifest = parse_manifest(svc.config.manifest_dir / "cloudflared" / "manifest.yaml")
    with svc.sessions.begin() as db:
        app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == manifest.id))
        if app is None and not svc.config.cloudflared_status_url:
            return
        created = app is None
        if app is None:
            app = InstalledApp(
                package_id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                state="monitored",
                is_mock=False,
            )
            db.add(app)
            db.flush()
        else:
            app.name = manifest.name
            if Version(app.version) < Version(manifest.version):
                app.version = manifest.version
        app_id = app.id
    svc.apps.adapters[app_id] = CloudflaredAppAdapter(svc.cloudflare_tunnel, svc.events, app_id)
    if created:
        svc.events.record(
            "app.registered",
            app_id,
            "Cloudflare Tunnel registered as a read-only infrastructure app",
        )
