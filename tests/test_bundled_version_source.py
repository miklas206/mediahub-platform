import asyncio
import base64
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mediahub.managed_apps import ManagedAdapter
from mediahub.platform_source import GitHubSourceProvider


@pytest.fixture(params=["mediaseed", "mediavpn"])
def bundled_app(request):
    kind = request.param
    path = Path(__file__).parents[1] / "docker" / "bundled" / kind / "pyproject.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    return kind, version


def managed_adapter(kind, installed, repository, access):
    svc = SimpleNamespace(
        updates=SimpleNamespace(source_access=access, github_metadata=None),
        release_credentials=SimpleNamespace(token=lambda: None),
        settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository=repository)),
    )
    manager = SimpleNamespace(svc=svc, containers=AsyncMock(return_value=[{
        "State": {"Running": True}, "Config": {"Labels": {
            "com.docker.compose.service": "app", "org.mediahub.app.version": installed,
        }},
    }]))
    return ManagedAdapter(manager, "org.mediahub." + kind)


def test_app_version_uses_core_repository_and_its_scoped_deploy_key(bundled_app):
    kind, installed = bundled_app
    access = SimpleNamespace(metadata=AsyncMock(return_value=("a" * 40, b'[project]\nversion="0.2.0"\n')))
    result = asyncio.run(managed_adapter(kind, installed, "owner/main", access).updateCheck())
    access.metadata.assert_awaited_once_with("owner/main", project_path=f"docker/bundled/{kind}/pyproject.toml")
    assert result["repository"] == "owner/main"
    assert result["latestVersion"] == "0.2.0"
    assert result["installedVersion"] == installed
    assert result["bundledVersion"] == installed
    assert result["updateAvailable"] is False  # Delivered with Core.


def test_missing_update_repository_does_not_claim_a_verified_version(bundled_app):
    kind, installed = bundled_app
    access = SimpleNamespace(metadata=AsyncMock(side_effect=AssertionError("No repository configured")))
    result = asyncio.run(managed_adapter(kind, installed, None, access).updateCheck())
    access.metadata.assert_not_awaited()
    assert result["installedVersion"] == result["bundledVersion"] == installed
    assert result["latestVersion"] is None
    assert result["repository"] is None
    assert result["checkStatus"] == "unchecked"
    assert result["updateAvailable"] is False
    assert result["message"] == "Choose the MediaHub update repository before checking app versions."


def test_older_upstream_bundle_is_not_described_as_a_newer_app(bundled_app):
    kind, installed = bundled_app
    access = SimpleNamespace(metadata=AsyncMock(return_value=("c" * 40, b'[project]\nversion="0.0.0"\n')))
    result = asyncio.run(managed_adapter(kind, installed, "owner/beta", access).updateCheck())
    access.metadata.assert_awaited_once_with("owner/beta", project_path=f"docker/bundled/{kind}/pyproject.toml")
    assert result["installedVersion"] == result["bundledVersion"] == installed
    assert result["latestVersion"] == "0.0.0"
    assert result["checkStatus"] == "checked"
    assert result["updateAvailable"] is False
    assert "newer" not in result["message"].lower()
    assert "updated automatically with MediaHub Core" in result["message"]


def test_http_bundle_metadata_is_pinned_to_checked_commit(bundled_app):
    kind, installed = bundled_app
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "b" * 40})
        assert request.url.params["ref"] == "b" * 40
        return httpx.Response(200, json={"encoding": "base64", "content": base64.b64encode(b'[project]\nversion="0.1.5"').decode()})

    result = asyncio.run(GitHubSourceProvider(installed, transport=httpx.MockTransport(handler),
        project_path=f"docker/bundled/{kind}/pyproject.toml").check("owner/beta"))
    assert result["latestVersion"] == "0.1.5"
    assert calls == ["/repos/owner/beta/commits/main", f"/repos/owner/beta/contents/docker/bundled/{kind}/pyproject.toml"]


@pytest.mark.parametrize("path", ["../../secret", "/etc/passwd", "docker/bundled/unknown/pyproject.toml"])
def test_metadata_path_cannot_expand_beyond_reviewed_projects(path):
    with pytest.raises(ValueError, match="Unsupported"):
        GitHubSourceProvider("0.1.4", project_path=path)
