"""Private RSS browsing; bounded public HTTPS fetches and explicit torrent selection."""

import asyncio
import base64
import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import Field, SecretStr
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.apps.seedbox_daily import AddTorrent
from mediahub.contracts import StrictModel
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.seedbox_wizard_api import target

KEY = "seedbox_private_rss"
LIMIT = 2 * 1024 * 1024
router = APIRouter(prefix="/seedbox", dependencies=[Depends(administrator)])


def url_parts(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port not in (None, 443)
        or len(url) > 8192
        or any(ord(c) < 33 for c in url)
    ):
        raise ValueError("Invalid feed address")
    return parsed


def fetch_public(url):
    """Pin each connection to a validated public address; preserve TLS hostname checks."""
    deadline = time.monotonic() + 30
    for _ in range(4):
        parsed = url_parts(url)
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Public HTTPS required")
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=12)
        raw = socket.create_connection((addresses[0][4][0], 443), timeout=12)
        try:
            connection.sock = ssl.create_default_context().wrap_socket(
                raw, server_hostname=parsed.hostname
            )
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request(
                "GET", path, headers={"Accept-Encoding": "identity", "User-Agent": "MediaHub RSS"}
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if (
                response.status != 200
                or response.getheader("Content-Encoding", "identity") != "identity"
            ):
                raise ValueError("Feed response rejected")
            chunks = []
            length = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Response timed out")
                connection.sock.settimeout(min(12, remaining)) if connection.sock else None
                chunk = response.read1(min(65536, LIMIT + 1 - length))
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                length += len(chunk)
                if length > LIMIT:
                    raise ValueError("Response too large")
        finally:
            connection.close()
            raw.close()
    raise ValueError("Too many redirects")


def parse_feed(data, base_url):
    # Decode before checking declarations so UTF-16 cannot bypass the entity guard.
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unsupported XML declarations")
    root = ET.fromstring(data)
    if root.tag.split("}")[-1] not in {"rss", "feed", "RDF"}:
        raise ValueError("Not an RSS/Atom feed")
    rows = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in {"item", "entry"}:
            continue
        fields = {c.tag.split("}")[-1]: (c.text or "").strip() for c in item}
        candidates = []
        for child in item:
            tag = child.tag.split("}")[-1]
            if tag == "enclosure" or (tag == "link" and child.get("rel") == "enclosure"):
                candidates.insert(0, child.get("url") or child.get("href") or "")
            elif tag == "link":
                candidates.append(child.get("href") or child.text or "")
        link = next((urljoin(base_url, x.strip()) for x in candidates if x.strip()), "")
        if not link:
            continue
        if not link.startswith("magnet:?"):
            url_parts(link)
        rows.append(
            {
                "id": hashlib.sha256(
                    (fields.get("guid") or fields.get("id") or link).encode()
                ).hexdigest(),
                "title": fields.get("title", "Untitled")[:300],
                "published": (
                    fields.get("pubDate") or fields.get("published") or fields.get("updated") or ""
                )[:100],
                "url": link,
            }
        )
        if len(rows) > 5000:
            raise ValueError("Feed has too many entries for a complete baseline")
    return list({r["id"]: r for r in rows}.values())


class FeedInput(StrictModel):
    url: SecretStr = Field(max_length=8192, min_length=1, exclude=True)


class FeedSelection(StrictModel):
    ids: list[str] = Field(min_length=1, max_length=20)
    storageId: str = Field(min_length=1, max_length=128)
    downloadLocationId: str = "root"
    startImmediately: bool = False


def read_feed(svc):
    with svc.sessions() as db:
        row = db.scalar(select(Setting).where(Setting.key == KEY))
        if not row:
            return None
        return json.loads(svc.catalog.cipher.decrypt(row.value["sealed"].encode()))


def save_feed(svc, value):
    sealed = svc.catalog.cipher.encrypt(json.dumps(value).encode()).decode()
    with svc.sessions.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key == KEY))
        if row:
            row.value = {"sealed": sealed}
        else:
            db.add(Setting(key=KEY, value={"sealed": sealed}))


def public_feed(feed):
    return {
        "configured": feed is not None,
        "items": [
            {k: row[k] for k in ("id", "title", "published")}
            for row in (feed or {}).get("items", [])
        ],
    }


async def refresh(svc, url):
    try:
        data = await asyncio.to_thread(fetch_public, url)
        feed = {"url": url, "items": parse_feed(data, url)}
        save_feed(svc, feed)
        return public_feed(feed)
    except Exception:
        raise DomainError(
            "rss_unavailable",
            "RSS could not be loaded. Check the private HTTPS RSS address and tracker access. The previous feed was kept.",
            422,
        ) from None


@router.get("/rss")
async def rss_list(request: Request):
    target(request)
    return result(public_feed(read_feed(services(request))))


@router.post("/rss")
async def rss_save(body: FeedInput, request: Request):
    target(request)
    return result(await refresh(services(request), body.url.get_secret_value().strip()))


@router.post("/rss/refresh")
async def rss_refresh(request: Request):
    target(request)
    svc = services(request)
    feed = read_feed(svc)
    if not feed:
        raise DomainError("rss_missing", "Save a private RSS address first", 409)
    return result(await refresh(svc, feed["url"]))


@router.delete("/rss")
async def rss_remove(request: Request):
    target(request)
    with services(request).sessions.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key == KEY))
        if row:
            db.delete(row)
    return result({"configured": False, "items": []})


@router.post("/rss/download")
async def rss_download(body: FeedSelection, request: Request):
    client = target(request)
    feed = read_feed(services(request))
    rows = {r["id"]: r for r in (feed or {}).get("items", [])}
    if any(i not in rows for i in body.ids):
        raise DomainError("rss_item_missing", "Refresh the list and select the items again", 409)
    outcomes = []
    for identifier in dict.fromkeys(body.ids):
        try:
            url = rows[identifier]["url"]
            payload = {
                "storageId": body.storageId,
                "downloadLocationId": body.downloadLocationId,
                "startImmediately": body.startImmediately,
            }
            if url.startswith("magnet:?"):
                payload["magnet"] = url
            else:
                payload["torrentBase64"] = base64.b64encode(
                    await asyncio.to_thread(fetch_public, url)
                ).decode()
            added = await client.request(
                "POST", "/v1/seedbox/torrents/add", AddTorrent(**payload).private_payload()
            )
            outcomes.append({"id": identifier, "ok": True, "state": added.get("state")})
        except Exception:
            outcomes.append(
                {
                    "id": identifier,
                    "ok": False,
                    "message": "Could not add this item. Check tracker access, storage and Seedbox VPN status.",
                }
            )
    return result({"items": outcomes})
