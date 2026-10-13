import asyncio
import json

import httpx
import pytest
from mediahub.errors import DomainError

from agent.install_images import publisher_reference, pull_latest


def test_installed_seedbox_pins_survive_runtime_reload_without_changing_storage(tmp_path):
    from types import SimpleNamespace

    from test_seedbox_plan import paths, spec

    from agent.install_files import save_json
    from agent.install_images import resolved_seedbox_policy
    from agent.seedbox_driver import ScopedDriver

    policy = SimpleNamespace(workRoot=str(tmp_path), hostId=spec().hostId,
                             downloadsStorageId=spec().downloadsStorageId, paths=paths())
    pins = {"vpnImage": "qmcgaw/gluetun@sha256:" + "c" * 64,
            "torrentImage": "lscr.io/linuxserver/qbittorrent@sha256:" + "d" * 64}
    save_json(tmp_path / "installation.json", {"installation": spec().model_dump(), "resolvedImages": pins})
    runtime = ScopedDriver(SimpleNamespace(policy=lambda: policy), None, None)
    resolved, _ = runtime.binding()
    assert resolved.paths.vpnImage == pins["vpnImage"]
    assert resolved.paths.downloads == paths().downloads
    with pytest.raises(ValueError):
        resolved_seedbox_policy(policy, {**pins, "downloads": "/wrong"})


def test_warm_cache_still_pulls_upstream_and_resolves_new_digest(monkeypatch, tmp_path):
    calls = []
    generation = 0
    original = httpx.AsyncClient

    def handler(request):
        nonlocal generation
        calls.append(request)
        if request.method == "POST":
            generation += 1
            assert dict(request.url.params) == {"fromImage": "jellyfin/jellyfin", "tag": "latest"}
            return httpx.Response(200, text=json.dumps({"status": "Already exists"}) + "\n")
        return httpx.Response(200, json={
            "Id": "sha256:" + str(generation) * 64,
            "RepoDigests": ["docker.io/jellyfin/jellyfin@sha256:" + str(generation) * 64],
        })

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **{**kwargs, "transport": httpx.MockTransport(handler)},
    ))
    for number in (1, 2):
        image = asyncio.run(pull_latest("unused", "jellyfin/jellyfin"))
        assert publisher_reference(image, "jellyfin/jellyfin").endswith(str(number) * 64)
    assert [request.method for request in calls] == ["POST", "GET", "POST", "GET"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("body", [
    '{"error":"private registry detail"}',
    '{"errorDetail":{"message":"private registry detail"}}',
    'broken JSON', '[]', 'x' * 65537,
], ids=["error", "error-detail", "invalid-json", "invalid-type", "oversize"])
def test_failed_pull_does_not_use_cached_image(monkeypatch, body):
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=body)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        **{**kwargs, "transport": httpx.MockTransport(handler)},
    ))
    with pytest.raises(DomainError) as error:
        asyncio.run(pull_latest("unused", "jellyfin/jellyfin"))
    assert error.value.code == "install_image_download_failed"
    assert "private registry detail" not in str(error.value)
    assert len(calls) == 1


def test_publisher_verification_rejects_foreign_digest_and_arbitrary_repository():
    image = {"Id": "sha256:" + "a" * 64, "RepoDigests": ["attacker/image@sha256:" + "b" * 64]}
    with pytest.raises(DomainError):
        publisher_reference(image, "jellyfin/jellyfin")
    with pytest.raises(DomainError):
        asyncio.run(pull_latest("unused", "attacker/image"))
