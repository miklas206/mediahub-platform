import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.apps.seedbox_daily import AddTorrent, TorrentRetention
from mediahub.errors import DomainError
from mediahub.rss_retention import RetentionRule

from agent.seedbox_torrents import TorrentService
from agent.torrent_retention import RetentionService


def setup(tmp_path, action="remove_job"):
    root = tmp_path / "media"
    root.mkdir()
    policy = SimpleNamespace(
        workRoot=str(tmp_path),
        paths=SimpleNamespace(downloads=str(root), extraStorage=[]),
    )
    spec = SimpleNamespace(downloadsStorageId="downloads")
    row = dict(
        hash="a" * 40,
        added_on=123,
        save_path="/downloads",
        tags="mediahub-cleanup-test",
        state="stalledUP",
        progress=1,
        size=100,
        uploaded=200,
        seeding_time=48 * 3600,
    )
    rows = [row]
    files = {row["hash"]: [{"name": "movie.mkv"}]}
    (root / "movie.mkv").write_bytes(b"example")

    class Response:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    async def get(path, params=None):
        if path.endswith("/files"):
            return Response(files[params["hash"]])
        return Response(
            [
                r
                for r in rows
                if not params or "hashes" not in params or r["hash"] == params["hashes"]
            ]
        )

    async def post(path, data):
        if path.endswith("/addTags"):
            for item in rows:
                if item["hash"] == data["hashes"]:
                    item["tags"] += "," + data["tags"]
        return Response({})

    client = SimpleNamespace(get=AsyncMock(side_effect=get), post=AsyncMock(side_effect=post))

    @asynccontextmanager
    async def session(mutate=False):
        yield client, spec, policy

    torrents = TorrentService(None)
    torrents.session = session
    service = torrents.retention
    rule = RetentionRule(mode="both", action=action)
    service.save(
        policy,
        {
            row["hash"]: {
                "tag": "mediahub-cleanup-test",
                "addedOn": 123,
                "savePath": "/downloads",
                "rule": rule.model_dump(),
                "error": "",
            }
        },
    )
    return service, client, policy, spec, row, rows, files, root


@pytest.mark.parametrize(
    "popularity", [0, 0.125, 12, None, "1.5", True, float("nan"), float("inf"), -float("inf")]
)
def test_torrent_list_forwards_only_finite_numeric_popularity(tmp_path, popularity):
    service, client, policy, spec, row, *_ = setup(tmp_path)
    row.update(
        popularity=popularity,
        tracker="https://tracker.invalid/secret-passkey",
        magnet_uri="magnet:?private-token",
        password="private-password",
    )
    result = asyncio.run(service.torrents.list())
    item = result["items"][0]
    assert item["popularity"] == (
        popularity if type(popularity) in (int, float) and popularity in (0, 0.125, 12) else None
    )
    assert item["seeding_time"] == row["seeding_time"]
    assert item["uploaded"] == row["uploaded"]
    for key in ("tracker", "magnet_uri", "password", "save_path", "tags"):
        assert key not in item
    assert "private-" not in str(result)
    assert "secret-passkey" not in str(result)


def test_torrent_list_missing_popularity_stays_unknown(tmp_path):
    service, *_ = setup(tmp_path)
    assert asyncio.run(service.torrents.list())["items"][0]["popularity"] is None


@pytest.mark.parametrize("action,delete", [("remove_job", "false"), ("delete_files", "true")])
def test_cleanup_uses_explicit_action_and_keeps_rule_until_removal_confirmed(
    tmp_path, action, delete
):
    service, client, policy, spec, row, rows, files, root = setup(tmp_path, action)
    asyncio.run(service.sweep())
    client.post.assert_awaited_once_with(
        "/api/v2/torrents/delete", data={"hashes": row["hash"], "deleteFiles": delete}
    )
    assert row["hash"] in service.load(policy)
    rows.clear()
    asyncio.run(service.sweep())
    assert service.load(policy) == {}


@pytest.mark.parametrize(
    "change",
    [
        {"tags": ""},
        {"added_on": 456},
        {"save_path": "/elsewhere"},
        {"progress": 0.5},
        {"state": "checkingUP"},
        {"uploaded": 199},
    ],
)
def test_changed_job_incomplete_or_unmet_rule_never_deletes(tmp_path, change):
    service, client, policy, spec, row, *_ = setup(tmp_path, "delete_files")
    row.update(change)
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()


def test_files_shared_with_another_torrent_block_deletion(tmp_path):
    service, client, policy, spec, row, rows, files, root = setup(tmp_path, "delete_files")
    other = dict(row, hash="b" * 40)
    rows.append(other)
    files[other["hash"]] = files[row["hash"]]
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()
    assert "blocked" in service.load(policy)[row["hash"]]["error"]


@pytest.mark.parametrize(
    "name", ["../outside", "/etc/passwd", "folder/../../outside", "folder\\outside"]
)
def test_unsafe_file_paths_block_deletion(tmp_path, name):
    service, client, policy, spec, row, rows, files, root = setup(tmp_path, "delete_files")
    files[row["hash"]] = [{"name": name}]
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()


def test_deleted_job_hash_reused_without_tag_is_not_cleaned(tmp_path):
    service, client, policy, spec, row, *_ = setup(tmp_path)
    row["tags"] = "unrelated"
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()


def test_disable_removes_rule_and_register_uses_unique_job_tag(tmp_path):
    service, client, policy, spec, row, *_ = setup(tmp_path)
    asyncio.run(service.register(client, policy, spec, row, RetentionRule()))
    assert service.load(policy) == {}
    asyncio.run(service.register(client, policy, spec, row, RetentionRule(mode="ratio")))
    record = service.load(policy)[row["hash"]]
    assert record["tag"].startswith("mediahub-cleanup-")
    assert record["tag"] != "mediahub-cleanup-test"
    assert client.post.call_args.args[0].endswith("/addTags")


def test_unknown_other_torrent_metadata_prevents_file_deletion(tmp_path):
    service, client, policy, spec, row, rows, files, root = setup(tmp_path, "delete_files")
    rows.append(dict(row, hash="b" * 40))
    files["b" * 40] = []
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()


def test_symlink_resolution_blocks_deletion(tmp_path, monkeypatch):
    from pathlib import Path

    service, client, policy, spec, row, rows, files, root = setup(tmp_path, "delete_files")
    original = Path.resolve

    def resolve(path, *a, **kw):
        if path == root / "movie.mkv":
            return tmp_path / "outside.mkv"
        return original(path, *a, **kw)

    monkeypatch.setattr(Path, "resolve", resolve)
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()


@pytest.mark.parametrize("rule", [RetentionRule(), RetentionRule(mode="ratio", uploadRatio=9)])
def test_individual_override_survives_reload_and_repeated_feed_add(tmp_path, rule):
    service, client, policy, spec, row, *_ = setup(tmp_path, "delete_files")
    torrents = service.torrents
    result = asyncio.run(
        torrents.configure_retention(TorrentRetention(hash=row["hash"], retention=rule))
    )
    assert result == {"state": "saved"}
    record = service.load(policy)[row["hash"]]
    assert record["override"] is True
    assert record["rule"] == rule.model_dump()
    assert service.tagged(row, record)

    reloaded = RetentionService(torrents)
    torrents.retention = reloaded
    item = asyncio.run(torrents.list())["items"][0]
    assert item["retentionOverride"] is True
    assert item["retention"] == rule.model_dump()
    client.post.reset_mock()
    asyncio.run(reloaded.sweep())
    client.post.assert_not_awaited()

    feed_rule = RetentionRule(mode="either", action="delete_files")
    # Both the real duplicate-add path and defensive registration preserve the override.
    added = asyncio.run(
        torrents.add(
            AddTorrent(
                magnet="magnet:?xt=urn:btih:" + row["hash"],
                storageId="downloads",
                retention=feed_rule,
            )
        )
    )
    assert added == {"state": "already_present", "hash": row["hash"], "started": False}
    asyncio.run(reloaded.register(client, policy, spec, row, feed_rule))
    assert reloaded.load(policy)[row["hash"]] == record
    client.post.assert_not_awaited()


@pytest.mark.parametrize("mode", ["time", "ratio"])
@pytest.mark.parametrize("action", ["remove_job", "delete_files"])
def test_cleanup_uses_only_new_individual_threshold_and_action(tmp_path, mode, action):
    old_action = "delete_files" if action == "remove_job" else "remove_job"
    service, client, policy, spec, row, *_ = setup(tmp_path, old_action)
    rule = RetentionRule(mode=mode, seedHours=72, uploadRatio=3, action=action)
    asyncio.run(
        service.torrents.configure_retention(TorrentRetention(hash=row["hash"], retention=rule))
    )
    client.post.reset_mock()
    # The feed's old threshold is already reached; the individual threshold is not.
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()
    row.update(seeding_time=72 * 3600, uploaded=300)
    asyncio.run(service.sweep())
    client.post.assert_awaited_once_with(
        "/api/v2/torrents/delete",
        data={
            "hashes": row["hash"],
            "deleteFiles": "true" if action == "delete_files" else "false",
        },
    )


@pytest.mark.parametrize("mode", ["disabled", "ratio"])
@pytest.mark.parametrize(
    "change", [{"added_on": 456}, {"tags": "unrelated"}, {"save_path": "/downloads/other"}]
)
def test_replaced_or_changed_job_does_not_inherit_override(tmp_path, mode, change):
    service, client, policy, spec, row, *_ = setup(tmp_path)
    asyncio.run(
        service.torrents.configure_retention(
            TorrentRetention(hash=row["hash"], retention=RetentionRule(mode=mode))
        )
    )
    row.update(change)
    item = asyncio.run(service.torrents.list())["items"][0]
    assert item["retention"] is None
    assert item["retentionOverride"] is False
    client.post.reset_mock()
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()

    # A stale record cannot suppress the rule for a newly admitted job with this hash.
    feed_rule = RetentionRule(mode="time", seedHours=96)
    asyncio.run(service.register(client, policy, spec, row, feed_rule))
    item = asyncio.run(service.torrents.list())["items"][0]
    assert item["retention"] == feed_rule.model_dump()
    assert item["retentionOverride"] is False


@pytest.mark.parametrize(
    "change,code",
    [
        ({"added_on": 0}, "retention_identity"),
        ({"save_path": "/elsewhere"}, "retention_storage"),
        ({"save_path": "/downloads/../elsewhere"}, "retention_storage"),
    ],
)
def test_never_override_still_requires_verified_identity_and_storage(tmp_path, change, code):
    service, client, policy, spec, row, *_ = setup(tmp_path)
    previous = service.load(policy)
    row.update(change)
    with pytest.raises(DomainError) as error:
        asyncio.run(
            service.torrents.configure_retention(
                TorrentRetention(hash=row["hash"], retention=RetentionRule())
            )
        )
    assert error.value.code == code
    assert service.load(policy) == previous
    client.post.assert_not_awaited()


def test_legacy_feed_rule_and_unconfigured_torrent_are_not_overrides(tmp_path):
    service, client, policy, spec, row, *_ = setup(tmp_path)
    item = asyncio.run(service.torrents.list())["items"][0]
    assert item["retentionOverride"] is False
    assert item["retention"] == RetentionRule(mode="both").model_dump()
    service.save(policy, {})
    item = asyncio.run(service.torrents.list())["items"][0]
    assert item["retentionOverride"] is False
    assert item["retention"] is None


def test_unconfirmed_override_tag_cannot_authorize_cleanup(tmp_path):
    service, client, policy, spec, row, *_ = setup(tmp_path, "delete_files")
    client.post.side_effect = RuntimeError("qBittorrent unavailable")
    with pytest.raises(RuntimeError):
        asyncio.run(
            service.torrents.configure_retention(
                TorrentRetention(hash=row["hash"], retention=RetentionRule(mode="ratio"))
            )
        )
    client.post.reset_mock()
    item = asyncio.run(service.torrents.list())["items"][0]
    assert item["retentionOverride"] is False
    assert item["retention"] is None
    asyncio.run(service.sweep())
    client.post.assert_not_awaited()
