"""Persistent per-feed baseline and queue. New entries only; no browser required."""

import asyncio
import base64
import json
import logging
import re
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import Field, SecretStr
from sqlalchemy import delete, select

from mediahub.api import administrator, result, services
from mediahub.apps.seedbox_daily import AddTorrent
from mediahub.contracts import StrictModel
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.rss_retention import RetentionRule
from mediahub.seedbox_rss import KEY as LEGACY_KEY
from mediahub.seedbox_rss import fetch_public, parse_feed, read_feed, url_parts
from mediahub.seedbox_wizard_api import target

KEY = "seedbox_rss_feeds"
INTERVAL = 300
HISTORY_LIMIT = 200
SETTINGS_KEY = "seedbox_rss_settings"
router = APIRouter(prefix="/seedbox/rss/feeds", dependencies=[Depends(administrator)])


def history_hash(value):
    """Only publish torrent identities, never arbitrary Agent response values."""
    if isinstance(value, str) and re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", value):
        return value.lower()
    return None


class FeedSettings(StrictModel):
    intervalSeconds: int = Field(default=INTERVAL, ge=60, le=86400, strict=True)


class FeedOptions(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    automatic: bool = False
    retention: RetentionRule = Field(default_factory=RetentionRule)
    storageId: str = Field(min_length=1, max_length=128)
    downloadLocationId: str = Field(default="root", pattern=r"^(?:root|location-[a-f0-9]{64})$")


class NewFeed(FeedOptions):
    url: SecretStr = Field(min_length=1, max_length=8192, exclude=True)


class Selection(StrictModel):
    ids: list[str] = Field(min_length=1, max_length=20)
    startImmediately: bool = False


class RSSFeeds:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()

    def load(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                return json.loads(self.svc.catalog.cipher.decrypt(row.value["sealed"].encode()))
        old = read_feed(self.svc)
        feeds = []
        if old:
            # A legacy feed was manual. Never enable automatic downloads on migration.
            feeds.append(
                dict(
                    id=uuid4().hex,
                    name="Saved RSS feed",
                    url=old["url"],
                    automatic=False,
                    storageId="",
                    downloadLocationId="root",
                    items=old["items"],
                    seen=[r["id"] for r in old["items"]],
                    pending=[],
                    checkedAt=None,
                    error="Choose a destination before enabling automatic downloads.",
                    added=0,
                )
            )
        self.save(feeds)
        if old:
            with self.svc.sessions.begin() as db:
                db.execute(delete(Setting).where(Setting.key == LEGACY_KEY))
        return feeds

    def save(self, feeds):
        sealed = self.svc.catalog.cipher.encrypt(json.dumps(feeds).encode()).decode()
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                row.value = {"sealed": sealed}
            else:
                db.add(Setting(key=KEY, value={"sealed": sealed}))

    def settings(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
            return FeedSettings(**(row.value if row else {}))

    async def configure_settings(self, body):
        async with self.lock:
            with self.svc.sessions.begin() as db:
                row = db.scalar(select(Setting).where(Setting.key == SETTINGS_KEY))
                if row:
                    row.value = body.model_dump()
                else:
                    db.add(Setting(key=SETTINGS_KEY, value=body.model_dump()))
            return body.model_dump()

    def public(self, feeds):
        return {
            "intervalSeconds": self.settings().intervalSeconds,
            "feeds": [
                {
                    **{
                        k: f[k]
                        for k in (
                            "id",
                            "name",
                            "automatic",
                            "storageId",
                            "downloadLocationId",
                            "checkedAt",
                            "error",
                            "added",
                        )
                    },
                    "pending": len(f["pending"]),
                    "automaticHistory": [
                        {
                            **{k: row[k] for k in ("id", "title", "addedAt", "alreadyPresent")},
                            "torrentHash": history_hash(row.get("torrentHash")),
                        }
                        for row in f.get("automaticHistory", [])[:HISTORY_LIMIT]
                    ],
                    "historyUnavailable": max(
                        0, f["added"] - len(f.get("automaticHistory", [])[:HISTORY_LIMIT])
                    ),
                    "retention": f.get("retention", RetentionRule().model_dump()),
                    "baselineCount": len(f["seen"]),
                    "items": [
                        {k: r[k] for k in ("id", "title", "published")} for r in f["items"][:200]
                    ],
                }
                for f in feeds
            ],
        }

    @staticmethod
    def find(feeds, identifier):
        for feed in feeds:
            if feed["id"] == identifier:
                return feed
        raise DomainError("rss_missing", "Feed no longer exists. Reload the page.", 404)

    async def fetch(self, url):
        try:
            return parse_feed(await asyncio.to_thread(fetch_public, url), url)
        except Exception:
            raise DomainError(
                "rss_unavailable",
                "RSS could not be loaded. Check the full private HTTPS feed address and tracker access. History was kept.",
                422,
            ) from None

    def client(self):
        with self.svc.sessions() as db:
            binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
            if not binding:
                raise DomainError("rss_seedbox_missing", "Seedbox is not configured", 409)
            return self.svc.hosts.client(binding.value["hostId"])

    async def validate_destination(self, options, client):
        listing = await client.request("GET", "/v1/seedbox/torrents")
        if options.retention.mode != "disabled" and not listing.get("retentionSupported"):
            raise DomainError(
                "retention_agent_update", "Update the Seedbox Agent to use automatic cleanup", 409
            )
        if options.storageId != listing["storageId"] or options.downloadLocationId not in {
            r["id"] for r in listing.get("downloadLocations", [{"id": "root"}])
        }:
            raise DomainError(
                "rss_destination", "Choose an available Seedbox download location", 422
            )

    async def create(self, body, client):
        async with self.lock:
            feeds = self.load()
            if len(feeds) >= 20:
                raise DomainError("rss_limit", "Up to 20 feeds are supported", 422)
            url = body.url.get_secret_value().strip()
            try:
                url_parts(url)
            except ValueError:
                raise DomainError(
                    "rss_address",
                    "Paste the complete https:// RSS address, not just the RSS key.",
                    422,
                ) from None
            if any(f["url"] == url for f in feeds):
                raise DomainError("rss_duplicate", "This feed is already saved", 409)
            await self.validate_destination(body, client)
            automatic_since = time.time()
            items = await self.fetch(url)
            feeds.append(
                dict(
                    **body.model_dump(),
                    url=url,
                    automaticSince=automatic_since if body.automatic else None,
                    id=uuid4().hex,
                    items=items,
                    seen=[r["id"] for r in items],
                    pending=[],
                    checkedAt=time.time(),
                    error="",
                    added=0,
                )
            )
            self.save(feeds)
            return self.public(feeds)

    async def configure(self, identifier, body, client):
        async with self.lock:
            feeds = self.load()
            feed = self.find(feeds, identifier)
            await self.validate_destination(body, client)
            if body.automatic and not feed["automatic"]:
                # Enabling after a pause starts from NOW, never from stale cached items.
                automatic_since = time.time()
                items = await self.fetch(feed["url"])
                seen = set(feed["seen"]) | {r["id"] for r in items}
                if len(seen) > 100000:
                    raise DomainError(
                        "rss_history_limit",
                        "Feed history is full. Add the feed again to establish a new baseline.",
                        409,
                    )
                feed.update(
                    items=items,
                    seen=sorted(seen),
                    pending=[],
                    checkedAt=time.time(),
                    automaticSince=automatic_since,
                )
            if not body.automatic:
                feed["pending"] = []
            feed.update(body.model_dump())
            feed["error"] = ""
            self.save(feeds)
            return self.public(feeds)

    async def add_item(self, client, feed, row, start):
        payload = dict(
            storageId=feed["storageId"],
            downloadLocationId=feed["downloadLocationId"],
            startImmediately=start,
            retention=feed.get("retention", RetentionRule().model_dump()),
        )
        if row["url"].startswith("magnet:?"):
            payload["magnet"] = row["url"]
        else:
            payload["torrentBase64"] = base64.b64encode(
                await asyncio.to_thread(fetch_public, row["url"])
            ).decode()
        return await client.request(
            "POST", "/v1/seedbox/torrents/add", AddTorrent(**payload).private_payload()
        )

    async def check(self, identifier, force=False):
        async with self.lock:
            feeds = self.load()
            feed = self.find(feeds, identifier)
            if not force and (
                not feed["automatic"]
                or time.time() - (feed["checkedAt"] or 0) < self.settings().intervalSeconds
            ):
                return self.public(feeds)
            try:
                items = await self.fetch(feed["url"])
                seen = set(feed["seen"])
                new = [r for r in items if r["id"] not in seen]
                if (
                    len(seen) + len(new) > 100000
                    or len(feed["pending"]) + (len(new) if feed["automatic"] else 0) > 1000
                ):
                    raise DomainError(
                        "rss_history_limit", "RSS history or queue limit reached", 409
                    )
                feed["seen"] = sorted(seen | {r["id"] for r in new})
                feed["items"] = items
                if feed["automatic"]:
                    now = time.time()
                    if not isinstance(feed.get("automaticSince"), (int, float)):
                        # Old installations have no reliable activation timestamp.
                        # Establish a fresh baseline; never replay their old queue.
                        feed["automaticSince"] = now
                        feed["pending"] = []
                    else:
                        # Discovery identity, not publication time, determines new work.
                        feed["pending"].extend(reversed(new))
                feed["error"] = ""
                feed["checkedAt"] = time.time()
                self.save(feeds)  # Persist discovery before any external side effect.
                if feed["automatic"] and feed["pending"]:
                    client = self.client()
                    # Per-feed work bounded per pass. Other feeds also get a turn.
                    for row in list(feed["pending"][:20]):
                        outcome = await self.add_item(client, feed, row, True)
                        feed["pending"] = [r for r in feed["pending"] if r["id"] != row["id"]]
                        feed["added"] += 1
                        feed["automaticHistory"] = [
                            {
                                "id": row["id"],
                                "title": row["title"],
                                "addedAt": time.time(),
                                "alreadyPresent": outcome.get("state") == "already_present",
                                "torrentHash": history_hash(outcome.get("hash")),
                            },
                            *feed.get("automaticHistory", []),
                        ][:HISTORY_LIMIT]
                        self.save(feeds)
            except Exception:
                feed["error"] = (
                    "Feed check or download failed. Pending entries and history are kept; automatic feeds retry at the configured interval. Check feed access, destination and Seedbox VPN."
                )
                feed["checkedAt"] = time.time()
            self.save(feeds)
            return self.public(feeds)

    async def poll(self):
        while True:
            try:
                async with self.lock:
                    identifiers = [f["id"] for f in self.load() if f["automatic"]]
                for identifier in identifiers:
                    await self.check(identifier)
            except Exception:
                # Never log tracker URLs, keys or exception payloads.
                logging.getLogger("mediahub.rss").warning(
                    "RSS scheduler could not complete its pass; retrying shortly"
                )
            await asyncio.sleep(15)


@router.get("")
async def listing(request: Request):
    target(request)
    service = services(request).rss_feeds
    # Read the latest committed snapshot without waiting for network work in the queue.
    return result(service.public(service.load()))


@router.post("")
async def create(body: NewFeed, request: Request):
    return result(await services(request).rss_feeds.create(body, target(request)))


@router.get("/settings")
async def settings(request: Request):
    target(request)
    return result(services(request).rss_feeds.settings().model_dump())


@router.put("/settings")
async def configure_settings(body: FeedSettings, request: Request):
    target(request)
    return result(await services(request).rss_feeds.configure_settings(body))


@router.put("/{identifier}")
async def configure(identifier: str, body: FeedOptions, request: Request):
    return result(await services(request).rss_feeds.configure(identifier, body, target(request)))


@router.post("/{identifier}/refresh")
async def check(identifier: str, request: Request):
    target(request)
    return result(await services(request).rss_feeds.check(identifier, force=True))


@router.delete("/{identifier}")
async def remove(identifier: str, request: Request):
    target(request)
    service = services(request).rss_feeds
    async with service.lock:
        feeds = [f for f in service.load() if f["id"] != identifier]
        service.save(feeds)
        return result(service.public(feeds))


@router.post("/{identifier}/download")
async def download(identifier: str, body: Selection, request: Request):
    client = target(request)
    service = services(request).rss_feeds
    async with service.lock:
        feeds = service.load()
        feed = service.find(feeds, identifier)
        rows = {r["id"]: r for r in feed["items"]}
        if any(i not in rows for i in body.ids):
            raise DomainError("rss_missing_items", "Refresh and select entries again", 409)
        outcomes = []
        for identifier in dict.fromkeys(body.ids):
            try:
                await service.add_item(client, feed, rows[identifier], body.startImmediately)
                feed["pending"] = [r for r in feed["pending"] if r["id"] != identifier]
                service.save(feeds)
                outcomes.append({"id": identifier, "ok": True})
            except Exception:
                outcomes.append({"id": identifier, "ok": False})
        return result({"items": outcomes})
