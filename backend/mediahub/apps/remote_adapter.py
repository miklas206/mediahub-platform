"""Multi-service app adapter. Core only calls the paired Agent, never components."""

from dataclasses import dataclass

from mediahub.contracts import Health, HealthCheck
from mediahub.errors import DomainError


@dataclass(frozen=True)
class RemoteAppDefinition:
    package_id: str
    binding_key: str
    agent_prefix: str
    component_actions: tuple[str, ...] = ()
    view_id: str = "seedbox"
    supports_update_check: bool = False


class RemoteAppAdapter:
    def __init__(self, definition, host_id, client_factory, status_cache, events, app_id):
        self.definition, self.host_id = definition, host_id
        self.client_factory, self.status_cache = client_factory, status_cache
        self.events, self.app_id = events, app_id

    async def status(self):
        return await self.status_cache.get(
            self.host_id,
            self.client_factory(self.host_id),
            self.definition.agent_prefix + "/status",
        )

    async def health(self):
        report = await self.status()
        states = {
            "healthy": "healthy",
            "degraded": "degraded",
            "critical": "unhealthy",
            "offline": "unknown",
            "unknown": "unknown",
        }
        return Health(
            status=states.get(report["health"], "unknown"),
            summary="Remote app: " + report["health"],
            checks=[
                HealthCheck(
                    name=c["name"], status=states.get(c["status"], "unknown"), message=c["status"]
                )
                for c in report.get("checks", [])
            ],
        )

    async def action(self, action):
        if action not in ("start", "stop", "restart", *self.definition.component_actions):
            raise DomainError("unsupported_action", "Action not supported by this app", 400)
        self.events.record(
            "app.action_requested", self.app_id, f"{action} requested on host {self.host_id}"
        )
        try:
            response = await self.client_factory(self.host_id).request(
                "POST", self.definition.agent_prefix + "/actions/" + action
            )
        except DomainError:
            self.events.record(
                "app.action_failed", self.app_id, f"{action} failed on host {self.host_id}"
            )
            raise
        self.status_cache.entries.pop(
            (self.host_id, self.definition.agent_prefix + "/status"), None
        )
        self.events.record(
            "app.action_accepted",
            self.app_id,
            f"{action} accepted on host {self.host_id}; verification pending",
        )
        return response

    async def start(self):
        return await self.action("start")

    async def stop(self):
        return await self.action("stop")

    async def restart(self):
        return await self.action("restart")

    async def logs(self):
        return await self.client_factory(self.host_id).request(
            "GET", self.definition.agent_prefix + "/logs"
        )

    async def updateCheck(self):
        if self.definition.supports_update_check:
            return await self.client_factory(self.host_id).request(
                "POST", self.definition.agent_prefix + "/update-check"
            )
        return {
            "supported": False,
            "reason": "Digest-pinned runtime; no automatic update provider configured",
        }

    async def restartVPN(self):
        return await self.action("restart-vpn")

    async def restartQBittorrent(self):
        return await self.action("restart-qbittorrent")

    async def testVPN(self):
        return await self.action("test-vpn")

    async def uninstall(self, confirmed_installation_id=None):
        report = await self.status()
        if not confirmed_installation_id or confirmed_installation_id != report.get(
            "installationId"
        ):
            raise DomainError(
                "confirmation_required", "Exact installation confirmation required", 409
            )
        self.events.record(
            "app.uninstall_requested", self.app_id, "Runtime-only removal requested; data preserved"
        )
        return await self.client_factory(self.host_id).request(
            "POST",
            self.definition.agent_prefix + "/uninstall",
            {"confirmedInstallationId": confirmed_installation_id},
        )
