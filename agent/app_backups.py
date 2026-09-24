"""Quiesce the owned app, encrypt selected config in RAM, safely resume."""

import asyncio
import base64
from pathlib import Path

from mediahub.app_backups import create_archive
from mediahub.errors import DomainError

from agent.install_files import read_json


class AppBackups:
    def __init__(self, plex, seedbox):
        self.plex, self.seedbox = plex, seedbox
        self.lock = asyncio.Lock()

    async def export(self, app, password):
        if self.lock.locked():
            raise DomainError("backup_busy", "An app backup is already running", 409)
        async with self.lock:
            try:
                payload = await (
                    self.export_plex(password) if app == "plex" else self.export_seedbox(password)
                )
                return {"archiveBase64": base64.b64encode(payload).decode(), "mediaIncluded": False}
            except DomainError:
                raise
            except Exception:
                raise DomainError(
                    "app_backup_failed",
                    "App configuration backup failed; inspect runtime health before retrying",
                    409,
                ) from None

    async def export_plex(self, password):
        c = self.plex
        r = c.runtime
        if not r:
            raise DomainError("backup_unavailable", "Managed Plex is not installed", 409)
        async with c.lock:
            policy = c.policy()
            row = await c.inspect(policy)
            if not await c.storage_verified(policy):
                raise DomainError("storage_unavailable", "Verified Plex storage is required", 409)
            running = row["State"]["Running"]
            plan = read_json(r.state_dir / "plex-plan.json")
            roots = {
                "database": Path(plan["appdataPath"]) / "Plug-in Support" / "Databases",
                "encrypted-preferences": r.state_dir / "plex-secrets",
                "plan.json": r.state_dir / "plex-plan.json",
                "managed.json": Path(c.policy_file),
                "install.json": Path(r.policy_file),
                "intent.json": r.state_dir / "plex-intent.json",
            }
            try:
                if running:
                    await r.stop(policy)
                return await asyncio.to_thread(create_archive, "plex", roots, password)
            finally:
                if running:
                    await asyncio.shield(r.start(policy))

    async def export_seedbox(self, password):
        c = self.seedbox
        c.initialize()
        if c.job and not c.job.done():
            raise DomainError("operation_busy", "Wait for the Seedbox operation to finish", 409)
        async with c.lifecycle.lock:
            policy, spec = c.driver.binding()
            root = Path(policy.workRoot)
            row = await c.driver.container("torrent")
            running = row["State"]["Running"]
            await c.driver.storage_guard()
            roots = {
                "encrypted-secrets": root / "vault",
                "policy.json": Path(c.installer.policy_file),
                **{
                    name: root / name
                    for name in [
                        "installation.json",
                        "compose.json",
                        "lifecycle.json",
                        "vpn-location.json",
                        "install-ownership.json",
                    ]
                },
            }
            try:
                if running:
                    await c.driver.stop_torrent()
                from agent.backup_read import client_configuration

                entries = await client_configuration(c.driver)
                return await asyncio.to_thread(create_archive, "seedbox", roots, password, entries)
            finally:
                if running:
                    await asyncio.shield(c.lifecycle.gated_start())
