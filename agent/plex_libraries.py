"""Explicit library edits inside the managed Plex server's read-only media mounts."""

import asyncio
import base64
import hashlib
import json
import re
from functools import wraps
from pathlib import PurePosixPath
from urllib.parse import quote

from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.nas_storage import storage_operation

DEFAULTS = {
    "movies": ("movie", "Plex Movie", "tv.plex.agents.movie"),
    "tv": ("show", "Plex TV Series", "tv.plex.agents.series"),
    "other": ("movie", "Plex Video Files", "tv.plex.agents.none"),
}


def bounded_change(method):
    @wraps(method)
    async def bounded(*args, **kwargs):
        try:
            async with asyncio.timeout(120):
                return await method(*args, **kwargs)
        except TimeoutError:
            raise DomainError(
                "plex_library_timeout",
                "Plex library operation timed out; refresh the library list before retrying",
                503,
            ) from None

    return bounded


def revision(section):
    value = {
        key: section.get(key, "")
        for key in ("key", "title", "type", "agent", "scanner", "language")
    }
    value["locations"] = sorted(loc.get("path", "") for loc in section.findall("Location"))
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class PlexLibraries:
    def __init__(self, runtime):
        self.runtime, self.control, self.state_dir = runtime, runtime.control, runtime.state_dir

    def roots(self, policy):
        return sorted(
            {
                m.target
                for m in policy.mounts
                if m.readOnly
                and re.fullmatch(
                    r"/media/(?:movies|tv|other)/[1-9][0-9]*|/media/nas/[a-f0-9]{24}", m.target
                )
            }
        )

    def path(self, policy, path):
        if (
            not isinstance(path, str)
            or len(path) > 2048
            or "\\" in path
            or any(ord(c) < 32 for c in path)
            or str(PurePosixPath(path)) != path
            or ".." in PurePosixPath(path).parts
        ):
            raise DomainError(
                "plex_folder_denied", "Choose a folder inside Plex's assigned media storage", 403
            )
        target = PurePosixPath(path)
        if not any(target.is_relative_to(root) for root in self.roots(policy)):
            raise DomainError(
                "plex_folder_denied", "Choose a folder inside Plex's assigned media storage", 403
            )
        return path

    async def active(self):
        policy = self.control.policy()
        inspected = await self.control.inspect(policy)
        if not inspected.get("State", {}).get("Running"):
            raise DomainError(
                "plex_libraries_stopped",
                "Start Plex in MediaHub to edit its libraries and folders",
                409,
            )
        return policy

    async def sections(self, policy):
        root = await self.control.plex_get(policy, "/library/sections")
        sections = list(root.findall("Directory"))
        if len(sections) > 200:
            raise DomainError(
                "plex_library_limit", "Too many Plex libraries to edit in one view", 409
            )
        return sections

    async def browse(self, policy, path):
        path = self.path(policy, path)
        encoded = quote(base64.b64encode(path.encode()).decode(), safe="")
        listing = await self.control.plex_get(
            policy, "/services/browse/" + encoded, params={"includeFiles": 0}
        )
        result = []
        for row in listing.findall("Path"):
            child = row.get("path", "")
            try:
                self.path(policy, child)
            except DomainError:
                continue
            if PurePosixPath(child).parent == PurePosixPath(path) and child != path:
                result.append({"path": child, "name": PurePosixPath(child).name})
        return {
            "path": path,
            "folders": sorted(result[:200], key=lambda r: r["name"].casefold()),
            "truncated": len(result) > 200,
        }

    @storage_operation
    async def folders(self, path):
        return await self.browse(await self.active(), path)

    @storage_operation
    async def inventory(self):
        policy = self.control.policy()
        inspected = await self.control.inspect(policy)
        choices = [{"path": root} for root in self.roots(policy)]
        if not inspected.get("State", {}).get("Running"):
            return {
                "available": False,
                "message": "Start Plex in MediaHub to edit its libraries and folders",
                "roots": choices,
                "libraries": [],
            }
        return {
            "available": True,
            "roots": choices,
            "libraries": [
                {
                    "id": s.get("key"),
                    "name": s.get("title"),
                    "type": s.get("type"),
                    "locations": [loc.get("path", "") for loc in s.findall("Location")],
                    "revision": revision(s),
                }
                for s in await self.sections(policy)
                if re.fullmatch(r"[0-9]{1,20}", s.get("key", ""))
            ],
        }

    def adopt(self):
        # An explicit library edit supersedes any unfinished first-install defaults.
        path = self.state_dir / "plex-plan.json"
        if path.exists():
            plan = read_json(path)
            if plan.get("bootstrapLibraries") is True:
                plan["bootstrapLibraries"] = False
                save_json(path, plan)
        self.runtime.libraries_ready = True

    async def validate_locations(self, policy, locations, existing=()):
        if len(locations) != len(set(locations)):
            raise DomainError("plex_folder_duplicate", "Choose each library folder only once", 422)
        for path in locations:
            if path in existing:
                continue  # Permit removing an unavailable folder without probing the remaining NAS paths.
            self.path(policy, path)
            parent = str(PurePosixPath(path).parent)
            if path not in self.roots(policy):
                siblings = await self.browse(policy, parent)
                if path not in {row["path"] for row in siblings["folders"]}:
                    # A truncated folder listing can be browsed but must never approve an unobserved path.
                    raise DomainError(
                        "plex_folder_unavailable",
                        "The selected Plex folder is unavailable; refresh the folder list",
                        409,
                    )
            await self.browse(policy, path)

    async def current(self, policy, identifier, expected):
        if not re.fullmatch(r"[0-9]{1,20}", identifier):
            raise DomainError("plex_library_invalid", "Invalid Plex library", 422)
        section = next((s for s in await self.sections(policy) if s.get("key") == identifier), None)
        if section is None:
            raise DomainError(
                "plex_library_missing",
                "This Plex library was removed; refresh the library list",
                404,
            )
        if revision(section) != expected:
            raise DomainError(
                "plex_library_changed",
                "This Plex library changed elsewhere; cancel editing and refresh before saving",
                409,
            )
        return section

    @storage_operation
    @bounded_change
    async def edit(self, identifier, body):
        async with self.control.lock:
            policy = await self.active()
            section = await self.current(policy, identifier, body.expectedRevision)
            previous = [loc.get("path", "") for loc in section.findall("Location")]
            await self.validate_locations(policy, body.locations, previous)
            self.adopt()
            if set(previous) != set(body.locations):
                await self.control.plex_get(
                    policy,
                    "/library/sections/" + identifier,
                    "PUT",
                    params=[
                        ("agent", section.get("agent", "")),
                        *(("location", path) for path in body.locations),
                    ],
                )
            self.control.record("library_folders_changed")
            return {"saved": True, "mediaPreserved": True}

    @storage_operation
    @bounded_change
    async def create(self, body):
        async with self.control.lock:
            policy = await self.active()
            sections = await self.sections(policy)
            for section in sections:
                if section.get("title") == body.name:
                    if (
                        set(body.locations)
                        == {loc.get("path", "") for loc in section.findall("Location")}
                        and section.get("agent") == DEFAULTS[body.kind][2]
                    ):
                        self.adopt()
                        return {"saved": True, "existing": True, "mediaPreserved": True}
                    raise DomainError(
                        "plex_library_exists",
                        "A library with this name already exists; edit its folders instead",
                        409,
                    )
            if len(sections) >= 200:
                raise DomainError(
                    "plex_library_limit", "Too many Plex libraries to edit in one view", 409
                )
            await self.validate_locations(policy, body.locations)
            self.adopt()
            media_type, scanner, agent = DEFAULTS[body.kind]
            await self.control.plex_get(
                policy,
                "/library/sections",
                "POST",
                params=[
                    ("name", body.name),
                    ("type", media_type),
                    ("scanner", scanner),
                    ("agent", agent),
                    ("language", "en-US"),
                    *(("location", path) for path in body.locations),
                ],
            )
            self.control.record("library_created")
            return {"saved": True, "mediaPreserved": True}

    @storage_operation
    @bounded_change
    async def remove(self, identifier, body):
        if not body.confirmRemove:
            raise DomainError(
                "plex_library_confirmation",
                "Confirm removal of the Plex library metadata first",
                422,
            )
        async with self.control.lock:
            policy = await self.active()
            await self.current(policy, identifier, body.expectedRevision)
            self.adopt()
            # This removes a library section, never an item/file deletion endpoint.
            await self.control.plex_get(policy, "/library/sections/" + identifier, "DELETE")
            self.control.record("library_removed")
            return {"saved": True, "mediaPreserved": True}
