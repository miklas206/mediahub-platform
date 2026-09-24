"""Secret-free, bounded lease lifecycle. Validity is monotonic and process-local."""

import asyncio
import time


class PortForwarding:
    def __init__(self, driver, clock=time.monotonic, wall=time.time):
        self.driver, self.clock, self.wall = driver, clock, wall
        self.lock = asyncio.Lock()
        self.deadline = 0
        self.next_attempt = 0
        self.failures = 0
        self.identity = None
        self.allowed_port = None
        self.state = {
            "status": "not_checked",
            "currentPort": None,
            "lastRenewed": None,
            "expiresAt": None,
            "qBittorrentVerified": False,
        }

    def public(self):
        result = self.state.copy()
        if result["status"] == "healthy" and self.clock() >= self.deadline:
            result.update(status="degraded", qBittorrentVerified=False)
        return result

    def invalidate(self):
        self.deadline = self.next_attempt = 0
        self.identity = None
        self.state.update(
            status="degraded", currentPort=None, expiresAt=None, qBittorrentVerified=False
        )

    async def renew(self, *, apply=True):
        async with self.lock:
            now = self.clock()
            if now < self.next_attempt:
                return self.public()
            try:
                identity = await self.driver.port_forward_identity()
                started = self.clock()
                lease = await self.driver.request_forwarded_port()
                port = lease["port"]
                remaining = lease["remainingSeconds"] - (self.clock() - started)
                if type(port) is not int or not 1024 <= port <= 65535 or remaining < 15:
                    raise ValueError("Invalid lease")
                if await self.driver.port_forward_identity() != identity:
                    raise ValueError("Tunnel changed during lease request")
                # Only tunnel ingress for this torrent port; never publish host ports.
                await self.driver.allow_forwarded_port(port, self.allowed_port)
                self.allowed_port = port
                self.identity = identity
                self.deadline = self.clock() + remaining
                self.state.update(
                    currentPort=port,
                    lastRenewed=self.wall(),
                    expiresAt=self.wall() + remaining,
                    status="pending_client",
                    qBittorrentVerified=False,
                )
                if apply:
                    await self.driver.apply_forwarded_port(port)
                    self.state.update(status="healthy", qBittorrentVerified=True)
                self.failures = 0
                self.next_attempt = self.clock() + min(30, remaining / 2)
            except Exception:
                self.failures += 1
                self.state.update(status="degraded", qBittorrentVerified=False)
                self.next_attempt = self.clock() + min(120, 5 * 2 ** min(self.failures - 1, 5))
            return self.public()

    async def apply_current(self):
        async with self.lock:
            try:
                if (
                    self.clock() >= self.deadline
                    or self.identity != await self.driver.port_forward_identity()
                ):
                    raise ValueError("Lease not current")
                await self.driver.apply_forwarded_port(self.state["currentPort"])
                self.state.update(status="healthy", qBittorrentVerified=True)
            except Exception:
                self.state.update(status="degraded", qBittorrentVerified=False)
            return self.public()
