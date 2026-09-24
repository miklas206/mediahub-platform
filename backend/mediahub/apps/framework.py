from typing import Protocol

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from sqlalchemy import select

from mediahub.apps.manifest import Manifest, parse_manifest
from mediahub.contracts import Health, HealthCheck
from mediahub.db import InstalledApp
from mediahub.errors import DomainError


class AppAdapter(Protocol):
    async def install(self): ...
    async def uninstall(self): ...
    async def start(self): ...
    async def stop(self): ...
    async def restart(self): ...
    async def update(self, version: str): ...
    async def status(self): ...
    async def health(self): ...
    async def logs(self): ...
    async def configure(self, settings: dict): ...
    async def updateCheck(self): ...


class Registry:
    def __init__(self):
        self.manifests: dict[str, Manifest] = {}

    def register(self, manifest: Manifest):
        if manifest.id in self.manifests:
            raise DomainError("duplicate_app", "App identifier is already registered")
        if Version("0.1.0.dev0") not in SpecifierSet(manifest.coreCompatibility):
            raise DomainError("incompatible_core", "App is incompatible with this Core version")
        self.manifests[manifest.id] = manifest

    def validate_dependencies(self):
        visited, active = set(), set()

        def visit(package_id):
            if package_id in active:
                raise DomainError("dependency_cycle", "App dependencies contain a cycle")
            if package_id in visited:
                return
            active.add(package_id)
            for dep in self.manifests[package_id].dependencies:
                target = self.manifests.get(dep.id)
                if target is None or Version(target.version) not in SpecifierSet(dep.version):
                    raise DomainError(
                        "missing_dependency", "A required app dependency is unavailable"
                    )
                visit(dep.id)
            active.remove(package_id)
            visited.add(package_id)

        for package_id in self.manifests:
            visit(package_id)


class MockAdapter:
    """Database-only demonstration. No subprocess, Docker or network operations."""

    def __init__(self, sessions, app_id, events):
        self.sessions, self.app_id, self.events = sessions, app_id, events

    async def _state(self, state):
        with self.sessions.begin() as db:
            app = db.get(InstalledApp, self.app_id)
            app.state = state
        self.events.record("app.health.changed", self.app_id, f"Mock app is {state}")
        return await self.status()

    async def install(self):
        return await self._state("stopped")

    async def uninstall(self):
        return await self._state("uninstalled")

    async def start(self):
        return await self._state("running")

    async def stop(self):
        return await self._state("stopped")

    async def restart(self):
        return await self._state("running")

    async def update(self, version):
        raise DomainError("not_implemented", "Mock updates are not supported in Phase 1", 501)

    async def configure(self, settings):
        if settings:
            raise DomainError("invalid_settings", "The mock app has no configurable settings")
        return {}

    async def status(self):
        with self.sessions() as db:
            return db.get(InstalledApp, self.app_id).state

    async def health(self):
        state = await self.status()
        status = "healthy" if state == "running" else "unknown"
        return Health(
            status=status,
            summary=f"Mock adapter: {state}",
            checks=[
                HealthCheck(
                    name="adapter", status=status, message="Database-only test app; no real service"
                )
            ],
        )

    async def logs(self):
        return []

    async def updateCheck(self):
        return {"supported": False, "reason": "Mock app has no update provider"}


class AppManager:
    def __init__(self, sessions, events, config):
        self.sessions, self.events, self.config = sessions, events, config
        self.registry = Registry()
        self.adapters: dict[str, AppAdapter] = {}

    def initialize(self):
        if not (self.config.dev_mode and self.config.mock_app):
            return
        manifest = parse_manifest(self.config.manifest_dir / "mock" / "manifest.yaml")
        self.registry.register(manifest)
        self.registry.validate_dependencies()
        created = False
        with self.sessions.begin() as db:
            app = db.scalar(select(InstalledApp).where(InstalledApp.package_id == manifest.id))
            if app is None:
                app = InstalledApp(
                    package_id=manifest.id,
                    name=manifest.name,
                    version=manifest.version,
                    state="running",
                    is_mock=True,
                )
                db.add(app)
                db.flush()
                created = True
            app_id = app.id
        self.adapters[app_id] = MockAdapter(self.sessions, app_id, self.events)
        if created:
            self.events.record(
                "app.registered", app_id, "Mock app registered; no real service attached"
            )

    def get(self, app_id):
        with self.sessions() as db:
            app = db.get(InstalledApp, app_id)
            if app is None:
                raise DomainError("app_not_found", "App not found", 404)
            return {
                "id": app.id,
                "packageId": app.package_id,
                "name": app.name,
                "version": app.version,
                "state": app.state,
                "isMock": app.is_mock,
                "detailPath": f"/apps/{app.id}"
                if hasattr(self.adapters.get(app.id), "definition")
                else None,
            }

    def list(self):
        with self.sessions() as db:
            query = select(InstalledApp.id)
            if not (self.config.dev_mode and self.config.mock_app):
                query = query.where(InstalledApp.is_mock.is_(False))
            ids = db.scalars(query).all()
        return [self.get(app_id) for app_id in ids]

    def adapter(self, app_id):
        self.get(app_id)
        if app_id not in self.adapters:
            raise DomainError("adapter_unavailable", "App adapter is unavailable", 503)
        return self.adapters[app_id]

    async def health(self, app_id):
        return await self.adapter(app_id).health()

    async def action(self, app_id, action):
        adapter = self.adapter(app_id)
        if hasattr(adapter, "definition"):
            return await adapter.action(action)
        if action not in {"start", "stop", "restart"}:
            raise DomainError("unsupported_action", "This operation is not available in Phase 1")
        return await getattr(adapter, action)()
