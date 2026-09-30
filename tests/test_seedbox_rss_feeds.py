import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub import seedbox_rss_feeds as module
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.seedbox_rss import parse_feed
from sqlalchemy import delete, select


def entry(identifier):
    return {
        "id": identifier,
        "title": identifier,
        "published": "",
        "url": "magnet:?xt=urn:btih:" + identifier * 40,
    }


def setup(client):
    service = module.RSSFeeds(client.app.state.services)
    agent = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "storageId": "downloads",
                "downloadLocations": [{"id": "root"}, {"id": "location-" + "a" * 64}],
            }
        )
    )
    service.client = lambda: agent
    service.fetch = AsyncMock(return_value=[entry("a")])
    service.add_item = AsyncMock(return_value={"state": "added"})
    return service, agent


def body(name="Movies", automatic=True, destination="root"):
    return module.NewFeed(
        name=name,
        url="https://tracker.example/" + name + "?key=private",
        automatic=automatic,
        storageId="downloads",
        downloadLocationId=destination,
    )


def test_initial_baseline_never_downloads_and_future_entries_survive_restart(client):
    async def run():
        service, agent = setup(client)
        created = await service.create(body(), agent)
        identifier = created["feeds"][0]["id"]
        service.add_item.assert_not_awaited()
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        service.fetch.return_value = [entry("b"), entry("a")]
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 1
        assert service.add_item.call_args.args[2]["id"] == "b"
        assert service.add_item.call_args.args[3] is True
        restarted = module.RSSFeeds(service.svc)
        restarted.fetch = service.fetch
        restarted.client = service.client
        restarted.add_item = AsyncMock()
        await restarted.check(identifier, force=True)
        restarted.add_item.assert_not_awaited()
        with service.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == module.KEY))
            assert "private" not in json.dumps(row.value)
        assert "private" not in json.dumps(restarted.public(restarted.load()))

    asyncio.run(run())


def test_multiple_feeds_independent_destinations_and_manual_mode(client):
    async def run():
        service, agent = setup(client)
        await service.create(body(), agent)
        await service.create(body("TV", destination="location-" + "a" * 64), agent)
        await service.create(body("Manual", automatic=False), agent)
        service.fetch.return_value = [entry("b"), entry("a")]
        for feed in service.load():
            await service.check(feed["id"], force=True)
        assert service.add_item.await_count == 2
        assert [call.args[1]["downloadLocationId"] for call in service.add_item.call_args_list] == [
            "root",
            "location-" + "a" * 64,
        ]

    asyncio.run(run())


def test_failed_download_persists_pending_for_retry_even_when_entry_leaves_feed(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("b"), entry("a")]
        service.add_item.side_effect = ValueError("private")
        failed = await service.check(identifier, force=True)
        assert failed["feeds"][0]["pending"] == 1
        assert "private" not in json.dumps(failed)
        service.add_item.side_effect = None
        service.fetch.return_value = [entry("a")]
        await service.check(identifier, force=True)
        assert service.load()[0]["pending"] == []
        assert service.add_item.call_args.args[2]["id"] == "b"

    asyncio.run(run())


def test_enable_and_reenable_skip_current_entries_and_disable_discards_pending(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(automatic=False), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("b"), entry("a")]
        enabled = module.FeedOptions(name="Movies", automatic=True, storageId="downloads")
        await service.configure(identifier, enabled, agent)
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        service.fetch.return_value = [entry("c"), entry("b"), entry("a")]
        service.add_item.side_effect = ValueError()
        await service.check(identifier, force=True)
        assert service.load()[0]["pending"]
        await service.configure(identifier, enabled.model_copy(update={"automatic": False}), agent)
        assert service.load()[0]["pending"] == []
        service.fetch.return_value = [entry("d"), entry("c"), entry("b"), entry("a")]
        await service.configure(identifier, enabled, agent)
        service.add_item.reset_mock()
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()

    asyncio.run(run())


def test_failed_initial_fetch_does_not_save_or_download(client):
    async def run():
        service, agent = setup(client)
        service.fetch.side_effect = DomainError("rss", "Unavailable", 422)
        with pytest.raises(DomainError):
            await service.create(body(), agent)
        assert service.load() == []
        service.add_item.assert_not_awaited()

    asyncio.run(run())


def test_migration_keeps_existing_feed_manual(client, monkeypatch):
    service, agent = setup(client)
    with service.svc.sessions.begin() as db:
        db.execute(delete(Setting).where(Setting.key == module.KEY))
    monkeypatch.setattr(
        module,
        "read_feed",
        lambda svc: {"url": "https://tracker.example/rss?key=private", "items": [entry("a")]},
    )
    feed = service.load()[0]
    assert feed["automatic"] is False
    assert feed["seen"] == ["a"]
    assert feed["pending"] == []


def test_stable_guid_and_full_baseline_not_limited_to_visible_200():
    xml = (
        "<rss><channel>"
        + "".join(
            f'<item><guid>{i}</guid><enclosure url="https://tracker.example/{i}?key=one"/></item>'
            for i in range(205)
        )
        + "</channel></rss>"
    )
    rows = parse_feed(xml.encode(), "https://tracker.example/rss")
    changed = parse_feed(xml.replace("key=one", "key=two").encode(), "https://tracker.example/rss")
    assert len(rows) == 205
    assert [r["id"] for r in rows] == [r["id"] for r in changed]


def test_concurrent_checks_add_new_entry_once(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("b"), entry("a")]
        await asyncio.gather(
            service.check(identifier, force=True), service.check(identifier, force=True)
        )
        assert service.add_item.await_count == 1

    asyncio.run(run())


def test_invalid_destination_and_bare_key_do_not_save(client):
    async def run():
        service, agent = setup(client)
        with pytest.raises(DomainError):
            await service.create(body(destination="location-" + "b" * 64), agent)
        with pytest.raises(DomainError) as error:
            await service.create(
                module.NewFeed(name="Key", url="private-key", storageId="downloads"), agent
            )
        assert "complete" in str(error.value)
        assert service.load() == []

    asyncio.run(run())


def test_background_poll_processes_due_feed_without_browser(client, monkeypatch):
    async def run():
        service, agent = setup(client)
        await service.create(body(), agent)
        feeds = service.load()
        feeds[0]["checkedAt"] = 0
        service.save(feeds)
        service.fetch.return_value = [entry("b"), entry("a")]

        async def end_pass(seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(module.asyncio, "sleep", end_pass)
        with pytest.raises(asyncio.CancelledError):
            await service.poll()
        assert service.add_item.await_count == 1
        assert service.load()[0]["pending"] == []

    asyncio.run(run())


def test_multifeed_routes_are_admin_only(client):
    assert client.get("/api/v1/seedbox/rss/feeds").status_code == 401
    assert client.post("/api/v1/seedbox/rss/feeds/example/refresh").status_code in (401, 403)
