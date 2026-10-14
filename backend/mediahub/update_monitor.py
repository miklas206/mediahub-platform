"""Scheduled, read-only release checks with persistent non-secret summaries."""

import asyncio
import copy
import hashlib
import time

from sqlalchemy import select

from mediahub import __version__
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.github_metadata import GitHubMetadata
from mediahub.main_branch_watch import MAIN_CHECK_INTERVAL_SECONDS, MainBranchWatch
from mediahub.platform_source import GitHubSourceProvider
from mediahub.source_git import source_access

STATE_KEY = "update-monitor"


class UpdateMonitor:
    def __init__(self, services):
        self.services = services
        self.lock = asyncio.Lock()
        self.check_task = None
        self.source_access = source_access(getattr(services, "config", None))
        data_dir = getattr(getattr(services, "config", None), "data_dir", None)
        self.github_metadata = GitHubMetadata(
            state_file=data_dir / "github-cooldowns.json" if data_dir else None
        )
        self.main_watch = MainBranchWatch(
            source_access=self.source_access, metadata_cache=self.github_metadata
        )
        self.check_finished_at = 0
        self.metadata_lock = asyncio.Lock()
        self.source_checks = {}

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
        retired = {app["id"] for app in self.services.apps.list()
                   if app.get("packageId") == "org.mediahub.cloudflared"}
        value["items"] = [item for item in value["items"] if item["id"] not in retired]
        value["count"] = sum(bool(item.get("updateAvailable")) for item in value["items"])
        if retired and value.get("lastError") and value["lastError"].startswith("Could not check:"):
            failed = [item["name"] for item in value["items"] if item.get("checkStatus") == "failed"]
            value["lastError"] = "Could not check: " + ", ".join(failed) if failed else None
        for item in value["items"]:
            if item.get("installedVersion") == "managed":
                item["installedVersion"] = None
        value["intervalHours"] = self.services.settings.get().update_check_interval_hours
        value["mainCheckIntervalSeconds"] = (
            MAIN_CHECK_INTERVAL_SECONDS
            if value["intervalHours"] and self.services.settings.get().release_repository
            else 0
        )
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
            "installedVersion": result.get("installedVersion") or (app.get("version") if app.get("version") != "managed" else None),
            "latestVersion": str(latest)[:128] if latest else None,
            "updateAvailable": available,
            "checkStatus": "unsupported"
            if result.get("supported") is False
            else result.get("checkStatus") or ("checked" if latest else "unchecked"),
            "message": str(result.get("message") or result.get("reason") or "Checked")[:200],
            **{
                key: result[key]
                for key in ("checkStatus", "stale", "retryAt", "checkedAt", "errorCode", "bundledVersion", "preparationState")
                if key in result
            },
        }

    @staticmethod
    def _failure(app, error):
        return {
            "id": app["id"],
            "name": app["name"],
            "installedVersion": app.get("version") if app.get("version") != "managed" else None,
            "latestVersion": None,
            "updateAvailable": False,
            "checkStatus": "deferred" if getattr(error, "retry_at", None) else "failed",
            **({"retryAt": error.retry_at} if getattr(error, "retry_at", None) else {}),
            "errorCode": error.code if isinstance(error, DomainError) else "update_check_timeout",
            "message": error.message[:200]
            if isinstance(error, DomainError)
            else "Update check timed out after 20 seconds",
        }

    def _store_results(self, items, error=None):
        previous = self._load()
        failed = [item for item in items if item.get("checkStatus") == "failed"]
        if failed:
            error = "Could not check: " + ", ".join(item["name"] for item in failed)
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
        deferred = any(item.get("checkStatus") == "deferred" for item in items)
        if not signature and not error and not deferred:
            # A successful zero-update result resolves old update alerts. Their
            # Event rows remain in the audit timeline, but they must not keep a
            # stale badge or ask the user to dismiss an already installed release.
            self.services.events.read_notifications(
                event_type="updates.available", source="updates"
            )
        elif signature and signature != previous.get("signature"):
            self.services.events.read_notifications(
                event_type="updates.available", source="updates"
            )
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
        installed = self.services.platform_update.installed_source()
        commit = installed.get("commit") if installed.get("repository") == repository else None
        return await self.source_metadata("pyproject.toml", __version__, commit)

    async def source_metadata(self, project_path, current_version, installed_commit=None):
        """Share short-lived source checks across Core and bundled app cards."""
        repository = self.services.settings.get().release_repository
        token = self.services.release_credentials.token()
        identity = hashlib.sha256((token or "").encode()).digest()
        key = (repository, identity, project_path, current_version, installed_commit)
        async with self.metadata_lock:
            cached = self.source_checks.get(key)
            if cached and time.monotonic() < cached[0]:
                return copy.deepcopy(cached[1])
            result = await GitHubSourceProvider(
                current_version, installed_commit,
                source_access=self.source_access, metadata_cache=self.github_metadata,
                project_path=project_path,
            ).check(repository, token)
            self.source_checks[key] = (time.monotonic() + 60, copy.deepcopy(result))
            while len(self.source_checks) > 16:
                self.source_checks.pop(next(iter(self.source_checks)))
            return result

    async def refresh_managed_versions(self, preparation_state="ready"):
        """Refresh observed versions after preparation, without contacting GitHub."""
        async with self.lock:
            previous = self._load()
            by_id = {item["id"]: item for item in previous["items"]}
            installed = self.services.platform_update.installed_source()
            repository = self.services.settings.get().release_repository
            core = by_id.get("mediahub-core", {})
            same_source = bool(installed.get("repository") == repository and installed.get("commit")
                               and core.get("latestVersion") == installed["commit"]
                               and core.get("checkStatus") == "checked")
            for app in self.services.apps.list():
                if app.get("packageId") not in {"org.mediahub.mediaseed", "org.mediahub.mediavpn"}:
                    continue
                try:
                    adapter = self.services.apps.adapter(app["id"])
                    if not hasattr(adapter, "installed_version"):
                        continue  # SSO-only connected apps do not grant Docker lifecycle access.
                    local = await adapter.installed_version()
                except (DomainError, OSError, ValueError, KeyError):
                    continue
                item = {**by_id.get(app["id"], {"id": app["id"], "name": app["name"], "checkStatus": "unchecked"}),
                        "installedVersion": local["installedVersion"],
                        "bundledVersion": local["bundledVersion"], "preparationState": preparation_state,
                        "updateAvailable": False}
                if same_source:
                    item.update(latestVersion=local["bundledVersion"],
                                checkStatus="checked" if local["installedVersion"] == local["bundledVersion"] else "unchecked",
                                message="This app is updated automatically with MediaHub Core.", stale=False)
                    item.pop("errorCode", None)
                    item.pop("retryAt", None)
                if preparation_state == "failed":
                    item.update(checkStatus="failed", message="Automatic app preparation failed; existing data was retained")
                by_id[app["id"]] = item
            self.check_finished_at = 0
            self._store_results(list(by_id.values()))

    async def record_platform(self, result):
        previous = self._load()
        retained = [item for item in previous["items"] if item.get("id") != "mediahub-core"]
        retained.insert(
            0,
            {
                "id": "mediahub-core",
                "name": "MediaHub Core",
                "checkStatus": "checked"
                if result.get("latestCommit") or result.get("latestVersion")
                else "unchecked",
                "installedVersion": result.get("installedVersion"),
                "checkedAt": time.time(),
                "latestVersion": result.get("latestCommit") or result.get("latestVersion"),
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
        # Refreshes and scheduled checks share the same in-flight result.
        # A disconnected HTTP request must not cancel the server-side check.
        if (
            self.check_task is not None
            and self.check_task.done()
            and not self.check_task.cancelled()
            and self.check_task.exception() is None
            and time.time() < self.check_finished_at + 60
        ):
            return self.check_task.result()
        if self.check_task is None or self.check_task.done():
            self.check_task = asyncio.create_task(self._check_all())
            self.check_task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )
        result = await asyncio.shield(self.check_task)
        self.check_finished_at = time.time()
        return result

    async def _check_all(self):
        async with self.lock:
            items = []
            failures = 0
            try:
                platform = await self.check_platform()
                items.append(
                    {
                        "id": "mediahub-core",
                        "name": "MediaHub Core",
                        "checkStatus": "checked"
                        if platform.get("latestCommit") or platform.get("latestVersion")
                        else "unchecked",
                        "installedVersion": platform.get("installedVersion"),
                        "checkedAt": time.time(),
                        "latestVersion": platform.get("latestCommit")
                        or platform.get("latestVersion"),
                        "updateAvailable": bool(platform.get("updateAvailable")),
                        "message": str(platform.get("message") or "Checked")[:200],
                    }
                )
            except DomainError as error:
                failures += not bool(getattr(error, "retry_at", None))
                failure = self._failure({"id": "mediahub-core", "name": "MediaHub Core"}, error)
                previous = next(
                    (item for item in self._load()["items"] if item.get("id") == "mediahub-core"),
                    {},
                )
                if failure["checkStatus"] == "deferred":
                    failure.update(
                        {
                            key: previous.get(key)
                            for key in (
                                "installedVersion",
                                "latestVersion",
                                "updateAvailable",
                                "checkedAt",
                            )
                        }
                    )
                    failure["stale"] = bool(previous.get("latestVersion"))
                items.append(failure)
            try:
                agent = await self.services.agent_updates.check()
                items.append(
                    self._app_result(
                        {"id": "seedbox-agent", "name": "Seedbox Agent"},
                        {**agent, "latestVersion": agent.get("latestCommit")},
                    )
                )
            except DomainError as error:
                if error.code != "agent_host_required":
                    failures += not bool(getattr(error, "retry_at", None))
                    items.append(
                        self._failure({"id": "seedbox-agent", "name": "Seedbox Agent"}, error)
                    )
            for app in self.services.apps.list():
                if app.get("isMock") or app.get("packageId") == "org.mediahub.cloudflared":
                    continue
                try:
                    result = await asyncio.wait_for(
                        self.services.apps.adapter(app["id"]).updateCheck(), timeout=20
                    )
                    items.append(self._app_result(app, result))
                except (DomainError, asyncio.TimeoutError) as error:
                    failures += not bool(getattr(error, "retry_at", None))
                    items.append(self._failure(app, error))
            self._store_results(
                items,
                "One or more update sources were unavailable" if failures else None,
            )
            return self.summary()

    async def check_main_change(self):
        settings = self.services.settings.get()
        if not settings.update_check_interval_hours:
            return
        if self.check_task and not self.check_task.done():
            return
        commit = await self.main_watch.check(
            settings.release_repository, self.services.release_credentials.token()
        )
        if not commit:
            return
        core = next(
            (item for item in self._load()["items"] if item.get("id") == "mediahub-core"), None
        )
        if core is None or core.get("latestVersion") != commit:
            self.source_checks.clear()
            self.check_finished_at = 0
            await self.check_all()

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
            else:
                try:
                    await self.check_main_change()
                except DomainError:
                    pass
            await asyncio.sleep(60)
