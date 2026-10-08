"""Bounded Core-to-VPN TCP checks. Targets come only from the paired Agent."""

import asyncio
import logging
import time
from ipaddress import ip_address

from sqlalchemy import select

from mediahub.db import Setting


def target(report):
    vpn, lease = report.get("vpn", {}), report.get("portForwarding", {})
    address = ip_address(vpn.get("externalIp") or "")
    port = lease.get("currentPort")
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or not vpn.get("verified")
        or type(port) is not int
        or not 1024 <= port <= 65535
        or lease.get("status") != "healthy"
        or not lease.get("qBittorrentVerified")
        or (lease.get("expiresAt") or 0) <= time.time() + 6
    ):
        raise ValueError("VPN or port lease is not verified")
    return str(address), port


async def tcp_connect(address, port):
    _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), 5)
    writer.close()
    await asyncio.wait_for(writer.wait_closed(), 1)


class SeedboxReachability:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()
        self.failures = 0
        self.state = {
            "status": "unknown",
            "checkedAt": None,
            "message": "Port reachability has not been checked",
            "source": "MediaHub Core",
        }

    def status(self):
        state = dict(self.state)
        if state.get("checkedAt") and time.time() - state["checkedAt"] > 90:
            state.update(
                status="unknown", message="Port check is stale; waiting for a fresh result"
            )
        return state

    async def check(self):
        async with self.lock:
            if self.state.get("checkedAt") and time.time() - self.state["checkedAt"] < 15:
                return self.status()
            result = {
                "status": "unknown",
                "checkedAt": time.time(),
                "source": "MediaHub Core",
                "address": None,
                "port": None,
            }
            try:
                with self.svc.sessions() as db:
                    binding = db.scalar(
                        select(Setting).where(Setting.key == "seedbox_installation")
                    )
                    host = binding.value.get("hostId") if binding else None
                if not host:
                    raise ValueError("No Seedbox is paired")
                client = self.svc.hosts.client(host)
                report = await client.request("GET", "/v1/seedbox/status")
                address, port = target(report)
                result.update(address=address, port=port)
                reachable = True
                try:
                    await tcp_connect(address, port)
                except (OSError, asyncio.TimeoutError):
                    reachable = False
                # Do not attach results to a changed tunnel, port or expired lease.
                fresh = await client.request("GET", "/v1/seedbox/status")
                if target(fresh) != (address, port):
                    raise ValueError("VPN endpoint changed during the check")
                result.update(
                    status="reachable" if reachable else "unreachable",
                    message="TCP connection to the VPN torrent port succeeded from MediaHub Core"
                    if reachable
                    else "TCP connection to the VPN torrent port failed from MediaHub Core. Check the listening socket and VPN firewall; the tracker may also show not connectable",
                )
            except Exception:
                result.update(
                    status="unknown",
                    message="Cannot verify the current VPN endpoint or lease. Check Agent connection, VPN and port diagnostics",
                )
            self.state = result
            self.failures = self.failures + 1 if result["status"] == "unreachable" else 0
            if self.failures == 2:
                self.svc.events.record(
                    "seedbox.port.unreachable",
                    "seedbox",
                    "Torrent port could not be reached from MediaHub Core in two consecutive checks",
                    "warning",
                    notify=True,
                )
            elif result["status"] == "reachable":
                self.svc.events.read_notifications(
                    event_type="seedbox.port.unreachable", source="seedbox"
                )
            return self.status()

    async def poll(self):
        await asyncio.sleep(5)
        while True:
            try:
                await self.check()
            except Exception:
                logging.getLogger("mediahub.port-check").warning(
                    "Port monitoring unavailable; retrying next minute"
                )
            await asyncio.sleep(60)
