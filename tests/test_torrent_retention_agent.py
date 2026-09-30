import asyncio
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.rss_retention import RetentionRule

from agent.torrent_retention import RetentionService


def setup(tmp_path, action="remove_job"):
    root = tmp_path / "media"
    root.mkdir()
    policy = SimpleNamespace(workRoot=str(tmp_path))
    spec = SimpleNamespace()
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
        return Response([r for r in rows if not params or r["hash"] == params["hashes"]])

    client = SimpleNamespace(
        get=AsyncMock(side_effect=get), post=AsyncMock(return_value=Response({}))
    )

    @asynccontextmanager
    async def session():
        yield client, spec, policy

    torrents = SimpleNamespace(
        session=session,
        allowed_save_roots=lambda p, s: [PurePosixPath("/downloads")],
        writable_storage_roots=lambda p, s: [
            {"saveRoot": PurePosixPath("/downloads"), "root": root}
        ],
    )
    service = RetentionService(torrents)
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
