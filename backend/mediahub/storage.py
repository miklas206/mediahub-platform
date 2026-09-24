import os
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mediahub.contracts import StorageInput
from mediahub.db import StorageLocation
from mediahub.errors import DomainError


class StorageManager:
    def __init__(self, sessions, config, events):
        self.sessions, self.config, self.events = sessions, config, events

    def validate(self, path: str):
        requested = Path(path)
        if not requested.is_absolute():
            raise DomainError("invalid_path", "Use an absolute storage path")
        try:
            resolved = requested.resolve()
            roots = self.config.storage_roots or [self.config.data_dir]
            if not any(resolved.is_relative_to(root.resolve()) for root in roots):
                raise DomainError(
                    "path_not_allowed",
                    "Path is outside the administrator-configured storage roots",
                    403,
                )
            exists = resolved.is_dir()
            readable = exists and os.access(resolved, os.R_OK | os.X_OK)
            writable = exists and os.access(resolved, os.W_OK | os.X_OK)
            usage = shutil.disk_usage(resolved) if exists else None
            return {
                "path": str(resolved),
                "exists": exists,
                "readable": readable,
                "writable": writable,
                "permissionCheck": "advisory-no-write-probe",
                "totalBytes": usage.total if usage else None,
                "freeBytes": usage.free if usage else None,
            }
        except (OSError, RuntimeError, ValueError):
            raise DomainError(
                "storage_unavailable", "Storage path cannot be inspected", 400
            ) from None

    def register(self, item: StorageInput):
        status = self.validate(item.path)
        if not status["exists"] or not status["readable"]:
            raise DomainError("storage_unavailable", "Storage must exist and be readable")
        try:
            with self.sessions.begin() as db:
                location = StorageLocation(name=item.name, kind=item.kind, path=status["path"])
                db.add(location)
                db.flush()
                location_id = location.id
        except IntegrityError:
            raise DomainError(
                "storage_exists", "This storage name or path is already registered", 409
            ) from None
        self.events.record(
            "storage.registered", "storage", "Storage location registered (no files modified)"
        )
        return {"id": location_id, "name": item.name, "kind": item.kind, **status}

    def list(self):
        with self.sessions() as db:
            locations = db.scalars(select(StorageLocation)).all()
        result = []
        for loc in locations:
            try:
                status = self.validate(loc.path)
            except DomainError as error:
                status = {
                    "path": loc.path,
                    "exists": False,
                    "readable": False,
                    "writable": False,
                    "totalBytes": None,
                    "freeBytes": None,
                    "error": error.message,
                }
            result.append({"id": loc.id, "name": loc.name, "kind": loc.kind, **status})
        return result
