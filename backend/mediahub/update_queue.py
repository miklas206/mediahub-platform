"""Persistent update queue owned by Core, never by a browser connection."""

import asyncio
import time
from uuid import UUID

from sqlalchemy import select

from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.fjordhub_deploy import clean_line

KEY = "updates.queue"
ACTIVE = {"running", "downloading", "staged", "building", "installing", "verifying", "rolling_back"}
FAILED = {"failed", "rolled_back", "interrupted", "invalid", "unavailable", "idle"}


class UpdateQueue:
    def __init__(self, svc):
        self.svc = svc
        self.task = None
        self.lock = asyncio.Lock()

    def status(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            return dict(row.value) if row else {"state": "idle", "items": [], "logs": []}

    def save(self, job, message=None):
        if message:
            job["message"] = clean_line(message, "")
            if not job["logs"] or job["logs"][-1] != job["message"]:
                job["logs"] = (job["logs"] + [job["message"]])[-200:]
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                row.value = dict(job)
            else:
                db.add(Setting(key=KEY, value=dict(job)))

    async def start(self, identifiers, request_id):
        request_id = str(UUID(str(request_id)))
        async with self.lock:
            previous = self.status()
            if previous.get("operationId") == request_id:
                return previous
            if previous["state"] == "running" or (self.task and not self.task.done()):
                raise DomainError("update_queue_busy", "An update queue is already running", 409)
            available = {
                item["id"]: item
                for item in self.svc.updates.summary()["items"]
                if item.get("updateAvailable")
            }
            items = []
            for identifier in dict.fromkeys(identifiers):
                item = available.get(identifier)
                if not item:
                    raise DomainError("update_not_available", "Check available updates again", 409)
                kind = {"mediahub-core": "core", "seedbox-agent": "agent"}.get(identifier)
                if kind is None:
                    app = self.svc.apps.get(identifier)
                    if app["isMock"] or app["packageId"] != "org.mediahub.plex":
                        raise DomainError(
                            "manual_update_required", "This app requires a manual update", 409
                        )
                    kind = "plex"
                items.append(
                    {"id": identifier, "name": item["name"], "kind": kind, "state": "pending"}
                )
            if not items:
                raise DomainError("update_not_available", "No automatic updates are available", 409)
            items.sort(key=lambda item: item["kind"] == "core")
            job = {
                "operationId": request_id,
                "state": "running",
                "items": items,
                "logs": [],
                "progress": 0,
                "coreUpdated": False,
            }
            self.save(job, "Updates continue on the server. You can leave or close this page.")
            self.task = asyncio.create_task(self.run(job))
            return job

    def resume(self):
        job = self.status()
        if job["state"] == "running":
            self.task = asyncio.create_task(self.run(job, recovering=True))

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def check(self, item):
        if item["kind"] == "agent":
            result = await self.svc.agent_updates.check()
            if result.get("updateAvailable") and not result.get("installReady"):
                raise DomainError(
                    "agent_ssh_required", "Prepare SSH access for the Seedbox Agent first", 409
                )
            return result
        if item["kind"] == "core":
            return await self.svc.updates.check_platform()
        return await self.svc.apps.adapter(item["id"]).updateCheck()

    async def operation(self, item):
        if item["kind"] == "agent":
            return self.svc.agent_updates.operation()
        if item["kind"] == "core":
            return self.svc.platform_update.status()
        return (await self.svc.apps.adapter(item["id"]).status()).get("operation", {})

    async def launch(self, item, checked):
        if item["kind"] == "agent":
            return await self.svc.agent_updates.start()
        if item["kind"] == "core":
            return await self.svc.platform_update.install(checked)
        adapter = self.svc.apps.adapter(item["id"])
        client = adapter.client_factory(adapter.host_id)
        if not client.config.agent_url.startswith("https://"):
            raise DomainError("agent_tls_required", "Plex requires a trusted HTTPS Agent", 409)
        return await client.request("POST", "/v1/plex/update")

    async def run(self, job, recovering=False):
        item = None
        try:
            for index, item in enumerate(job["items"]):
                if item["state"] == "complete":
                    continue
                if recovering and item["state"] in {"starting", "waiting"}:
                    # Never repeat an install whose acknowledgement may have been lost.
                    current = await self.operation(item)
                    actual = current.get("operationId")
                    expected = item.get("operationId")
                    if (
                        not actual
                        or (expected and actual != expected)
                        or (not expected and actual == item.get("previousOperationId"))
                    ):
                        raise DomainError(
                            "update_uncertain",
                            "Core restarted during an update; inspect the component before retrying",
                            409,
                        )
                    item.update(state="waiting", operationId=actual)
                    self.save(job, "Reconnected to the existing server update")
                if item["state"] == "pending":
                    checked = await self.check(item)
                    available = checked.get("updateAvailable", bool(checked.get("releaseVersions")))
                    if checked.get("supported") is False:
                        raise DomainError(
                            "update_unverified", "This update could not be verified", 409
                        )
                    if not available:
                        item["state"] = "complete"
                        self.save(job, item["name"] + ": already up to date; skipped")
                        continue
                    current = await self.operation(item)
                    if current.get("state") in ACTIVE:
                        raise DomainError(
                            "update_busy", "A component update is already running", 409
                        )
                    item.update(
                        state="starting",
                        previousOperationId=current.get("operationId"),
                        deadline=time.time() + 4500,
                    )
                    self.save(job, item["name"] + ": starting update")
                    started = await self.launch(item, checked)
                    item.update(state="waiting", operationId=started.get("operationId"))
                    self.save(job)
                while True:
                    if time.time() >= item["deadline"]:
                        raise DomainError(
                            "update_timeout", "Timed out waiting for verified completion", 409
                        )
                    try:
                        current = await self.operation(item)
                    except DomainError:
                        self.save(
                            job,
                            item["name"]
                            + ": reconnecting; the install request will not be repeated",
                        )
                        await asyncio.sleep(2)
                        continue
                    if (
                        item.get("operationId")
                        and current.get("operationId") != item["operationId"]
                    ):
                        raise DomainError(
                            "update_changed", "The component operation changed; queue stopped", 409
                        )
                    state = current.get("state")
                    progress = current.get(
                        "progress",
                        {"building": 20, "installing": 75, "verifying": 90, "succeeded": 100}.get(
                            state, 10
                        ),
                    )
                    job["progress"] = round(
                        (index + max(0, min(100, progress)) / 100) / len(job["items"]) * 100
                    )
                    for line in current.get("logs") or []:
                        safe = clean_line(str(line), "")
                        if safe and safe not in job["logs"]:
                            job["logs"] = (job["logs"] + [safe])[-200:]
                    self.save(job, item["name"] + ": " + current.get("message", "Updating"))
                    if state == "succeeded":
                        item["state"] = "complete"
                        job["coreUpdated"] |= item["kind"] == "core"
                        self.save(job)
                        break
                    if state in FAILED:
                        raise DomainError(
                            "update_failed", current.get("message", "Update failed"), 409
                        )
                    await asyncio.sleep(2)
            job.update(state="succeeded", progress=100)
            self.save(job, "All queued updates completed. Any manual updates remain separate.")
        except Exception as error:
            if item:
                item["state"] = "error"
            job["state"] = "failed"
            reason = (
                str(error)
                if isinstance(error, DomainError)
                else "Inspect the component status and log before retrying"
            )
            self.save(
                job, "Update queue stopped: " + reason + ". Remaining updates were not started."
            )
        finally:
            if job["state"] != "running":
                try:
                    await self.svc.updates.check_all()
                    job["summaryUpdated"] = True
                    self.save(job)
                except Exception:
                    pass
