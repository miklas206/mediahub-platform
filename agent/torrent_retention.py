"""Opt-in cleanup, tied to a particular qBittorrent job and validated storage."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
from uuid import uuid4

from mediahub.errors import DomainError
from mediahub.rss_retention import RetentionRule, reached

from agent.install_files import read_json, save_json


class RetentionService:
    def __init__(self, torrents):
        self.torrents = torrents

    @staticmethod
    def path(policy):
        return Path(policy.workRoot) / "torrent-retention.json"

    def load(self, policy):
        path = self.path(policy)
        return read_json(path) if path.exists() else {}

    def save(self, policy, records):
        if len(json.dumps(records).encode()) > 250000:
            raise DomainError(
                "retention_limit", "Too many cleanup rules; remove unused rules first", 409
            )
        save_json(self.path(policy), records)

    @staticmethod
    def tagged(row, record):
        return (
            record["tag"] in {t.strip() for t in row.get("tags", "").split(",")}
            and row.get("added_on") == record["addedOn"]
            and row.get("save_path", "").rstrip("/") == record["savePath"]
        )

    async def register(self, client, policy, spec, row, rule, *, override=False):
        records = self.load(policy)
        identity = row["hash"]
        previous = records.get(identity)
        if (
            not override
            and previous
            and previous.get("override") is True
            and self.tagged(row, previous)
        ):
            # Feed defaults must not replace a choice saved for this particular job.
            return
        if rule.mode == "disabled" and not override:
            records.pop(identity, None)
            self.save(policy, records)
            return
        save_path = PurePosixPath(row.get("save_path", ""))
        if (
            not save_path.is_absolute()
            or ".." in save_path.parts
            or not any(
                save_path == p or p in save_path.parents
                for p in self.torrents.allowed_save_roots(policy, spec)
            )
        ):
            raise DomainError(
                "retention_storage", "Cleanup requires an approved download location", 409
            )
        if not isinstance(row.get("added_on"), int) or row["added_on"] <= 0:
            raise DomainError(
                "retention_identity", "Torrent identity is not available yet; try again", 409
            )
        tag = "mediahub-cleanup-" + uuid4().hex
        record = {
            "tag": tag,
            "addedOn": row["added_on"],
            "savePath": str(save_path),
            "rule": rule.model_dump(),
            "override": override,
            "error": "",
        }
        records[identity] = record
        # Persist first; cleanup cannot act until qBittorrent confirms the unique tag.
        self.save(policy, records)
        response = await client.post(
            "/api/v2/torrents/addTags", data={"hashes": identity, "tags": tag}
        )
        response.raise_for_status()

    @staticmethod
    async def file_paths(client, row):
        response = await client.get("/api/v2/torrents/files", params={"hash": row["hash"]})
        response.raise_for_status()
        files = response.json()
        if not files or len(files) > 10000:
            raise ValueError("Missing or oversized file list")
        save = PurePosixPath(row["save_path"])
        if not save.is_absolute() or ".." in save.parts:
            raise ValueError("Unsafe save path")
        paths = []
        for item in files:
            name = item["name"]
            relative = PurePosixPath(name)
            if (
                relative.is_absolute()
                or not relative.parts
                or ".." in relative.parts
                or "\\" in name
                or "\x00" in name
            ):
                raise ValueError("Unsafe torrent path")
            paths.append(save / relative)
        return paths

    def host_path(self, remote, policy, spec):
        matches = sorted(
            self.torrents.writable_storage_roots(policy, spec),
            key=lambda r: len(r["saveRoot"].parts),
            reverse=True,
        )
        for root in matches:
            if root["saveRoot"] in remote.parents:
                base = root["root"]
                local = base.joinpath(*remote.relative_to(root["saveRoot"]).parts)
                if base.resolve() != base or local.resolve() != local or base not in local.parents:
                    raise ValueError("Symlink or unsafe storage path")
                if local.exists() and not local.is_file():
                    raise ValueError("Torrent path is not a regular file")
                return local
        raise ValueError("File outside writable storage")

    async def validate_files(self, client, row, others, policy, spec):
        paths = await self.file_paths(client, row)
        local = {self.host_path(p, policy, spec) for p in paths}
        # Scan other jobs' file lists. Unknown/incomplete metadata means no file deletion.
        if len(others) > 500:
            raise ValueError("Too many jobs for safe overlap verification")
        for other in others:
            if other["hash"] == row["hash"]:
                continue
            for path in await self.file_paths(client, other):
                # Compare remote paths, plus host paths when this is an approved mapping.
                if path in paths:
                    raise ValueError("Files are shared with another torrent")
                if self.host_path(path, policy, spec) in local:
                    raise ValueError("Storage aliases overlap another torrent")
        return hashlib.sha256("\n".join(sorted(str(p) for p in paths)).encode()).hexdigest()

    async def sweep(self):
        async with self.torrents.session() as (client, spec, policy):
            records = self.load(policy)
            if not records:
                return
            response = await client.get("/api/v2/torrents/info")
            response.raise_for_status()
            rows = response.json()
            by_hash = {r["hash"]: r for r in rows}
            for identity, record in list(records.items()):
                row = by_hash.get(identity)
                if row is None:
                    records.pop(identity)
                    continue
                try:
                    if not self.tagged(row, record):
                        record["error"] = (
                            "Cleanup paused: job identity or location changed. Save its cleanup settings again."
                        )
                        continue
                    rule = RetentionRule(**record["rule"])
                    if rule.mode == "disabled":
                        continue
                    save_path = PurePosixPath(record["savePath"])
                    if not any(
                        root == save_path or root in save_path.parents
                        for root in self.torrents.allowed_save_roots(policy, spec)
                    ):
                        raise ValueError("Location is no longer authorized")
                    if row.get("state") not in {
                        "uploading",
                        "stalledUP",
                        "queuedUP",
                        "pausedUP",
                        "stoppedUP",
                        "forcedUP",
                    } or not reached(rule, row):
                        continue
                    delete_files = rule.action == "delete_files"
                    fingerprint = None
                    if delete_files:
                        fingerprint = await self.validate_files(client, row, rows, policy, spec)
                    # Recheck identity immediately before issuing the destructive command.
                    current = await client.get("/api/v2/torrents/info", params={"hashes": identity})
                    current.raise_for_status()
                    current_rows = current.json()
                    if (
                        len(current_rows) != 1
                        or not self.tagged(current_rows[0], record)
                        or not reached(rule, current_rows[0])
                        or current_rows[0].get("state")
                        not in {
                            "uploading",
                            "stalledUP",
                            "queuedUP",
                            "pausedUP",
                            "stoppedUP",
                            "forcedUP",
                        }
                    ):
                        continue
                    if delete_files:
                        confirmed_paths = await self.file_paths(client, current_rows[0])
                        if (
                            fingerprint
                            != hashlib.sha256(
                                "\n".join(sorted(str(p) for p in confirmed_paths)).encode()
                            ).hexdigest()
                        ):
                            raise ValueError("Torrent files changed during cleanup")
                    response = await client.post(
                        "/api/v2/torrents/delete",
                        data={
                            "hashes": identity,
                            "deleteFiles": "true" if delete_files else "false",
                        },
                    )
                    response.raise_for_status()
                    # Keep the record until a later read confirms the job has disappeared.
                    record["error"] = (
                        "Cleanup requested; waiting for qBittorrent to confirm removal."
                    )
                except Exception:
                    record["error"] = (
                        "Cleanup blocked: could not verify job/files, storage or shared-file safety. No unverified deletion is attempted."
                    )
            self.save(policy, records)

    async def poll(self):
        while True:
            await asyncio.sleep(60)
            try:
                await self.sweep()
            except Exception:
                logging.getLogger("mediahub.retention").warning(
                    "Torrent cleanup unavailable; retrying without deleting unverified files"
                )
