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
from mediahub.update_monitor import UpdateMonitor


@pytest.fixture(params=["mediaseed", "mediavpn"])
def bundled_app(request):
    kind = request.param
    path = Path(__file__).parents[1] / "docker" / "bundled" / kind / "pyproject.toml"
    with path.open("rb") as stream:
        version = tomllib.load(stream)["project"]["version"]
    return kind, version


def managed_adapter(kind, installed, repository, access):
    svc = SimpleNamespace(
        release_credentials=SimpleNamespace(token=lambda: None),
        settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository=repository)),
    )
    svc.updates = UpdateMonitor(svc)
    svc.updates.source_access = access
    svc.updates.check_platform = AsyncMock(return_value={})
    manager = SimpleNamespace(
        svc=svc,
        containers=AsyncMock(
            return_value=[
                {
                    "State": {"Running": True},
                    "Config": {
                        "Labels": {
                            "com.docker.compose.service": "app",
                            "org.mediahub.app.version": installed,
                        }
                    },
                }
            ]
        ),
    )
    return ManagedAdapter(manager, "org.mediahub." + kind)


@pytest.mark.parametrize("latest,available", [("9.0.0", True), ("0.0.0", False)])
def test_app_checks_its_own_repository_independently(bundled_app, monkeypatch, latest, available):
    kind, installed = bundled_app
    check = AsyncMock(
        return_value={
            "repository": "miklas206/" + kind,
            "latestCommit": "a" * 40,
            "latestVersion": latest,
            "updateAvailable": True,
        }
    )
    monkeypatch.setattr("mediahub.app_updates.GitHubSourceProvider.check", check)
    access = SimpleNamespace(
        metadata=AsyncMock(side_effect=AssertionError("Core source must not be used"))
    )
    result = asyncio.run(managed_adapter(kind, installed, None, access).updateCheck())
    check.assert_awaited_once_with("miklas206/" + kind, None)
    access.metadata.assert_not_awaited()
    assert result["repository"] == "miklas206/" + kind
    assert result["installedVersion"] == installed
    assert result["latestVersion"] == latest
    assert result["supported"] is True
    assert result["updateAvailable"] is available


def test_http_bundle_metadata_is_pinned_to_checked_commit(bundled_app):
    kind, installed = bundled_app
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": "b" * 40})
        assert request.url.params["ref"] == "b" * 40
        return httpx.Response(
            200,
            json={
                "encoding": "base64",
                "content": base64.b64encode(b'[project]\nversion="0.1.5"').decode(),
            },
        )

    result = asyncio.run(
        GitHubSourceProvider(
            installed,
            transport=httpx.MockTransport(handler),
            project_path=f"docker/bundled/{kind}/pyproject.toml",
        ).check("owner/beta")
    )
    assert result["latestVersion"] == "0.1.5"
    assert calls == [
        "/repos/owner/beta/commits/main",
        f"/repos/owner/beta/contents/docker/bundled/{kind}/pyproject.toml",
    ]


@pytest.mark.parametrize(
    "path", ["../../secret", "/etc/passwd", "docker/bundled/unknown/pyproject.toml"]
)
def test_metadata_path_cannot_expand_beyond_reviewed_projects(path):
    with pytest.raises(ValueError, match="Unsupported"):
        GitHubSourceProvider("0.1.4", project_path=path)
