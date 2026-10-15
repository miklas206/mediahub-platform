import asyncio
import io
import json
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.app_updates import AppUpdates, extract_app


def archive_at(path, entries):
    with tarfile.open(path, "w:gz") as archive:
        for name, body, link in entries:
            member = tarfile.TarInfo(name)
            if link:
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))


@pytest.mark.parametrize("bad", ["root/../outside", "/outside", "root/mediaseed/link"])
def test_archive_rejects_traversal_and_links(tmp_path, bad):
    archive = tmp_path / "app.tar.gz"
    archive_at(archive, [(bad, b"x", bad.endswith("link"))])
    with pytest.raises(ValueError):
        extract_app(archive, tmp_path / "source", "mediaseed", "1.0.0")
    assert not (tmp_path / "outside").exists()


def test_archive_extracts_only_reviewed_inputs_and_verifies_identity(tmp_path):
    archive = tmp_path / "app.tar.gz"
    archive_at(
        archive,
        [
            ("root/pyproject.toml", b'[project]\nname="mediaseed"\nversion="1.0.0"', False),
            ("root/Dockerfile", b"FROM scratch", False),
            ("root/.env", b"sentinel", False),
            ("root/mediaseed/static/index.html", b"hello", False),
        ],
    )
    extract_app(archive, tmp_path / "source", "mediaseed", "1.0.0")
    assert not (tmp_path / "source/.env").exists()
    assert (tmp_path / "source/mediaseed/static/index.html").read_text() == "hello"
    with pytest.raises(ValueError, match="identity"):
        extract_app(archive, tmp_path / "mismatch", "mediaseed", "2.0.0")


@pytest.mark.parametrize(
    "helper_running,exit_code,version,expected",
    [
        (True, 0, "1.0.0", "running"),
        (False, 0, "1.0.0", "succeeded"),
        (False, 1, "1.0.0", "interrupted"),
        (False, 0, "0.1.0", "interrupted"),
    ],
)
def test_restart_recovery_waits_for_helper_and_verifies_selected_version(
    tmp_path, helper_running, exit_code, version, expected
):
    labels = {
        "com.docker.compose.service": "app",
        "org.mediahub.app.commit": "a" * 40,
        "org.mediahub.app.version": version,
    }
    helper = {
        "Config": {"Labels": {"org.mediahub.app-update": "operation"}},
        "State": {"Running": helper_running, "ExitCode": exit_code},
    }
    manager = SimpleNamespace(
        svc=SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path)),
        containers=AsyncMock(return_value=[{"Config": {"Labels": labels}}]),
        docker=AsyncMock(return_value=helper),
    )
    updater = AppUpdates(manager)
    path = updater.path("mediaseed")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "state": "running",
                "operationId": "operation",
                "commit": "a" * 40,
                "toVersion": "1.0.0",
            }
        )
    )
    result = asyncio.run(updater.status(SimpleNamespace(package="org.mediahub.mediaseed")))
    assert result["state"] == expected


@pytest.mark.parametrize("helper_failure", [False, True])
def test_pinned_update_runs_selected_helper_and_persists_verified_result(
    tmp_path, monkeypatch, helper_failure
):
    from mediahub.errors import DomainError

    updates = []
    commit = "a" * 40
    labels = {
        "com.docker.compose.service": "app",
        "org.mediahub.app.version": "1.0.0",
        "org.mediahub.app.commit": commit,
    }

    async def helper(update):
        updates.append(update)

    dependencies = SimpleNamespace(
        require_ready=lambda: None,
        _run=helper,
        message="Synthetic build failure" if helper_failure else None,
    )
    svc = SimpleNamespace(
        config=SimpleNamespace(data_dir=tmp_path),
        app_dependencies=dependencies,
        release_credentials=SimpleNamespace(token=lambda: None),
    )
    manager = SimpleNamespace(
        svc=svc,
        lock=asyncio.Lock(),
        containers=AsyncMock(return_value=[{"Config": {"Labels": labels}}]),
    )

    async def download(client, repository, target_commit, archive, token):
        assert repository == "miklas206/mediaseed" and target_commit == commit
        archive_at(
            archive,
            [
                ("root/pyproject.toml", b'[project]\nname="mediaseed"\nversion="1.0.0"', False),
                ("root/Dockerfile", b"FROM scratch", False),
            ],
        )

    monkeypatch.setattr("mediahub.app_updates.download_source", download)
    updater = AppUpdates(manager)
    adapter = SimpleNamespace(package="org.mediahub.mediaseed")
    checked = {
        "updateAvailable": True,
        "repository": "miklas206/mediaseed",
        "latestCommit": commit,
        "latestVersion": "1.0.0",
    }

    async def scenario():
        first = await updater.start(adapter, checked)
        with pytest.raises(DomainError, match="active update"):
            await updater.start(adapter, checked)
        await updater.tasks["mediaseed"]
        return first

    job = asyncio.run(scenario())
    saved = updater.operation("mediaseed")
    assert saved["operationId"] == job["operationId"]
    assert saved["state"] == ("failed" if helper_failure else "succeeded")
    assert len(updates) == 1 and updates[0]["kind"] == "mediaseed"
    assert updates[0]["source"].startswith("app-updates/mediaseed/")
    assert not updater.path("mediavpn").exists()
