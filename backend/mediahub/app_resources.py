"""App-scoped resource collection, preferences and human-approved changes."""

import asyncio
import time

from agent.resource_control import DockerResources, metrics_of
from mediahub.errors import DomainError
from mediahub.managed_apps import ManagedAdapter
from mediahub.resource_history import ResourceHistory


class AppResources:
    def __init__(self, svc):
        self.svc = svc
        self.history = ResourceHistory(svc.config.data_dir)
        self.cache = {}
        self.shared = []
        self.shared_at = 0
        self.lock = asyncio.Lock()
        self.local = DockerResources(
            svc.managed_apps.docker, self.resolve_local, self.persist_local, svc.config.data_dir
        )

    async def resolve_local(self, package):
        manager = self.svc.managed_apps
        if package not in manager.policy:
            raise DomainError(
                "resources_unavailable",
                "An approved local app installation is required for resource control.",
                409,
            )
        targets = []
        rows = await manager.containers(package)
        for summary in rows:
            labels = summary["Config"]["Labels"]
            service = labels.get("com.docker.compose.service")
            component = None
            if labels.get("com.docker.compose.project") == manager.policy[package].project:
                component = (
                    {"app": "app", "sso-proxy": "proxy"}.get(service)
                    if package.endswith("mediavpn")
                    else {"app": "app", "qbittorrent": "client"}.get(service)
                )
            elif (
                package.endswith("mediaseed")
                and labels.get("org.mediahub.mediavpn.seedbox") == "mediaseed"
            ):
                component = "client"
            if component:
                inspected = await manager.docker("GET", "/containers/" + summary["Id"] + "/json")
                if inspected.get("Config", {}).get("Labels") != labels:
                    raise DomainError(
                        "resources_stale", "App ownership changed during resource discovery.", 409
                    )
                targets.append({"id": summary["Id"], "component": component, "inspect": inspected})
        components = {r["component"] for r in targets}
        expected = {"app", "proxy"} if package.endswith("mediavpn") else {"app", "client"}
        if components != expected:
            raise DomainError(
                "resources_unavailable", "Required app resource components are unavailable.", 409
            )
        if any(
            sum(
                r["inspect"]["State"].get("Running", False)
                for r in targets
                if r["component"] == part
            )
            > 1
            for part in components
        ):
            raise DomainError(
                "resources_ambiguous",
                "Multiple running containers claim the same app component. Resolve ownership before changing limits.",
                409,
            )
        editable, reason = True, None
        if package.endswith("mediaseed"):
            vpn = await manager.containers("org.mediahub.mediavpn")
            app = next(
                (
                    row
                    for row in vpn
                    if row["Config"]["Labels"].get("com.docker.compose.service") == "app"
                ),
                None,
            )
            editable = bool(
                app and app["Config"]["Labels"].get("org.mediahub.resources.client-limits") == "1"
            )
            if not editable:
                reason = (
                    "Update MediaVPN to enable persistent resource limits for the torrent client."
                )
        return {
            "installationId": manager.policy[package].installationId,
            "targets": targets,
            "editable": editable,
            "reason": reason,
            "sharedExcluded": True,
        }

    async def persist_local(self, package, parts):
        await self.svc.app_dependencies._run(
            update={"kind": package.rsplit(".", 1)[-1], "resources": parts}
        )
        if self.svc.app_dependencies.message:
            raise DomainError(
                "resources_persist_failed",
                "App resource configuration could not be saved. Inspect app preparation before retrying.",
                409,
            )

        from agent.install_files import read_json, save_json

        path = self.svc.config.data_dir / "app-resource-limits.json"
        saved = read_json(path) if path.is_file() else {}
        saved[package] = {
            "installationId": self.svc.managed_apps.policy[package].installationId,
            "components": parts,
        }
        save_json(path, saved)

    def backend(self, app):
        adapter = self.svc.apps.adapter(app["id"])
        if isinstance(adapter, ManagedAdapter):
            return self.local, None
        if hasattr(adapter, "client_factory") and app["packageId"].startswith("org.mediahub."):
            client = adapter.client_factory(adapter.host_id)
            if not client.trusted_transport:
                raise DomainError(
                    "resources_https_required",
                    "Resource control requires a trusted HTTPS Agent.",
                    409,
                )
            return None, client
        raise DomainError(
            "resources_unavailable",
            "Resource telemetry requires an owned Docker runtime or an updated paired Agent.",
            409,
        )

    async def observe(self, app):
        local, client = self.backend(app)
        if local:
            return await local.observe(app["packageId"])
        try:
            return await client.request(
                "GET", "/v1/apps/" + app["packageId"].removeprefix("org.mediahub.") + "/resources"
            )
        except DomainError as error:
            if error.status == 404:
                raise DomainError(
                    "resources_agent_upgrade",
                    "Update the paired Agent to enable resource telemetry and limits.",
                    409,
                ) from None
            raise

    def row(self, app):
        package = app["packageId"]
        raw = self.cache.get(app["id"])
        if not raw or abs(time.time() - raw.get("sampledAt", 0)) > 90 or not raw.get("available"):
            return {
                "id": app["id"],
                "packageId": package,
                "name": app["name"],
                "available": False,
                "editable": False,
                "reason": raw.get("reason") if raw else "Collecting app resource measurements.",
                "recommendationsEnabled": self.history.enabled(package),
                "recommendations": [],
            }
        return {
            "id": app["id"],
            "packageId": package,
            "name": app["name"],
            **self.history.decorate(package, raw),
        }

    def summary(self):
        def local_app(app):
            adapter = self.svc.apps.adapter(app["id"])
            return isinstance(adapter, ManagedAdapter) or (
                hasattr(adapter, "client_factory") and getattr(adapter, "host_id", None) == "local"
            )

        return {
            "scope": "local-host",
            "items": [
                self.row(app)
                for app in self.svc.apps.list()
                if not app.get("isMock") and local_app(app)
            ],
            "sampleIntervalSeconds": 60,
            "reductionWindowDays": 7,
            "shared": self.shared if time.time() - self.shared_at <= 90 else [],
        }

    async def collect_app(self, app):
        try:
            sample = await asyncio.wait_for(self.observe(app), 20)
            if (
                not isinstance(sample, dict)
                or not sample.get("installationId")
                or not sample.get("limits")
            ):
                raise DomainError(
                    "resources_invalid",
                    "The runtime returned incomplete resource measurements.",
                    503,
                )
            self.cache[app["id"]] = sample
            self.history.record(app["packageId"], sample)
            row = self.row(app)
            advice = row["recommendations"]
            if self.history.should_notify(app["packageId"], advice):
                self.svc.events.read_notifications(
                    event_type="resources.recommended", source="resources:" + app["id"]
                )
                self.svc.events.record(
                    "resources.recommended",
                    "resources:" + app["id"],
                    "Resource recommendations are available for "
                    + app["name"]
                    + ". Review and approve them in Overview.",
                    notify=True,
                )
            elif not advice:
                self.svc.events.read_notifications(
                    event_type="resources.recommended", source="resources:" + app["id"]
                )
        except (DomainError, OSError, ValueError, KeyError, TypeError, TimeoutError) as error:
            self.cache[app["id"]] = {
                "available": False,
                "sampledAt": time.time(),
                "reason": error.message
                if isinstance(error, DomainError)
                else "App resource measurements are temporarily unavailable.",
            }

    async def collect_shared(self):
        self.shared_at = time.time()
        manager = self.svc.managed_apps
        groups = {"MediaHub and support services": [], "Shared VPN infrastructure": []}
        try:
            summaries = await manager.docker("GET", "/containers/json?all=false")
            selected = {}
            for row in summaries:
                labels = row.get("Labels") or {}
                project = labels.get("com.docker.compose.project")
                service = labels.get("com.docker.compose.service")
                name = (row.get("Names") or [""])[0].lstrip("/")
                group = label = None
                if project == "mediahub-platform" and service in {"core", "agent", "proxy"}:
                    group = "MediaHub and support services"
                    label = {
                        "core": "MediaHub Core",
                        "agent": "MediaHub Agent",
                        "proxy": "HTTPS gateway",
                    }[service]
                elif project == "mediahub-host-metrics" and service == "sampler":
                    group, label = "MediaHub and support services", "Host resource sampler"
                elif (
                    "org.mediahub.mediavpn" in manager.policy
                    and not labels.get("org.mediahub.mediavpn.seedbox")
                    and not (
                        project == manager.policy["org.mediahub.mediavpn"].project
                        and service in {"app", "sso-proxy"}
                    )
                ):
                    if labels.get("org.mediahub.vpn.relay"):
                        group, label = "Shared VPN infrastructure", "VPN app routing"
                    elif labels.get("org.mediahub.mediavpn.owner") == "mediavpn":
                        group = "Shared VPN infrastructure"
                        label = {
                            "mediavpn-web": "Web gateway",
                            "mediavpn-shared-gateway": "VPN gateway",
                            "mediavpn-torrent-lease": "Torrent port forwarding",
                            "mediavpn-plex-lease": "Plex port forwarding",
                        }.get(name, "VPN connection")
                if group:
                    selected[row["Id"]] = (group, label)
            slots = asyncio.Semaphore(4)

            async def measure(identifier, group, label):
                async with slots:
                    metrics = metrics_of(
                        await manager.docker(
                            "GET", "/containers/" + identifier + "/stats?stream=false"
                        )
                    )
                groups[group].append(
                    {
                        "name": label,
                        "memoryBytes": metrics["memoryBytes"],
                        "cpuCores": metrics["cpuCores"],
                    }
                )

            await asyncio.gather(
                *(
                    measure(identifier, group, label)
                    for identifier, (group, label) in selected.items()
                )
            )
            self.shared = [
                {
                    "name": name,
                    "components": components,
                    "memoryBytes": sum(row["memoryBytes"] for row in components)
                    if all(row["memoryBytes"] is not None for row in components)
                    else None,
                    "cpuCores": sum(row["cpuCores"] for row in components)
                    if all(row["cpuCores"] is not None for row in components)
                    else None,
                }
                for name, components in groups.items()
                if components
            ]
        except (DomainError, OSError, ValueError, KeyError, TypeError):
            self.shared = [
                {
                    "name": "Local infrastructure measurements unavailable",
                    "memoryBytes": None,
                    "cpuCores": None,
                    "components": [],
                }
            ]

    async def poll(self):
        while True:
            async with self.lock:
                slots = asyncio.Semaphore(4)

                async def collect(app):
                    async with slots:
                        await self.collect_app(app)

                await asyncio.gather(
                    *(collect(app) for app in self.svc.apps.list() if not app.get("isMock"))
                )
                await self.collect_shared()
            await asyncio.sleep(60)

    def preference(self, app, enabled):
        self.history.preference(app["packageId"], enabled)
        if not enabled:
            self.svc.events.read_notifications(
                event_type="resources.recommended", source="resources:" + app["id"]
            )
        return self.row(app)

    async def change(self, app, change, recommendation_id=None):
        async with self.lock:
            if any(
                key != app["id"]
                and row.get("operation", {}).get("state") in {"interrupted", "recovery_failed"}
                for key, row in self.cache.items()
                if row.get("operation")
            ):
                raise DomainError(
                    "resources_recovery_pending",
                    "Another app has an interrupted resource change. Resolve that app first.",
                    409,
                )
            if recommendation_id:
                fresh = await self.observe(app)
                row = self.history.decorate(app["packageId"], fresh)
                advice = next(
                    (item for item in row["recommendations"] if item["id"] == recommendation_id),
                    None,
                )
                if not advice or fresh["revision"] != change.revision:
                    raise DomainError(
                        "resources_recommendation_stale",
                        "The recommendation changed or was disabled. Refresh Overview before approving.",
                        409,
                    )
                expected = {**fresh["limits"], advice["metric"]: advice["proposed"]}
                if change.model_dump(include={"memoryBytes", "cpuCores"}) != expected:
                    raise DomainError(
                        "resources_recommendation_stale",
                        "The proposed limits no longer match this recommendation.",
                        409,
                    )
            local, client = self.backend(app)
            if local:
                self.svc.app_dependencies.require_ready()
                if self.svc.managed_apps.lock.locked():
                    raise DomainError(
                        "resources_busy",
                        "An app operation is running. Retry resource changes afterwards.",
                        409,
                    )
                async with self.svc.managed_apps.lock:
                    result = await local.change(app["packageId"], change)
            else:
                result = await client.request(
                    "PUT",
                    "/v1/apps/" + app["packageId"].removeprefix("org.mediahub.") + "/resources",
                    change.model_dump(),
                )
            self.cache[app["id"]] = result
            self.history.record(app["packageId"], result)
            self.svc.events.read_notifications(
                event_type="resources.recommended", source="resources:" + app["id"]
            )
            self.svc.events.record(
                "resources.changed",
                "resources:" + app["id"],
                "Verified resource limits saved for " + app["name"],
            )
            return self.row(app)
