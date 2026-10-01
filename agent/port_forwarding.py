"""Secret-free, bounded lease lifecycle. Validity is monotonic and process-local."""

import asyncio
import time

from agent.port_listener import ListeningPortError


class PortLeaseError(ValueError):
    MESSAGES = {
        "natpmp_refused": "Proton refused the port request. Check NAT-PMP on the WireGuard profile and P2P server.",
        "natpmp_timeout": "Proton did not answer the port request through the VPN tunnel.",
    }

    def __init__(self, reason):
        super().__init__(self.MESSAGES.get(reason, "Proton port lease could not be verified"))


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
            "listenerVerified": False,
            "listenerCheckSupported": True,
            "lastError": None,
        }

    def public(self):
        result = self.state.copy()
        if result["status"] == "healthy" and self.clock() >= self.deadline:
            result.update(status="degraded", qBittorrentVerified=False, listenerVerified=False)
        return result

    def invalidate(self):
        self.deadline = self.next_attempt = 0
        self.identity = None
        self.state.update(
            status="degraded",
            currentPort=None,
            expiresAt=None,
            qBittorrentVerified=False,
            listenerVerified=False,
            lastError=None,
        )

    async def renew(self, *, apply=True):
        async with self.lock:
            now = self.clock()
            if now < self.next_attempt:
                return self.public()
            stage = "VPN identity"
            try:
                identity = await self.driver.port_forward_identity()
                started = self.clock()
                stage = "Proton port lease"
                lease = await self.driver.request_forwarded_port()
                port = lease["port"]
                remaining = lease["remainingSeconds"] - (self.clock() - started)
                if type(port) is not int or not 1024 <= port <= 65535 or remaining < 15:
                    raise ValueError("Invalid lease")
                if await self.driver.port_forward_identity() != identity:
                    raise ValueError("Tunnel changed during lease request")
                # Only tunnel ingress for this torrent port; never publish host ports.
                stage = "VPN firewall"
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
                    listenerVerified=False,
                )
                if apply:
                    stage = "qBittorrent port and listening socket"
                    listening = await self.driver.apply_forwarded_port(port)
                    self.state.update(
                        status="healthy",
                        qBittorrentVerified=True,
                        listenerVerified=bool(listening),
                        lastError=None,
                    )
                self.failures = 0
                self.next_attempt = self.clock() + min(30, remaining / 2)
            except Exception as error:
                self.state["lastError"] = (
                    "qBittorrent port is configured, but no listening socket was found"
                    if isinstance(error, ListeningPortError)
                    else str(error)
                    if isinstance(error, PortLeaseError)
                    else stage + " could not be verified"
                )
                self.failures += 1
                self.state.update(
                    status="degraded",
                    qBittorrentVerified=isinstance(error, ListeningPortError),
                    listenerVerified=False,
                )
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
                listening = await self.driver.apply_forwarded_port(self.state["currentPort"])
                self.state.update(
                    status="healthy",
                    qBittorrentVerified=True,
                    listenerVerified=bool(listening),
                    lastError=None,
                )
            except Exception:
                self.state.update(
                    status="degraded",
                    qBittorrentVerified=False,
                    listenerVerified=False,
                    lastError="Current lease or qBittorrent listening socket could not be verified",
                )
            return self.public()
