"""Serialized, bounded orchestration; runtime operations supplied by a scoped driver.

No Docker commands, network addresses or installation-specific IDs belong here.
Persistence is mandatory before an automatic attempt or desired-state transition.
"""

import asyncio
import time
from collections.abc import Callable

from mediahub.errors import DomainError


class Lifecycle:
    actions = frozenset(
        {"start", "stop", "restart", "restart-vpn", "restart-qbittorrent", "test-vpn"}
    )

    def __init__(self, driver, state: dict, save: Callable, emit: Callable, clock=time.time):
        self.driver, self.state, self.save, self.emit, self.clock = driver, state, save, emit, clock
        self.lock = asyncio.Lock()
        self.state.setdefault("desiredRunning", False)
        self.state.setdefault("attempts", {})
        self.state.setdefault("manualIntervention", [])
        self.stable_since = None

    def persist(self):
        self.save(self.state)

    def event(self, kind, severity="info"):
        # Never forward arbitrary driver exceptions or command output to logs.
        self.emit(kind, severity)

    async def gated_start(self, restart_vpn=False):
        # Stop first: no retained namespace or an unverified running qbit.
        await self.driver.stop_torrent()
        self.event("qbittorrent.stopped")
        await self.driver.storage_guard()
        await self.driver.device_guard()
        await self.driver.write_probe()
        await self.driver.start_vpn(restart=restart_vpn)
        vpn_ip = await self.driver.verify_vpn()
        self.event("vpn.connected")
        forwarding = getattr(self.driver, "forwarding", None)
        if forwarding:
            forwarding.invalidate()
            await forwarding.renew(apply=False)
        # Storage can disappear during tunnel establishment. Check again.
        await self.driver.storage_guard()
        await self.driver.device_guard()
        try:
            # A start request may have taken effect even if its response was lost.
            await self.driver.start_torrent()
            await self.driver.verify_torrent(vpn_ip)
            await self.driver.storage_guard()
            if forwarding:
                await forwarding.apply_current()
        except BaseException:
            await self.driver.stop_torrent()
            raise
        self.event("qbittorrent.started")

    async def action(self, action):
        if action not in self.actions:
            raise DomainError("unsupported_action", "Unsupported runtime action", 400)
        async with self.lock:
            if action == "test-vpn":
                await self.driver.verify_vpn()
                return {"state": "verified"}
            if action == "stop":
                # Persist intent before stopping: reboot must not undo an explicit stop.
                self.state["desiredRunning"] = False
                self.persist()
                await self.driver.stop_torrent()
                self.event("qbittorrent.stopped")
                await self.driver.stop_vpn()
                forwarding = getattr(self.driver, "forwarding", None)
                if forwarding:
                    forwarding.invalidate()
                self.event("vpn.disconnected")
                self.event("seedbox.stopped")
                return {"state": "stopped"}
            self.state["desiredRunning"] = True
            self.persist()
            try:
                await self.gated_start(restart_vpn=action in {"restart", "restart-vpn"})
            except Exception:
                self.event("seedbox.start_failed", "error")
                raise DomainError(
                    "startup_blocked", "Runtime checks failed; inspect component health", 409
                ) from None
            # Only a successfully verified manual start clears a manual-intervention latch.
            # A manual action may clear a latch, but never erase recent automatic
            # attempts and thereby exceed the rolling ten-minute budget.
            self.state["manualIntervention"] = []
            self.persist()
            self.event("seedbox.started" if action == "start" else "seedbox.restarted")
            if action == "restart-qbittorrent":
                self.event("qbittorrent.restarted")
            return {"state": "healthy"}

    def reserve_attempt(self, component):
        if component in self.state["manualIntervention"]:
            return False
        now = self.clock()
        history = self.state["attempts"].get(component, [])
        # Clock rollback must not erase attempts and defeat the limit.
        history = [stamp for stamp in history if now - stamp < 600]
        if len(history) >= 3:
            self.state["manualIntervention"].append(component)
            self.persist()
            self.event("recovery.rate_limited", "error")
            return False
        self.state["attempts"][component] = [*history, now]
        self.persist()
        return True

    async def recover(self, component):
        if component not in {"vpn", "qbittorrent", "storage"}:
            raise ValueError("Unknown recovery component")
        async with self.lock:
            if not self.state["desiredRunning"]:
                return "stopped"
            self.stable_since = None
            await self.driver.stop_torrent()
            # Missing storage is a waiting condition, never an instruction to recreate it.
            try:
                await self.driver.storage_guard()
                await self.driver.device_guard()
            except Exception:
                self.event("storage.guard_failed", "error")
                return "waiting-for-storage"
            if not self.reserve_attempt(component):
                return "manual-intervention"
            self.event(component + ".recovery_started", "warning")
            try:
                await self.gated_start(restart_vpn=component == "vpn")
            except Exception:
                self.event(component + ".recovery_failed", "error")
                return "failed"
            self.event(component + ".recovery_succeeded")
            return "healthy"

    def observed_healthy(self):
        now = self.clock()
        if self.stable_since is None or now < self.stable_since:
            self.stable_since = now
        history = self.state["attempts"]
        remaining = {
            component: [stamp for stamp in stamps if now - stamp < 600]
            for component, stamps in history.items()
        }
        remaining = {component: stamps for component, stamps in remaining.items() if stamps}
        if remaining != history:
            self.state["attempts"] = remaining
            self.persist()
