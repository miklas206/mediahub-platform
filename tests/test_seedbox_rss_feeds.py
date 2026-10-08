import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub import seedbox_rss_feeds as module
from mediahub.db import Setting
from mediahub.errors import DomainError
from mediahub.seedbox_rss import parse_feed
from sqlalchemy import delete, select


@pytest.fixture(autouse=True)
def rss_clock(monkeypatch):
    # Windows wall-clock ticks can round ISO microseconds below the activation time.
    current = int(datetime.now(timezone.utc).timestamp())

    def tick():
        nonlocal current
        current += 1
        return current

    monkeypatch.setattr(module, "time", SimpleNamespace(time=tick))


def entry(identifier):
    return {
        "id": identifier,
        "title": identifier,
        "published": datetime.fromtimestamp(module.time.time(), timezone.utc).isoformat(),
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


def body(name="Movies", automatic=True, destination="root", allow_older=False):
    return module.NewFeed(
        name=name,
        url="https://tracker.example/" + name + "?key=private",
        automatic=automatic,
        allowOlderItems=allow_older,
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
    assert client.get("/api/v1/seedbox/rss/feeds/settings").status_code == 401
    assert client.put(
        "/api/v1/seedbox/rss/feeds/settings", json={"intervalSeconds": 60}
    ).status_code in (401, 403)


def test_settings_routes_validate_and_persist(logged_in, monkeypatch):
    monkeypatch.setattr(module, "target", lambda request: None)
    path = "/api/v1/seedbox/rss/feeds/settings"
    assert logged_in.get(path).json()["data"] == {"intervalSeconds": 300}
    for invalid in (0, 59, 86401, 60.5, True, "300"):
        assert logged_in.put(path, json={"intervalSeconds": invalid}).status_code == 422
    assert logged_in.put(path, json={"intervalSeconds": 900}).status_code == 200
    restarted = module.RSSFeeds(logged_in.app.state.services)
    assert restarted.settings().intervalSeconds == 900
    assert logged_in.get(path).json()["data"]["intervalSeconds"] == 900


def test_changed_interval_controls_due_checks_and_preserves_manual_refresh(client, monkeypatch):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        manual = (await service.create(body("Manual", automatic=False), agent))["feeds"][1]["id"]
        checked = service.load()[0]["checkedAt"]
        service.fetch.reset_mock()
        monkeypatch.setattr(module.time, "time", lambda: checked + 600)
        await service.configure_settings(module.FeedSettings(intervalSeconds=900))
        await service.check(identifier)
        service.fetch.assert_not_awaited()
        await service.configure_settings(module.FeedSettings(intervalSeconds=60))
        await service.check(identifier)
        assert service.fetch.await_count == 1
        await service.check(identifier)
        await service.check(manual)
        assert service.fetch.await_count == 1
        await service.check(manual, force=True)
        assert service.fetch.await_count == 2
        assert service.public(service.load())["intervalSeconds"] == 60

    asyncio.run(run())


def test_cleanup_requires_capable_agent_and_is_forwarded_to_new_downloads(client):
    from mediahub.rss_retention import RetentionRule

    async def run():
        service, agent = setup(client)
        request = body().model_copy(
            update={"retention": RetentionRule(mode="both", action="delete_files")}
        )
        with pytest.raises(DomainError):
            await service.create(request, agent)
        agent.request.return_value = {
            "storageId": "downloads",
            "downloadLocations": [{"id": "root"}],
            "retentionSupported": True,
        }
        feed = (await service.create(request, agent))["feeds"][0]
        assert feed["retention"]["action"] == "delete_files"
        # Exercise the actual adapter rather than the test's mocked add helper.
        saved = service.load()[0]
        await module.RSSFeeds.add_item(service, agent, saved, entry("b"), True)
        assert agent.request.call_args.args[2]["retention"]["mode"] == "both"

    asyncio.run(run())


@pytest.mark.parametrize(
    "published",
    [
        "Sun, 22 Feb 2026 08:31:39 +0100",
        "",
        "2999-01-01T00:00:00Z",
        "yesterday",
        "2026-10-01T12:00:00",
    ],
)
def test_explicit_discovery_opt_in_accepts_any_publication_date(client, published):
    async def run():
        service, agent = setup(client)
        baseline = dict(entry("a"), published=published)
        service.fetch.return_value = [baseline]
        identifier = (await service.create(body(allow_older=True), agent))["feeds"][0]["id"]
        discovered = dict(entry("b"), published=published)
        service.fetch.return_value = [discovered, baseline]
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 1
        assert service.add_item.call_args.args[2]["id"] == "b"
        # A tracker changing dates or temporarily rotating IDs out does not replay them.
        service.fetch.return_value = []
        await service.check(identifier, force=True)
        service.fetch.return_value = [entry("b"), entry("a")]
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 1

    asyncio.run(run())


def test_legacy_feed_discards_old_pending_and_rebaselines(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        feeds = service.load()
        feeds[0].pop("automaticSince")
        feeds[0]["pending"] = [entry("b")]
        service.save(feeds)
        service.fetch.return_value = [entry("c")]
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        assert service.load()[0]["pending"] == []
        service.fetch.return_value = [entry("d")]
        await service.check(identifier, force=True)
        assert service.add_item.call_args.args[2]["id"] == "d"

    asyncio.run(run())


def test_saved_pending_retries_after_restart_regardless_of_publication_date(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(allow_older=True), agent))["feeds"][0]["id"]
        feeds = service.load()
        feeds[0]["seen"].append("b")
        feeds[0]["pending"] = [dict(entry("b"), published="2020-01-01T00:00:00Z")]
        service.save(feeds)
        service.add_item.side_effect = ValueError("private")
        await service.check(identifier, force=True)
        assert service.load()[0]["pending"][0]["id"] == "b"
        restarted = module.RSSFeeds(service.svc)
        restarted.fetch = AsyncMock(return_value=[])
        restarted.client = service.client
        restarted.add_item = AsyncMock(return_value={"state": "added"})
        await restarted.check(identifier, force=True)
        assert restarted.add_item.call_args.args[2]["id"] == "b"
        assert restarted.load()[0]["pending"] == []
        assert restarted.load()[0]["automaticHistory"][0]["id"] == "b"
        await restarted.check(identifier, force=True)
        assert restarted.add_item.await_count == 1

    asyncio.run(run())


def test_previously_skipped_seen_ids_are_not_replayed(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        feeds = service.load()
        feeds[0]["seen"].append("b")
        service.save(feeds)
        service.fetch.return_value = [dict(entry("b"), published="2020-01-01T00:00:00Z")]
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        assert service.load()[0]["pending"] == []

    asyncio.run(run())


def test_discovered_queue_is_durable_and_bounded_to_twenty_per_poll(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        rows = [entry(str(i)) for i in range(25)]
        service.fetch.return_value = rows

        async def add(client, feed, row, start):
            saved = service.load()[0]
            assert row["id"] in saved["seen"]
            assert row["id"] in {item["id"] for item in saved["pending"]}
            return {"state": "added"}

        service.add_item.side_effect = add
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 20
        assert len(service.load()[0]["pending"]) == 5
        service.fetch.return_value = []
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 25
        assert service.load()[0]["pending"] == []
        service.fetch.return_value = rows
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 25

    asyncio.run(run())


def test_automatic_history_survives_restart_and_feed_entry_disappearance(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("b"), entry("a")]
        service.add_item.return_value = {"state": "added", "hash": "B" * 40}
        checked = await service.check(identifier, force=True)
        history = checked["feeds"][0]["automaticHistory"]
        assert len(history) == 1
        assert history[0]["id"] == "b"
        assert history[0]["title"] == "b"
        assert history[0]["alreadyPresent"] is False
        assert history[0]["addedAt"] > 0
        assert history[0]["torrentHash"] == "b" * 40
        assert "url" not in history[0]
        service.fetch.return_value = []
        await service.check(identifier, force=True)
        restarted = module.RSSFeeds(service.svc)
        assert restarted.public(restarted.load())["feeds"][0]["automaticHistory"] == history
        assert service.add_item.await_count == 1

    asyncio.run(run())


def test_history_does_not_publish_invalid_hash_or_private_agent_payload(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("b")]
        service.add_item.return_value = {
            "state": "added",
            "hash": "https://tracker.example/?key=private",
        }
        checked = await service.check(identifier, force=True)
        assert checked["feeds"][0]["automaticHistory"][0]["torrentHash"] is None
        assert "private" not in json.dumps(checked)

    asyncio.run(run())


def test_history_records_successful_retry_and_existing_torrent_only_once(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("b")]
        service.add_item.side_effect = ValueError("private")
        failed = await service.check(identifier, force=True)
        assert failed["feeds"][0]["automaticHistory"] == []
        service.add_item.side_effect = None
        service.add_item.return_value = {"state": "already_present"}
        result = await service.check(identifier, force=True)
        assert len(result["feeds"][0]["automaticHistory"]) == 1
        assert result["feeds"][0]["automaticHistory"][0]["alreadyPresent"] is True
        again = await service.check(identifier, force=True)
        assert again["feeds"][0]["automaticHistory"] == result["feeds"][0]["automaticHistory"]

    asyncio.run(run())


def test_history_handles_legacy_counts_and_keeps_latest_200(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        feeds = service.load()
        feeds[0]["added"] = 4
        assert service.public(feeds)["feeds"][0]["historyUnavailable"] == 4
        assert service.public(feeds)["feeds"][0]["automaticHistory"] == []
        feeds[0]["automaticHistory"] = [
            {"id": str(i), "title": str(i), "addedAt": i, "alreadyPresent": False}
            for i in reversed(range(200))
        ]
        feeds[0]["added"] = 204
        service.save(feeds)
        service.fetch.return_value = [entry("b")]
        result = (await service.check(identifier, force=True))["feeds"][0]
        assert len(result["automaticHistory"]) == 200
        assert result["automaticHistory"][0]["id"] == "b"
        assert result["automaticHistory"][-1]["id"] == "1"
        assert result["historyUnavailable"] == 5
        assert len(service.load()[0]["automaticHistory"]) == 200

    asyncio.run(run())


@pytest.mark.parametrize(
    "published",
    [
        "2020-01-01T00:00:00Z",
        "Sun, 22 Feb 2026 08:31:39 +0100",
        "",
        "2999-01-01T00:00:00Z",
        "yesterday",
        "2026-10-01T12:00:00",
    ],
)
@pytest.mark.parametrize("missing_policy", [False, True])
def test_strict_default_blocks_unsafe_new_and_persisted_items(client, published, missing_policy):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        feeds = service.load()
        if missing_policy:
            feeds[0].pop("allowOlderItems")
        feeds[0]["seen"].append("queued")
        feeds[0]["pending"] = [dict(entry("queued"), published=published)]
        service.save(feeds)
        service.fetch.return_value = [dict(entry("b"), published=published), entry("fresh")]
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 1
        assert service.add_item.call_args.args[2]["id"] == "fresh"
        saved = service.load()[0]
        assert saved["allowOlderItems"] is False
        assert saved["automatic"] is True
        assert saved["pending"] == []
        assert {"b", "queued", "fresh"} <= set(saved["seen"])
        # Rewriting a previously skipped date must not replay its identity.
        service.fetch.return_value = [entry("b")]
        await service.check(identifier, force=True)
        assert service.add_item.await_count == 1

    asyncio.run(run())


@pytest.mark.parametrize("allow_older", [False, True])
def test_policy_changes_fetch_baseline_clear_queue_and_never_replay(client, allow_older):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(allow_older=allow_older), agent))["feeds"][0]["id"]
        feeds = service.load()
        feeds[0]["pending"] = [entry("queued")]
        feeds[0]["seen"].append("queued")
        service.save(feeds)
        service.fetch.return_value = [entry("baseline")]
        options = module.FeedOptions(
            name="Movies", automatic=True, allowOlderItems=not allow_older, storageId="downloads"
        )
        service.fetch.side_effect = ValueError("private")
        with pytest.raises(ValueError):
            await service.configure(identifier, options, agent)
        assert service.load()[0]["pending"][0]["id"] == "queued"
        assert service.load()[0]["allowOlderItems"] is allow_older
        service.fetch.side_effect = None
        await service.configure(identifier, options, agent)
        assert service.load()[0]["pending"] == []
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        service.fetch.return_value = [entry("fresh")]
        await service.check(identifier, force=True)
        assert service.add_item.call_args.args[2]["id"] == "fresh"

    asyncio.run(run())


def test_policy_change_while_manual_does_not_activate(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(automatic=False), agent))["feeds"][0]["id"]
        service.fetch.return_value = [entry("baseline")]
        options = module.FeedOptions(
            name="Movies", automatic=False, allowOlderItems=True, storageId="downloads"
        )
        await service.configure(identifier, options, agent)
        assert service.load()[0]["automatic"] is False
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()

    asyncio.run(run())


def test_failed_fetch_filters_unsafe_saved_queue_and_preserves_eligible_retry(client):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        feeds = service.load()
        fresh = entry("fresh")
        feeds[0]["pending"] = [dict(entry("old"), published="2020-01-01T00:00:00Z"), fresh]
        feeds[0]["seen"].extend(["old", "fresh"])
        service.save(feeds)
        service.fetch.side_effect = ValueError("private")
        failed = await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        assert service.load()[0]["pending"] == [fresh]
        assert failed["feeds"][0]["error"]
        assert failed["feeds"][0]["checkedAt"] >= feeds[0]["checkedAt"]
        service.fetch.side_effect = None
        service.fetch.return_value = []
        await service.check(identifier, force=True)
        assert service.add_item.call_args.args[2]["id"] == "fresh"

    asyncio.run(run())


@pytest.mark.parametrize("activation", [True, float("nan"), float("inf"), 0, 999999999999])
def test_unreliable_activation_rebaselines_without_downloading(client, activation):
    async def run():
        service, agent = setup(client)
        identifier = (await service.create(body(), agent))["feeds"][0]["id"]
        feeds = service.load()
        feeds[0]["automaticSince"] = activation
        feeds[0]["pending"] = [entry("queued")]
        service.save(feeds)
        service.fetch.return_value = [entry("baseline")]
        await service.check(identifier, force=True)
        service.add_item.assert_not_awaited()
        assert service.load()[0]["pending"] == []

    asyncio.run(run())


def test_date_boundaries_and_timezone_aware_formats():
    since = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
    feed = {"automaticSince": since}
    for published in ("2026-10-01T00:00:00Z", "Thu, 01 Oct 2026 02:00:00 +0200"):
        assert module.automatic_eligible(feed, {"published": published}, since)
    assert not module.automatic_eligible(feed, {"published": "2026-10-01T00:00:01Z"}, since)
    assert not module.automatic_eligible(feed, {"published": "2026-09-30T23:59:59Z"}, since)
    for invalid in ("true", 1, None):
        with pytest.raises(ValueError):
            module.FeedOptions(name="Movies", storageId="downloads", allowOlderItems=invalid)
