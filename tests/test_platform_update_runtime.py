import asyncio
import hashlib
import json
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
