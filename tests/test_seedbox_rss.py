import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mediahub import seedbox_rss as rss
from mediahub.db import Setting
from mediahub.errors import DomainError
from sqlalchemy import select

FEED = b'<rss><channel><item><title>Example release</title><pubDate>Today</pubDate><link>https://tracker.example/details/1</link><enclosure url="https://tracker.example/download?id=1&amp;key=private"/></item></channel></rss>'


def test_rss_and_atom_enclosures_and_private_public_boundary():
    rows = rss.parse_feed(FEED, "https://tracker.example/rss?key=private")
    assert rows[0]["url"].endswith("id=1&key=private")
    assert "private" not in json.dumps(rss.public_feed({"items": rows}))
    atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom</title><link rel="enclosure" href="/download/1"/></entry></feed>'
    assert (
        rss.parse_feed(atom, "https://tracker.example/rss")[0]["url"]
        == "https://tracker.example/download/1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://tracker.example/rss",
        "file:///etc/passwd",
        "https://user:pass@tracker.example/rss",
        "https://tracker.example:8080/rss",
    ],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        rss.url_parts(url)


def test_blocks_private_dns_before_connecting(monkeypatch):
    monkeypatch.setattr(
        rss.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    connect = Mock()
    monkeypatch.setattr(rss.socket, "create_connection", connect)
    with pytest.raises(ValueError):
        rss.fetch_public("https://tracker.example/rss")
    connect.assert_not_called()


def test_fetch_pins_public_ip_and_revalidates_redirect(monkeypatch):
    monkeypatch.setattr(
        rss.socket,
        "getaddrinfo",
        lambda host, *a, **k: [
            (2, 1, 6, "", ("127.0.0.1" if host == "internal.example" else "8.8.8.8", 443))
        ],
    )
    raw = Mock()
    connect = Mock(return_value=raw)
    monkeypatch.setattr(rss.socket, "create_connection", connect)
    tls = Mock()
    monkeypatch.setattr(rss.ssl, "create_default_context", lambda: tls)
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 302
    response.getheader.return_value = "https://internal.example/private"
    monkeypatch.setattr(rss.http.client, "HTTPSConnection", lambda *a, **k: connection)
    with pytest.raises(ValueError):
        rss.fetch_public("https://tracker.example/rss?key=secret")
    connect.assert_called_once_with(("8.8.8.8", 443), timeout=12)
    tls.wrap_socket.assert_called_once_with(raw, server_hostname="tracker.example")
    connection.close.assert_called_once()


def test_download_rejects_unknown_selection_without_network(monkeypatch):
    agent = SimpleNamespace(request=AsyncMock())
    monkeypatch.setattr(rss, "target", lambda r: agent)
    monkeypatch.setattr(rss, "services", lambda r: None)
    monkeypatch.setattr(rss, "read_feed", lambda s: {"items": []})
    with pytest.raises(DomainError):
        asyncio.run(
            rss.rss_download(rss.FeedSelection(ids=["unknown"], storageId="downloads"), None)
        )
    agent.request.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        b'<!DOCTYPE rss [<!ENTITY secret SYSTEM "file:///etc/passwd">]><rss/>',
        "<rss/>".encode("utf-16"),
        b"<html/>",
    ],
)
def test_rejects_unsafe_or_nonfeed_xml(data):
    with pytest.raises(ValueError):
        rss.parse_feed(data, "https://tracker.example/rss")


def test_feed_persistence_encrypted_and_failed_refresh_preserves_previous(client, monkeypatch):
    svc = client.app.state.services
    monkeypatch.setattr(rss, "fetch_public", lambda url: FEED)
    result = asyncio.run(rss.refresh(svc, "https://tracker.example/rss?key=private"))
    assert result["configured"]
    with svc.sessions() as db:
        row = db.scalar(select(Setting).where(Setting.key == rss.KEY))
        assert "private" not in json.dumps(row.value)
    assert rss.read_feed(svc)["url"].endswith("key=private")
    monkeypatch.setattr(rss, "fetch_public", Mock(side_effect=ValueError("private")))
    with pytest.raises(DomainError) as error:
        asyncio.run(rss.refresh(svc, "https://tracker.example/bad"))
    assert "key=private" not in str(error.value)
    assert rss.read_feed(svc)["url"].endswith("key=private")


def test_selected_items_only_use_existing_agent_add_and_report_partial_failure(monkeypatch):
    agent = SimpleNamespace(
        request=AsyncMock(side_effect=[{"state": "added"}, DomainError("failed", "private")])
    )
    monkeypatch.setattr(rss, "target", lambda r: agent)
    monkeypatch.setattr(rss, "services", lambda r: None)
    monkeypatch.setattr(
        rss,
        "read_feed",
        lambda s: {
            "items": [
                {"id": "a", "url": "magnet:?xt=urn:btih:" + "a" * 40},
                {"id": "b", "url": "magnet:?xt=urn:btih:" + "b" * 40},
                {"id": "c", "url": "magnet:?xt=urn:btih:" + "c" * 40},
            ]
        },
    )
    result = asyncio.run(
        rss.rss_download(rss.FeedSelection(ids=["a", "b"], storageId="downloads"), None)
    )
    assert [r["ok"] for r in result["data"]["items"]] == [True, False]
    assert agent.request.await_count == 2
    assert agent.request.call_args_list[0].args[2]["startImmediately"] is False
    assert "private" not in json.dumps(result)


def test_rss_routes_require_admin(client):
    assert client.get("/api/v1/seedbox/rss").status_code == 401
    assert client.post("/api/v1/seedbox/rss/refresh").status_code in (401, 403)
