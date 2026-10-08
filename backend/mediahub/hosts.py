"""Authenticated host registry and metadata-only storage mappings. Never mounts data."""

import asyncio
import hashlib
import secrets
import time
from ipaddress import ip_address
from pathlib import PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from mediahub.agent_client import AgentClient
from mediahub.db import Host, HostStorage, LogicalStorage, PairingRequest, now
from mediahub.errors import DomainError


def remote_address(value):
    parsed = urlsplit(value)
    try:
        address = ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise DomainError("invalid_address", "Use an explicit private IP with HTTPS") from None
    if (
        parsed.scheme != "https"
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port == 0
    ):
        raise DomainError(
            "invalid_address",
            "Remote agents require HTTPS on an explicit private IP; no credentials or URL paths",
        )
    return value.rstrip("/")


def path_shape(path):
    # Validate either host OS, not the Core OS. Live Agent validation happens at resolution.
    p = (
        PureWindowsPath(path)
        if "\\" in path or (len(path) > 1 and path[1] == ":")
        else PurePosixPath(path)
    )
    if not p.is_absolute() or ".." in p.parts or str(p) == p.anchor or "\x00" in path:
        raise DomainError(
            "unsafe_path", "Mapping requires an absolute non-root path without traversal"
        )
    return str(p)


class HostRegistry:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()
        with svc.sessions.begin() as db:
            if not db.scalar(select(Host).where(Host.local.is_(True))):
                db.add(
                    Host(
                        id="local",
                        name="MediaHub Host",
                        address=svc.config.agent_url,
                        local=True,
                        details={},
                    )
                )

    def client(self, identifier):
        with self.svc.sessions() as db:
            host = db.get(Host, identifier)
            if not host:
                raise DomainError("unknown_host", "Choose a registered host", 404)
            if host.local:
                return self.svc.agent
            token = self.svc.catalog.cipher.decrypt(host.encrypted_token.encode()).decode()
            return AgentClient(
                SimpleNamespace(
                    agent_url=remote_address(host.address),
                    agent_socket=None,
                    agent_ca_file=self.svc.config.agent_ca_file,
                ),
                token,
            )

    async def refresh(self):
        with self.svc.sessions() as db:
            identifiers = list(db.scalars(select(Host.id)))

        async def one(identifier):
            try:
                details = await self.client(identifier).status()
            except Exception:
                details = {"connected": False}
            with self.svc.sessions.begin() as db:
                host = db.get(Host, identifier)
                host.status = "online" if details.get("connected") else "offline"
                if details.get("connected"):
                    # Only known metadata; never persist arbitrary remote response fields.
                    host.details = {
                        k: details[k]
                        for k in [
                            "hostname",
                            "os",
                            "architecture",
                            "version",
                            "cores",
                            "ramBytes",
                            "docker",
                            "capabilities",
                            "storage",
                            "devices",
                        ]
                        if k in details
                    }
                    host.last_seen = now()

        await asyncio.gather(*(one(i) for i in identifiers))

    def list(self):
        with self.svc.sessions() as db:
            return [
                {
                    "id": h.id,
                    "name": h.name,
                    "address": h.address,
                    "local": h.local,
                    "status": h.status,
                    "last_seen": h.last_seen,
                    **h.details,
                    "deviceHealth": (
                        h.details.get("devices", {}).get("health", "unknown")
                        if h.status == "online"
                        else "unknown"
                    ),
                }
                for h in db.scalars(select(Host))
            ]

    def invitation(self, name, address):
        address = remote_address(address)
        token = secrets.token_urlsafe(48)
        expiry = int(time.time()) + 300
        with self.svc.sessions.begin() as db:
            if db.scalar(select(Host).where((Host.address == address) | (Host.name == name))):
                raise DomainError("host_exists", "Host name or address is already registered", 409)
            db.add(
                PairingRequest(
                    name=name,
                    address=address,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    expires_at=expiry,
                )
            )
        return {"token": token, "expires_at": expiry, "singleUse": True}

    async def pair(self, token, address, agent_token):
        address = remote_address(address)
        async with self.lock:
            digest = hashlib.sha256(token.encode()).hexdigest()
            try:
                with self.svc.sessions.begin() as db:
                    request = db.scalar(
                        select(PairingRequest).where(PairingRequest.token_hash == digest)
                    )
                    if (
                        not request
                        or request.used
                        or request.expires_at <= time.time()
                        or request.address != address
                    ):
                        raise DomainError(
                            "pairing_rejected", "Pairing request is invalid, expired or used", 403
                        )
                    claimed = db.execute(
                        update(PairingRequest)
                        .where(PairingRequest.id == request.id, PairingRequest.used.is_(False))
                        .values(used=True)
                    )
                    if claimed.rowcount != 1:
                        raise DomainError("pairing_rejected", "Pairing request already used", 403)
                    host = Host(
                        name=request.name,
                        address=address,
                        local=False,
                        details={},
                        encrypted_token=self.svc.catalog.cipher.encrypt(
                            agent_token.encode()
                        ).decode(),
                    )
                    db.add(host)
                    db.flush()
                    identifier = host.id
            except IntegrityError:
                raise DomainError(
                    "host_exists", "Host name or address already registered", 409
                ) from None
        return {"host_id": identifier, "paired": True}

    def storage(self):
        with self.svc.sessions() as db:
            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind,
                    "dataset_ref": s.dataset_ref,
                    "mappings": [
                        {"host_id": m.host_id, "path": m.path, "access": m.access}
                        for m in db.scalars(
                            select(HostStorage).where(HostStorage.logical_id == s.id)
                        )
                    ],
                }
                for s in db.scalars(select(LogicalStorage))
            ]

    def add_storage(self, name, kind, dataset_ref):
        try:
            with self.svc.sessions.begin() as db:
                row = LogicalStorage(name=name, kind=kind, dataset_ref=dataset_ref)
                db.add(row)
                db.flush()
                return {"id": row.id, "filesChanged": False}
        except IntegrityError:
            raise DomainError(
                "storage_conflict", "Logical storage name already exists", 409
            ) from None

    def map_storage(self, logical_id, host_id, path, access):
        path = path_shape(path)
        try:
            with self.svc.sessions.begin() as db:
                if not db.get(LogicalStorage, logical_id) or not db.get(Host, host_id):
                    raise DomainError("not_found", "Host or logical storage not registered", 404)
                row = db.scalar(
                    select(HostStorage).where(
                        HostStorage.logical_id == logical_id, HostStorage.host_id == host_id
                    )
                )
                if row:
                    row.path, row.access = path, access
                else:
                    db.add(
                        HostStorage(
                            host_id=host_id, logical_id=logical_id, path=path, access=access
                        )
                    )
        except IntegrityError:
            raise DomainError(
                "storage_conflict", "Host path already maps another logical location", 409
            ) from None
        return {"saved": True, "verified": False, "filesChanged": False, "mounted": False}

    async def resolve(self, logical_id, host_id, required_access="ro"):
        with self.svc.sessions() as db:
            row = db.scalar(
                select(HostStorage).where(
                    HostStorage.logical_id == logical_id, HostStorage.host_id == host_id
                )
            )
            if not row:
                raise DomainError(
                    "missing_mapping", "Logical storage has no mapping on selected host"
                )
            path, access = row.path, row.access
        if required_access == "rw" and access != "rw":
            raise DomainError(
                "read_only_mapping", "App cannot escalate a read-only host mapping", 403
            )
        inspection = await self.client(host_id).request(
            "POST", "/v1/directories/inspect", {"path": path}
        )
        if not inspection["readable"] or (required_access == "rw" and not inspection["writable"]):
            raise DomainError(
                "storage_unavailable", "Selected host lacks required filesystem access"
            )
        return {
            "path": inspection["path"],
            "access": required_access,
            "inspection": inspection,
            "datasetIdentityVerified": False,
        }
