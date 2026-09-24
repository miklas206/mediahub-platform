import asyncio
from types import SimpleNamespace

import httpx
import pytest
from mediahub.errors import DomainError
from mediahub.platform_updates import GitHubReleaseProvider
from mediahub.release_credentials import GitHubReleaseCredentials


def response(payload, status=200):
    return httpx.MockTransport(lambda request: httpx.Response(status, json=payload))


def test_unconfigured_release_provider_is_offline_and_honest():
    data = asyncio.run(GitHubReleaseProvider("0.2.0").check(None))
    assert data["configured"] is False
    assert data["updateAvailable"] is False
    assert data["installReady"] is False


def test_release_check_requires_digest_identified_manifest():
    payload = {
        "tag_name": "v0.3.0",
        "html_url": "https://github.com/example/mediahub/releases/tag/v0.3.0",
        "published_at": "2026-09-24T10:00:00Z",
        "assets": [
            {
                "name": "mediahub-release.json",
                "digest": "sha256:" + "a" * 64,
                "browser_download_url": "https://github.com/example/mediahub/releases/download/v0.3.0/mediahub-release.json",
                "url": "https://api.github.com/repos/example/mediahub/releases/assets/123",
            }
        ],
    }
    data = asyncio.run(GitHubReleaseProvider("0.2.0", response(payload)).check("example/mediahub"))
    assert data["updateAvailable"] is True
    assert data["manifest"]["digest"] == "sha256:" + "a" * 64
    assert data["manifest"]["apiUrl"].endswith("/assets/123")
    assert data["installReady"] is False


def test_release_check_rejects_invalid_versions_without_leaking_payload():
    with pytest.raises(DomainError) as error:
        asyncio.run(
            GitHubReleaseProvider("0.2.0", response({"tag_name": "secret-invalid"})).check(
                "example/mediahub"
            )
        )
    assert error.value.code == "invalid_release_metadata"
    assert "secret-invalid" not in error.value.message


def test_private_release_check_uses_bearer_without_returning_it():
    token = "github_pat_private_read_only_123456789"

    def handler(request):
        assert request.headers["authorization"] == f"Bearer {token}"
        return httpx.Response(
            200,
            json={
                "tag_name": "v0.2.0",
                "html_url": "https://github.com/example/mediahub/releases/tag/v0.2.0",
                "published_at": "2026-09-24T10:00:00Z",
                "assets": [],
            },
        )

    data = asyncio.run(
        GitHubReleaseProvider("0.2.0", httpx.MockTransport(handler)).check(
            "example/mediahub", token
        )
    )
    assert data["privateAccessConfigured"] is True
    assert token not in str(data)


def test_release_credentials_are_encrypted_replaceable_and_removable(tmp_path):
    service = GitHubReleaseCredentials(SimpleNamespace(data_dir=tmp_path.resolve()))
    first = "github_pat_private_read_only_123456789"
    second = "github_pat_private_read_only_987654321"
    assert service.status() == {"configured": False}
    service.save(first)
    assert service.token() == first
    service.save(second)
    assert service.token() == second
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert first.encode() not in path.read_bytes()
            assert second.encode() not in path.read_bytes()
    service.remove()
    assert service.status() == {"configured": False}


def test_private_release_credentials_api_never_returns_or_persists_plaintext(logged_in):
    token = "github_pat_private_read_only_123456789"
    response = logged_in.put("/api/v1/updates/platform/credentials", json={"token": token})
    assert response.status_code == 200
    assert response.json()["data"] == {"configured": True}
    assert token not in response.text
    status = logged_in.get("/api/v1/updates/platform/credentials")
    assert status.json()["data"] == {"configured": True}
    for path in logged_in.app.state.services.config.data_dir.rglob("*"):
        if path.is_file():
            assert token.encode() not in path.read_bytes()
    removed = logged_in.delete("/api/v1/updates/platform/credentials")
    assert removed.json()["data"] == {"configured": False}
