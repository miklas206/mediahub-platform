import asyncio
import hashlib
import json
import os
from types import SimpleNamespace

import httpx
import mediahub.platform_update_runtime as runtime_module
import pytest
from mediahub.errors import DomainError
from mediahub.platform_update_runtime import PlatformUpdateRuntime, ReleaseManifest


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def release_fixture():
    core = b"bounded-core-image-bundle"
    agent = b"bounded-agent-image-bundle"
    manifest = {
        "schemaVersion": 1,
        "version": "0.5.0",
        "images": {
            "core": "ghcr.io/example/mediahub-core@sha256:" + "a" * 64,
            "agent": "ghcr.io/example/mediahub-agent@sha256:" + "b" * 64,
        },
        "bundles": {
            "core": {"name": "mediahub-core-image.tar.gz", "sha256": digest(core)},
            "agent": {"name": "mediahub-agent-image.tar.gz", "sha256": digest(agent)},
        },
        "updatePolicy": {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        },
    }
    encoded_manifest = (json.dumps(manifest) + "\n").encode()
    contents = {
        "mediahub-release.json": encoded_manifest,
        "mediahub-core-image.tar.gz": core,
        "mediahub-agent-image.tar.gz": agent,
    }
    assets = {
        name: {
            "name": name,
            "digest": "sha256:" + digest(value),
            "size": len(value),
            "downloadUrl": f"https://github.com/example/mediahub/releases/download/v0.5.0/{name}",
            "apiUrl": f"https://api.github.com/repos/example/mediahub/releases/assets/{index}",
        }
        for index, (name, value) in enumerate(contents.items(), start=1)
    }
    return contents, {
        "updateAvailable": True,
        "latestVersion": "0.5.0",
        "assets": assets,
    }


def source_fixture(repository="example/mediahub"):
    source = b"test-source-archive"
    manifest = {
        "schemaVersion": 2,
        "version": "0.5.0",
        "source": {
            "name": "mediahub-source.tar.gz",
            "sha256": digest(source),
            "repository": repository,
            "commit": "a" * 40,
        },
        "updatePolicy": {
            "transactional": True,
            "rollbackRequired": True,
            "mediaIsOutOfScope": True,
        },
    }
    contents = {
        "mediahub-source-release.json": json.dumps(manifest).encode(),
        "mediahub-source.tar.gz": source,
    }
    assets = {
        name: {
            "name": name,
            "size": len(value),
            "digest": "sha256:" + digest(value),
            "apiUrl": f"https://api.github.com/repos/example/mediahub/releases/assets/{index}",
        }
        for index, (name, value) in enumerate(contents.items(), 1)
    }
    return contents, {
        "updateAvailable": True,
        "latestVersion": "0.5.0",
        "repository": "example/mediahub",
        "assets": assets,
    }


def test_source_requires_upgraded_host_and_stages_only_source(tmp_path, monkeypatch):
    contents, release = source_fixture()
    requested = []

    def handler(request):
        name = list(contents)[int(request.url.path.rsplit("/", 1)[1]) - 1]
        requested.append(name)
        return httpx.Response(200, content=contents[name])

    updater, spool = runtime(tmp_path, monkeypatch, handler)
    assert not updater.ready(release)
    with pytest.raises(DomainError, match="source-build support"):
        asyncio.run(updater.install(release))
    monkeypatch.setattr(PlatformUpdateRuntime, "source_available", property(lambda self: True))
    assert updater.ready(release)

    async def stage():
        await updater.install(release)
        await updater.task

    asyncio.run(stage())
    assert updater.status()["state"] == "staged"
    assert requested == list(contents)
    request = json.loads((spool / "request.json").read_text())
    assert request["schemaVersion"] == 2
    assert [step["id"] for step in updater.status()["steps"]] == [
        "download",
        "build",
        "backup",
        "replace",
        "verify",
    ]
    for path in spool.rglob("*"):
        if path.is_file():
            assert b"github_pat_" not in path.read_bytes()


@pytest.mark.parametrize("wrong_repository,tamper", [(True, False), (False, True)])
def test_source_rejects_wrong_repository_or_digest(tmp_path, monkeypatch, wrong_repository, tamper):
    contents, release = source_fixture("attacker/repo" if wrong_repository else "example/mediahub")

    def handler(request):
        name = list(contents)[int(request.url.path.rsplit("/", 1)[1]) - 1]
        value = b"tampered" if tamper and name.endswith("tar.gz") else contents[name]
        return httpx.Response(200, content=value)

    updater, spool = runtime(tmp_path, monkeypatch, handler)
    monkeypatch.setattr(PlatformUpdateRuntime, "source_available", property(lambda self: True))

    async def stage():
        await updater.install(release)
        await updater.task

    asyncio.run(stage())
    assert updater.status()["state"] == "failed"
    assert not (spool / "request.json").exists()


def runtime(tmp_path, monkeypatch, handler, token="github_pat_test_read_only_123456789"):
    spool = tmp_path / "updates"
    spool.mkdir(mode=0o700)
    spool.chmod(0o700)
    monkeypatch.setattr(
        runtime_module.os,
        "geteuid",
        lambda: spool.stat().st_uid,
        raising=False,
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        runtime_module.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    services = SimpleNamespace(
        config=SimpleNamespace(platform_update_spool=spool),
        release_credentials=SimpleNamespace(token=lambda: token),
    )
    updater = PlatformUpdateRuntime(services)
    # Windows does not preserve POSIX directory mode bits. The production check
    # is exercised on Linux CI; these tests focus on staging and verification.
    monkeypatch.setattr(updater, "_available_root", lambda: spool)
    return updater, spool


def test_release_manifest_rejects_swapped_bundles_and_unknown_schema():
    contents, _ = release_fixture()
    value = json.loads(contents["mediahub-release.json"])
    value["bundles"]["core"]["name"] = "mediahub-agent-image.tar.gz"
    with pytest.raises(ValueError):
        ReleaseManifest.model_validate(value)
    value = json.loads(contents["mediahub-release.json"])
    value["schemaVersion"] = 2
    with pytest.raises(ValueError):
        ReleaseManifest.model_validate(value)


def test_verified_assets_are_staged_without_persisting_the_github_token(tmp_path, monkeypatch):
    contents, release = release_fixture()
    token = "github_pat_test_read_only_123456789"

    def handler(request):
        assert request.headers["authorization"] == f"Bearer {token}"
        asset_id = int(request.url.path.rsplit("/", 1)[1])
        name = list(contents)[asset_id - 1]
        return httpx.Response(200, content=contents[name])

    updater, spool = runtime(tmp_path, monkeypatch, handler, token)

    async def stage():
        started = await updater.install(release)
        assert started["state"] == "downloading"
        await updater.task

    asyncio.run(stage())
    status = updater.status()
    assert status["state"] == "staged"
    assert status["progress"] == 60
    request = json.loads((spool / "request.json").read_text(encoding="utf-8"))
    assert request["toVersion"] == "0.5.0"
    assert request["stage"] == f"staging/{request['operationId']}"
    for path in spool.rglob("*"):
        if path.is_file():
            assert token.encode() not in path.read_bytes()


def test_digest_mismatch_fails_closed_before_host_request(tmp_path, monkeypatch):
    contents, release = release_fixture()

    def handler(request):
        asset_id = int(request.url.path.rsplit("/", 1)[1])
        name = list(contents)[asset_id - 1]
        value = b"tampered" if name == "mediahub-core-image.tar.gz" else contents[name]
        return httpx.Response(200, content=value)

    updater, spool = runtime(tmp_path, monkeypatch, handler)

    async def stage():
        await updater.install(release)
        await updater.task

    asyncio.run(stage())
    assert updater.status()["state"] == "failed"
    assert not (spool / "request.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows does not preserve POSIX mode bits")
def test_unsafe_staging_permissions_fail_with_actionable_message(tmp_path, monkeypatch):
    contents, release = release_fixture()

    def handler(request):
        return httpx.Response(200, content=next(iter(contents.values())))

    updater, spool = runtime(tmp_path, monkeypatch, handler)
    staging = spool / "staging"
    staging.mkdir(mode=0o755)
    staging.chmod(0o755)

    async def stage():
        await updater.install(release)
        await updater.task

    asyncio.run(stage())
    status = updater.status()
    assert status["state"] == "failed"
    assert "ownership or permissions" in status["message"]
    assert not (spool / "request.json").exists()


def test_install_requires_complete_release_and_available_host_updater(tmp_path, monkeypatch):
    contents, release = release_fixture()

    def handler(request):
        return httpx.Response(200, content=next(iter(contents.values())))

    updater, _ = runtime(tmp_path, monkeypatch, handler)
    incomplete = {
        **release,
        "assets": {"mediahub-release.json": release["assets"]["mediahub-release.json"]},
    }
    with pytest.raises(DomainError) as failure:
        asyncio.run(updater.install(incomplete))
    assert failure.value.code == "platform_release_incomplete"

    unavailable = PlatformUpdateRuntime(
        SimpleNamespace(
            config=SimpleNamespace(platform_update_spool=None),
            release_credentials=SimpleNamespace(token=lambda: None),
        )
    )
    with pytest.raises(DomainError) as failure:
        asyncio.run(unavailable.install(release))
    assert failure.value.code == "platform_updater_unavailable"
