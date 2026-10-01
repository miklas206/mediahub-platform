"""Private durable intent, single asynchronous action and bounded recovery worker."""

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.port_forwarding import PortForwarding
from agent.seedbox_driver import ScopedDriver
from agent.seedbox_lifecycle import Lifecycle


class SeedboxControl:
    def __init__(self, installer, socket, devices, status):
        self.installer, self.devices, self.status = installer, devices, status
        self.driver = ScopedDriver(installer, socket, devices)
        self.driver.forwarding = PortForwarding(self.driver)
        self.lifecycle = None
        self.job = None
        self.monitor_task = None
        self.operation = {"state": "idle", "action": None}
        self.events = []
        self.last_component = None
        self.failed_since = None
        self.previous = None

    def initialize(self):
        if self.lifecycle is not None:
            return
        root = Path(self.installer.policy().workRoot)
        self.path = root / "lifecycle.json"
        state = {}
        if self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_size > 262144:
                raise ValueError("Invalid lifecycle state")
            state = json.loads(self.path.read_text())
            if (
                not isinstance(state.get("desiredRunning"), bool)
                or not isinstance(state.get("attempts"), dict)
                or not isinstance(state.get("manualIntervention"), list)
            ):
                raise ValueError("Invalid lifecycle state")
        self.lifecycle = Lifecycle(self.driver, state, self.save, self.emit)
        self.events = state.get("events", [])[-200:]

    def save(self, state):
        temporary = self.path.with_suffix(".pending")
        # A single controller lock owns this path. Reject symlinks rather than following.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(temporary, flags, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, self.path)
        if os.name != "nt":
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def emit(self, kind, severity):
        policy, spec = self.driver.binding()
        self.events.append(
            {
                "timestamp": time.time(),
                "hostId": policy.hostId,
                "app": spec.installationId,
                "severity": severity,
                "type": kind,
                "message": kind.replace(".", ": ").replace("_", " "),
            }
        )
        self.events = self.events[-200:]
        if self.lifecycle:
            self.lifecycle.state["events"] = self.events
            self.persist_events()

    def persist_events(self):
        self.lifecycle.persist()

    def observe(self, report):
        current = {
            "health": report["health"],
            "vpn": report["vpn"]["verified"],
            "ip": report["vpn"]["externalIp"],
            "torrent": report["qBittorrent"]["healthy"],
            "storage": report["storage"]["mounted"],
        }
        previous = self.previous
        self.previous = current
        last_ip = self.lifecycle.state.get("lastVerifiedVpnIp") if self.lifecycle else None
        if current["ip"] and current["ip"] != last_ip and self.lifecycle:
            self.lifecycle.state["lastVerifiedVpnIp"] = current["ip"]
            self.lifecycle.persist()
            if last_ip:
                self.emit("vpn.ip_changed", "info")
        if previous is None:
            return
        if current["health"] != previous["health"]:
            self.emit(
                "seedbox.health_changed", "info" if current["health"] == "healthy" else "warning"
            )
        for key, yes, no in [
            ("vpn", "vpn.connected", "vpn.disconnected"),
            ("torrent", "qbittorrent.started", "qbittorrent.failed"),
            ("storage", "storage.restored", "storage.unavailable"),
        ]:
            if current[key] != previous[key]:
                self.emit(yes if current[key] else no, "info" if current[key] else "error")

    def public(self):
        return {
            "operation": self.operation.copy(),
            "portForwarding": self.driver.forwarding.public(),
            "desiredRunning": self.lifecycle.state["desiredRunning"] if self.lifecycle else False,
            "manualIntervention": list(self.lifecycle.state["manualIntervention"])
            if self.lifecycle
            else [],
            "events": self.events[-50:],
        }

    async def submit(self, action):
        if action not in Lifecycle.actions:
            raise DomainError("unsupported_action", "Unsupported runtime action", 400)
        self.initialize()
        if self.job and not self.job.done():
            raise DomainError("operation_busy", "Another runtime operation is still running", 409)
        self.operation = {"state": "running", "action": action, "startedAt": time.time()}
        self.job = asyncio.create_task(self.perform(action))
        return {"state": "accepted", "action": action}

    async def uninstall(self, installation_id):
        self.initialize()
        _, spec = self.driver.binding()
        if installation_id != spec.installationId:
            raise DomainError(
                "confirmation_required", "Exact installation confirmation required", 409
            )
        if self.job and not self.job.done():
            raise DomainError("operation_busy", "Another runtime operation is still running", 409)
        self.operation = {"state": "running", "action": "remove-runtime", "startedAt": time.time()}
        self.job = asyncio.create_task(self.remove_runtime())
        return {"state": "accepted", "dataPreserved": True}

    async def install(self, request):
        raise DomainError(
            "wizard_required",
            "Use the resumable installation wizard or explicit runtime adoption",
            409,
        )

    async def remove_runtime(self):
        try:
            await self.lifecycle.action("stop")
            async with self.lifecycle.lock:
                await self.driver.remove_runtime()
                root = Path(self.installer.policy().workRoot)
                ledger = root / "install-transaction.json"
                if ledger.exists():
                    save_json(
                        ledger,
                        {"state": "NotInstalled", "steps": [], "attempt": 0, "dataPreserved": True},
                    )
                ownership = root / "install-ownership.json"
                if ownership.exists():
                    save_json(ownership, {**read_json(ownership), "status": "removed"})
                wizard = root / "wizard.json"
                if wizard.exists():
                    draft = read_json(wizard)
                    draft.update(step=0, revision=draft["revision"] + 1, preflight=None)
                    save_json(wizard, draft)
                self.emit("seedbox.runtime_removed", "info")
            self.operation.update(
                state="succeeded",
                message="Runtime removed; data, configuration and credentials preserved",
            )
        except Exception:
            self.operation.update(
                state="failed", message="Runtime removal stopped; persistent data was not deleted"
            )
        finally:
            self.status.cached = None
            self.operation["finishedAt"] = time.time()

    async def perform(self, action):
        try:
            await self.lifecycle.action(action)
            self.operation.update(state="succeeded", message="Runtime action verified")
        except Exception:
            self.operation.update(
                state="failed", message="Safety checks failed; inspect health and events"
            )
        finally:
            self.operation["finishedAt"] = time.time()
            self.status.cached = None

    async def restart_after_update(self):
        commit = os.environ.get("MEDIAHUB_SOURCE_COMMIT", "")
        if not commit:
            return
        try:
            self.initialize()
            self.driver.binding()  # No installed runtime: nothing to restart.
            if self.lifecycle.state.get("runtimeAgentCommit") == commit:
                return
            # Record the attempt first so a crash cannot cause a restart loop.
            self.lifecycle.state["runtimeAgentCommit"] = commit
            self.lifecycle.persist()
            if (
                not self.lifecycle.state["desiredRunning"]
                or self.lifecycle.state["manualIntervention"]
            ):
                return
            self.operation = {
                "state": "running",
                "action": "post-update-restart",
                "message": "Restarting VPN and qBittorrent after Agent update",
                "startedAt": time.time(),
            }
            await self.perform("restart")
            self.emit(
                "seedbox.post_update_restart_" + self.operation["state"],
                "info" if self.operation["state"] == "succeeded" else "error",
            )
        except FileNotFoundError:
            return
        except Exception:
            self.operation = {
                "state": "failed",
                "action": "post-update-restart",
                "message": "Post-update restart could not be verified; inspect Seedbox status",
            }

    async def monitor(self):
        while True:
            await asyncio.sleep(10)
            try:
                self.initialize()
                if (
                    self.lifecycle.lock.locked()
                    or (self.job and not self.job.done())
                    or not self.lifecycle.state["desiredRunning"]
                ):
                    continue
                report = await self.status.report(self.devices())
                self.observe(report)
                if report["vpn"]["verified"] and report["qBittorrent"]["healthy"]:
                    async with self.lifecycle.lock:
                        await self.driver.forwarding.renew()
                else:
                    self.driver.forwarding.invalidate()
                if report["health"] == "healthy":
                    self.lifecycle.observed_healthy()
                    self.failed_since = None
                    self.last_component = None
                    continue
                component = (
                    "storage"
                    if not report["storage"]["mounted"] or report["storage"]["appWritable"] is False
                    else "vpn"
                    if not report["vpn"]["verified"]
                    else "qbittorrent"
                )
                if component != self.last_component:
                    self.last_component, self.failed_since = component, time.monotonic()
                # Stop qbit promptly on storage failure. For VPN failure the network kill
                # switch already blocks traffic; 75s backoff allows stable fault diagnosis.
                if component != "storage" and time.monotonic() - self.failed_since < 75:
                    continue
                result = await self.lifecycle.recover(component)
                self.status.cached = None
                self.operation = {
                    "state": result,
                    "action": "automatic-recovery",
                    "finishedAt": time.time(),
                }
                if result == "healthy":
                    self.failed_since = None
                    self.last_component = None
            except Exception:
                # No raw exception output: may contain API cookies or Docker secrets.
                self.operation = {
                    "state": "failed",
                    "action": "automatic-recovery",
                    "message": "Runtime guard unavailable; operator inspection required",
                }

    async def close(self):
        for task in (self.monitor_task, self.job):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
