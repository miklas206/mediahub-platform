"""Installation-scoped qBittorrent operations; no arbitrary paths, URLs or file deletion."""

import base64
import contextlib
import hashlib
from pathlib import Path, PurePosixPath

from mediahub.errors import DomainError

from agent.seedbox_rotation import authenticated_client
from agent.seedbox_secret_store import SeedboxSecretStore
from agent.torrent_input import magnet_hash, torrent_hash
from agent.torrent_retention import RetentionService


class TorrentService:
    def __init__(self, control):
        self.control = control
        self.retention = RetentionService(self)

    @contextlib.asynccontextmanager
    async def session(self, mutate=False):
        control = self.control
        control.initialize()
        if control.job and not control.job.done():
            raise DomainError("operation_busy", "Runtime operation in progress", 409)
        async with control.lifecycle.lock:
            try:
                driver = control.driver
                policy, spec = driver.binding()
                await driver.storage_guard()
                if mutate:
                    if (
                        not control.lifecycle.state["desiredRunning"]
                        or control.lifecycle.state["manualIntervention"]
                    ):
                        raise ValueError("Runtime not ready")
                    ip = await driver.verify_vpn()
                    await driver.verify_torrent(ip)
                    if driver.forwarding.public()["status"] != "healthy":
                        raise ValueError("Forwarding not ready")
                credentials = SeedboxSecretStore(Path(policy.workRoot) / "vault").load(
                    "seedbox-runtime"
                )
                client = await authenticated_client(f"http://127.0.0.1:{spec.webPort}", credentials)
                try:
                    yield client, spec, policy
                finally:
                    with contextlib.suppress(Exception):
                        await client.post("/api/v2/auth/logout")
                    await client.aclose()
            except DomainError:
                raise
            except Exception:
                # Never forward HTTP response bodies, URI/passkey or torrent bytes.
                raise DomainError(
                    "torrent_operation_failed",
                    "Torrent request failed or safety checks did not pass",
                    409,
                ) from None

    async def list(self):
        async with self.session() as (client, spec, policy):
            response = await client.get("/api/v2/torrents/info", params={"limit": 500})
            response.raise_for_status()
            allowed_roots = self.allowed_save_roots(policy, spec)
            cleanup = self.retention.load(policy)
            rows = []
            for item in response.json():
                path = PurePosixPath(item.get("save_path", ""))
                allowed = any(path == root or root in path.parents for root in allowed_roots)
                rows.append(
                    {
                        key: item.get(key)
                        for key in [
                            "hash",
                            "name",
                            "progress",
                            "state",
                            "dlspeed",
                            "upspeed",
                            "ratio",
                            "eta",
                            "size",
                            "num_seeds",
                            "num_leechs",
                            "category",
                            "seeding_time",
                        ]
                    }
                    | {
                        "actionsAllowed": allowed,
                        "retention": cleanup.get(item.get("hash"), {}).get("rule"),
                        "retentionMessage": cleanup.get(item.get("hash"), {}).get("error", ""),
                    }
                )
            locations = self.download_locations(policy, spec)
            return {
                "items": rows,
                "storageId": spec.downloadsStorageId,
                "downloadLocations": [
                    {
                        "id": item["id"],
                        "label": item["label"],
                        "storageLabel": item["storageLabel"],
                    }
                    for item in locations
                ],
                "limit": 500,
                "retentionSupported": True,
            }

    @staticmethod
    def writable_storage_roots(policy, spec):
        """Return install-authorized writable roots, never request-supplied paths."""
        logical_ids = {spec.downloadsStorageId}
        roots = [
            {
                "logicalId": spec.downloadsStorageId,
                "storageLabel": "Downloads",
                "root": Path(policy.paths.downloads),
                "saveRoot": PurePosixPath("/downloads"),
                "primary": True,
            }
        ]
        for mapping in policy.paths.extraStorage:
            if mapping.readOnly or not mapping.allowTorrentDownload:
                continue
            if mapping.logicalId in logical_ids:
                raise ValueError("Writable logical storage identifiers must be unique")
            logical_ids.add(mapping.logicalId)
            roots.append(
                {
                    "logicalId": mapping.logicalId,
                    "storageLabel": mapping.displayName
                    or mapping.logicalId.replace("-", " ").title(),
                    "root": Path(mapping.source),
                    "saveRoot": PurePosixPath(mapping.target),
                    "primary": False,
                }
            )
        return roots

    @classmethod
    def allowed_save_roots(cls, policy, spec):
        return [item["saveRoot"] for item in cls.writable_storage_roots(policy, spec)]

    @classmethod
    def download_locations(cls, policy, spec):
        """Return the explicitly authorized storage roots only.

        The browser receives opaque identifiers rather than filesystem paths. Existing
        media subfolders are content, not additional download destinations.
        """
        locations = []
        for storage in cls.writable_storage_roots(policy, spec):
            root = storage["root"]
            resolved_root = root.resolve(strict=True)
            if not resolved_root.is_dir():
                raise ValueError("Authorized storage is not a directory")
            identity = storage["logicalId"] + "\0"
            root_id = (
                "root"
                if storage["primary"]
                else "location-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
            )
            locations.append(
                {
                    "id": root_id,
                    "label": "Top folder",
                    "storageLabel": storage["storageLabel"],
                    "savePath": str(storage["saveRoot"]),
                }
            )
        return locations

    @classmethod
    def resolve_download_location(cls, policy, spec, location_id: str):
        for location in cls.download_locations(policy, spec):
            if location["id"] == location_id:
                return location["savePath"]
        raise DomainError(
            "download_location_denied",
            "Choose an available folder inside approved Seedbox storage",
            403,
        )

    async def add(self, body):
        try:
            if body.magnet is not None:
                value = body.magnet.get_secret_value()
                identity = magnet_hash(value)
                raw = None
            else:
                raw = base64.b64decode(body.torrentBase64.get_secret_value(), validate=True)
                identity = torrent_hash(raw)
                value = None
        except Exception:
            raise DomainError(
                "invalid_torrent", "Invalid or unsupported torrent input", 422
            ) from None
        async with self.session(mutate=True) as (client, spec, policy):
            if body.storageId != spec.downloadsStorageId:
                raise DomainError(
                    "storage_denied", "Use the authorized logical downloads storage", 403
                )
            save_path = self.resolve_download_location(policy, spec, body.downloadLocationId)
            existing = await client.get("/api/v2/torrents/info", params={"hashes": identity})
            existing.raise_for_status()
            if existing.json():
                return {"state": "already_present", "hash": identity, "started": False}
            params = {
                "savepath": save_path,
                "autoTMM": "false",
                "stopped": "true",
                "paused": "true",
                "category": "",
            }
            kwargs = (
                {"files": {"torrents": ("upload.torrent", raw, "application/x-bittorrent")}}
                if raw is not None
                else {}
            )
            if value is not None:
                params["urls"] = value
            response = await client.post("/api/v2/torrents/add", data=params, **kwargs)
            response.raise_for_status()
            # Versions differ in acknowledgement bodies. Verify admission by the
            # exact infohash below; never interpret or expose the response body.
            # Wait for observable admission, not merely HTTP 200.
            import asyncio

            for _ in range(20):
                response = await client.get("/api/v2/torrents/info", params={"hashes": identity})
                response.raise_for_status()
                if response.json():
                    break
                await asyncio.sleep(0.2)
            else:
                raise DomainError(
                    "torrent_not_observable", "Torrent was not visible after submission", 409
                )
            if body.retention.mode != "disabled":
                await self.retention.register(
                    client, policy, spec, response.json()[0], body.retention
                )
            if body.startImmediately:
                await self.control.driver.storage_guard()
                ip = await self.control.driver.verify_vpn()
                await self.control.driver.verify_torrent(ip)
                (
                    await client.post("/api/v2/torrents/start", data={"hashes": identity})
                ).raise_for_status()
            return {"state": "added", "hash": identity, "started": body.startImmediately}

    async def configure_retention(self, body):
        async with self.session() as (client, spec, policy):
            response = await client.get("/api/v2/torrents/info", params={"hashes": body.hash})
            response.raise_for_status()
            rows = response.json()
            if len(rows) != 1:
                raise DomainError("torrent_missing", "Torrent not found", 404)
            await self.retention.register(client, policy, spec, rows[0], body.retention)
            return {"state": "saved"}

    async def action(self, body):
        async with self.session(mutate=body.action in {"resume", "recheck"}) as (
            client,
            spec,
            _policy,
        ):
            response = await client.get("/api/v2/torrents/info", params={"hashes": body.hash})
            response.raise_for_status()
            rows = response.json()
            if len(rows) != 1:
                raise DomainError("torrent_missing", "Torrent not found", 404)
            path = PurePosixPath(rows[0].get("save_path", ""))
            allowed_roots = self.allowed_save_roots(_policy, spec)
            if not any(path == root or root in path.parents for root in allowed_roots):
                raise DomainError("storage_denied", "Torrent is outside authorized storage", 403)
            endpoint = {
                "pause": "stop",
                "resume": "start",
                "recheck": "recheck",
                "remove": "delete",
            }[body.action]
            data = {"hashes": body.hash}
            if body.action == "remove":
                data["deleteFiles"] = "false"
            (await client.post("/api/v2/torrents/" + endpoint, data=data)).raise_for_status()
            return {"state": "accepted", "dataPreserved": True}
