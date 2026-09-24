"""Scheduled, read-only release checks with persistent non-secret summaries."""

import asyncio
import time

from sqlalchemy import select

from mediahub import __version__
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.platform_updates import GitHubReleaseProvider

STATE_KEY = "update-monitor"


class UpdateMonitor:
    def __init__(self, services):
        self.services = services
        self.lock = asyncio.Lock()

    def _load(self):
        with self.services.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == STATE_KEY))
            value = dict(row.value) if row else {}
        return {
            "checkedAt": value.get("checkedAt"),
            "count": int(value.get("count") or 0),
            "items": list(value.get("items") or [])[:50],
            "signature": str(value.get("signature") or "")[:512],
            "lastError": str(value.get("lastError") or "")[:200] or None,
        }

    def _save(self, value):
        stored = {
            "checkedAt": value.get("checkedAt"),
            "count": int(value.get("count") or 0),
            "items": list(value.get("items") or [])[:50],
            "signature": str(value.get("signature") or "")[:512],
            "lastError": str(value.get("lastError") or "")[:200] or None,
        }
        with self.services.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == STATE_KEY))
            if row:
                row.value = stored
            else:
                db.add(Setting(key=STATE_KEY, value=stored))
        return stored

    def summary(self):
        value = self._load()
        value["intervalHours"] = self.services.settings.get().update_check_interval_hours
        value["notifications"] = self.services.events.notifications(limit=10)
        return value

    @staticmethod
    def _app_result(app, result):
        versions = [str(value)[:128] for value in result.get("releaseVersions") or [] if value]
        latest = result.get("latestVersion") or (versions[0] if versions else None)
        available = bool(result.get("updateAvailable", bool(versions)))
        if result.get("supported") is False:
            available = False
        return {
            "id": app["id"],
            "name": app["name"],
            "installedVersion": result.get("installedVersion") or app.get("version"),
            "latestVersion": str(latest)[:128] if latest else None,
            "updateAvailable": available,
            "message": str(result.get("message") or result.get("reason") or "Checked")[:200],
        }

    def _store_results(self, items, error=None):
        previous = self._load()
        available = sorted(
            f"{item['id']}:{item.get('latestVersion') or 'available'}"
            for item in items
            if item.get("updateAvailable")
        )
        signature = "|".join(available)
        saved = self._save(
            {
                "checkedAt": time.time(),
                "count": len(available),
                "items": items,
                "signature": signature,
                "lastError": error,
            }
        )
        if signature and signature != previous.get("signature"):
            count = len(available)
            self.services.events.record(
                "updates.available",
                "updates",
                f"{count} verified update{'s are' if count != 1 else ' is'} available",
                "info",
                notify=True,
            )
        self.services.events.publish("updates.changed", self.summary())
        return saved

    async def check_platform(self):
        repository = self.services.settings.get().release_repository
        return await GitHubReleaseProvider(__version__).check(
            repository, self.services.release_credentials.token()
        )

    async def record_platform(self, result):
        previous = self._load()
        retained = [item for item in previous["items"] if item.get("id") != "mediahub-core"]
        retained.insert(
            0,
            {
                "id": "mediahub-core",
                "name": "MediaHub Core",
                "installedVersion": result.get("installedVersion"),
                "latestVersion": result.get("latestVersion"),
                "updateAvailable": bool(result.get("updateAvailable")),
                "message": str(result.get("message") or "Checked")[:200],
            },
        )
        self._store_results(retained)

    async def record_app(self, app, result):
        previous = self._load()
        retained = [item for item in previous["items"] if item.get("id") != app["id"]]
        retained.append(self._app_result(app, result))
        self._store_results(retained)

    async def check_all(self):
        if self.lock.locked():
            raise DomainError("update_check_busy", "An update check is already running", 409)
        async with self.lock:
            items = []
            failures = 0
            try:
                platform = await self.check_platform()
                items.append(
                    {
                        "id": "mediahub-core",
                        "name": "MediaHub Core",
                        "installedVersion": platform.get("installedVersion"),
                        "latestVersion": platform.get("latestVersion"),
                        "updateAvailable": bool(platform.get("updateAvailable")),
                        "message": str(platform.get("message") or "Checked")[:200],
                    }
                )
            except DomainError:
                failures += 1
            for app in self.services.apps.list():
                if app.get("isMock"):
                    continue
                try:
                    result = await asyncio.wait_for(
                        self.services.apps.adapter(app["id"]).updateCheck(), timeout=20
                    )
                    items.append(self._app_result(app, result))
                except (DomainError, asyncio.TimeoutError):
                    failures += 1
                    items.append(
                        {
                            "id": app["id"],
                            "name": app["name"],
                            "installedVersion": app.get("version"),
                            "latestVersion": None,
                            "updateAvailable": False,
                            "message": "Update source temporarily unavailable",
                        }
                    )
            self._store_results(
                items,
                "One or more update sources were unavailable" if failures else None,
            )
            return self.summary()

    async def poll(self):
        await asyncio.sleep(20)
        while True:
            settings = self.services.settings.get()
            interval = settings.update_check_interval_hours
            state = self._load()
            recorded_core = next(
                (item for item in state["items"] if item.get("id") == "mediahub-core"),
                None,
            )
            version_changed = bool(
                recorded_core and recorded_core.get("installedVersion") != __version__
            )
            due = (
                version_changed
                or not state["checkedAt"]
                or time.time() - state["checkedAt"] >= interval * 3600
            )
            if version_changed or (interval and due):
                try:
                    await self.check_all()
                except DomainError:
                    pass
            await asyncio.sleep(60)
