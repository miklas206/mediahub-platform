"""Bounded, authenticated Agent status forwarding with an explicit public schema."""

import asyncio
import time

from pydantic import BaseModel, ConfigDict, Field


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class VPNStatus(PublicModel):
    verified: bool = False
    externalIp: str | None = None
    provider: str | None = None
    protocol: str | None = None
    connectedSince: str | None = None  # Container start, NOT tunnel uptime.
    lastVerified: float | None = None
    countryCode: str | None = None


class TorrentStatus(PublicModel):
    healthy: bool = False
    version: str | None = None
    running: bool = False
    apiAuthenticated: bool = False
    bindingVerified: bool = False
    namespaceVerified: bool = False
    downloadSpeed: int = 0
    uploadSpeed: int = 0
    torrents: int = 0
    downloading: int = 0
    seeding: int = 0
    paused: int = 0
    errors: int = 0


class PortForwardStatus(PublicModel):
    status: str = "not_checked"
    currentPort: int | None = Field(default=None, ge=1024, le=65535)
    lastRenewed: float | None = None
    expiresAt: float | None = None
    qBittorrentVerified: bool = False
    listenerVerified: bool = False
    listenerCheckSupported: bool = False
    lastError: str | None = None
    plexVerified: bool = False


class StorageStatus(PublicModel):
    mounted: bool = False
    appWritable: bool | None = None
    logicalId: str | None = None
    source: str | None = None
    filesystem: str | None = None
    verifiedAt: float | None = None
    totalBytes: int | None = None
    usedBytes: int | None = None
    freeBytes: int | None = None


class DeviceMount(PublicModel):
    path: str
    readOnly: bool


class Device(PublicModel):
    stableIdentity: str | None = None
    model: str | None = None
    sizeBytes: int | None = None
    connected: bool = False
    mounted: bool = False
    mounts: list[DeviceMount] = Field(default_factory=list)


class DeviceCheck(PublicModel):
    id: str
    connected: bool
    status: str
    message: str


class HostMetrics(PublicModel):
    cpuPercent: float | None = None
    cpuCores: int | None = None
    ramTotalBytes: int | None = None
    ramUsedBytes: int | None = None
    ramAvailableBytes: int | None = None
    uptimeSeconds: float | None = None


class Check(PublicModel):
    name: str
    status: str


class Operation(PublicModel):
    state: str = "idle"
    action: str | None = None
    message: str | None = None
    startedAt: float | None = None
    finishedAt: float | None = None


class RuntimeEvent(PublicModel):
    timestamp: float
    hostId: str
    app: str
    severity: str
    type: str
    message: str


class ControlStatus(PublicModel):
    desiredRunning: bool = False
    manualIntervention: list[str] = Field(default_factory=list)
    operation: Operation = Field(default_factory=Operation)
    events: list[RuntimeEvent] = Field(default_factory=list)


class RuntimeStatus(PublicModel):
    observedAt: float
    installationId: str
    hostId: str
    health: str
    agentOnline: bool = False
    dockerHealthy: bool = False
    vpn: VPNStatus = Field(default_factory=VPNStatus)
    portForwarding: PortForwardStatus = Field(default_factory=PortForwardStatus)
    qBittorrent: TorrentStatus = Field(default_factory=TorrentStatus)
    storage: StorageStatus = Field(default_factory=StorageStatus)
    checks: list[Check] = Field(default_factory=list)
    deviceInventory: list[Device] = Field(default_factory=list)
    deviceChecks: list[DeviceCheck] = Field(default_factory=list)
    host: HostMetrics = Field(default_factory=HostMetrics)
    control: ControlStatus = Field(default_factory=ControlStatus)
    plex: "PlexStatus | None" = None


class PlexLibrary(PublicModel):
    id: str | None = None
    name: str | None = None
    type: str | None = None


class PlexStatus(PublicModel):
    running: bool = False
    version: str | None = None
    startedAt: str | None = None
    libraries: list[PlexLibrary] = Field(default_factory=list)
    activeStreams: int | None = None
    memoryBytes: int | None = None
    cpuPercent: float | None = None


RuntimeStatus.model_rebuild()


class RemoteStatusCache:
    def __init__(self, ttl=5, timeout=8):
        self.ttl, self.timeout = ttl, timeout
        self.entries, self.locks = {}, {}

    async def get(self, host_id, client, path="/v1/seedbox/status"):
        key = (host_id, path)
        async with self.locks.setdefault(key, asyncio.Lock()):
            saved = self.entries.get(key)
            if saved and time.monotonic() - saved[0] < self.ttl:
                return {**saved[1], "cached": True}
            try:
                raw = await asyncio.wait_for(client.request("GET", path), self.timeout)
                data = RuntimeStatus.model_validate(raw).model_dump()
                if data["hostId"] != host_id or not -5 <= time.time() - data["observedAt"] <= 30:
                    raise ValueError("Stale or mismatched Agent status")
                data.update(cached=False, available=True)
            except Exception:
                # No exception bodies, tokens, raw responses or stale Healthy on failure.
                data = {
                    "hostId": host_id,
                    "health": "offline",
                    "agentOnline": False,
                    "available": False,
                    "cached": False,
                    "message": "Agent status unavailable, invalid or timed out",
                }
            self.entries[key] = (time.monotonic(), data)
            return data
