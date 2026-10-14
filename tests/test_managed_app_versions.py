import asyncio
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.managed_apps import ManagedAdapter
from mediahub.update_monitor import UpdateMonitor

BUNDLED_VERSION = tomllib.loads((Path(__file__).resolve().parents[1] / "docker/bundled/mediaseed/pyproject.toml").read_text())["project"]["version"]


def row(service, running, version=None, clone=False):
    labels = {"com.docker.compose.service": service}
    if version:
        labels["org.mediahub.app.version"] = version
    if clone:
        labels["org.mediahub.mediavpn.seedbox"] = "mediaseed"
    return {"Config": {"Labels": labels}, "State": {"Running": running}}


@pytest.mark.parametrize("clone", [False, True])
def test_stopped_source_and_completed_initializer_do_not_hide_healthy_vpn_client(clone):
    rows = [row("app", True), row("client-init", False), row("qbittorrent", False)]
    if clone:
        rows.append(row("vpn-client", True, clone=True))
    adapter = ManagedAdapter(
        SimpleNamespace(containers=AsyncMock(return_value=rows)), "org.mediahub.mediaseed"
    )
    assert asyncio.run(adapter.health()).status == ("healthy" if clone else "unknown")
    rows[0]["State"]["Running"] = False
    assert asyncio.run(adapter.health()).status == "unknown"


@pytest.mark.parametrize(
    "version,preparation,status",
    [(BUNDLED_VERSION, "ready", "checked"), (None, "failed", "failed"), ("0.1.1", "ready", "unchecked"), ("0.1.0", "ready", "unchecked")],
)
def test_bundled_checks_use_running_app_version_and_report_preparation_failure(
    version, preparation, status, monkeypatch
):
    upstream = AsyncMock(return_value={"latestVersion": BUNDLED_VERSION})
    monkeypatch.setattr("mediahub.platform_source.GitHubSourceProvider.check", upstream)
    svc = SimpleNamespace(
        settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository="owner/mediahub-main")),
        release_credentials=SimpleNamespace(token=lambda: None),
        app_dependencies=SimpleNamespace(
            public=lambda: {
                "state": preparation,
                "message": "App preparation failed" if preparation == "failed" else None,
            }
        )
    )
    manager = SimpleNamespace(
        svc=svc, containers=AsyncMock(return_value=[row("app", True, version)])
    )
    adapter = ManagedAdapter(manager, "org.mediahub.mediaseed")
    checked = asyncio.run(adapter.updateCheck())
    upstream.assert_awaited_once_with("owner/mediahub-main", None)
    assert checked["latestVersion"] == BUNDLED_VERSION
    assert checked["installedVersion"] == version
    assert checked["checkStatus"] == status
    assert not checked[
        "updateAvailable"
    ]  # Updates travel with Core, never through the Plex updater.
    result = UpdateMonitor._app_result(
        {"id": "seed", "name": "MediaSeed", "version": "managed"}, checked
    )
    assert result["installedVersion"] == version and result["checkStatus"] == status
    assert "managed" != result["installedVersion"]


def test_rate_limit_does_not_erase_observed_installed_app_version(monkeypatch):
    error = DomainError("github_rate_limited", "GitHub request limit reached", 429)
    error.retry_at = 123456
    monitor = SimpleNamespace(check_platform=AsyncMock(side_effect=error))
    svc = SimpleNamespace(updates=monitor, settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository="owner/hub")))
    adapter = ManagedAdapter(SimpleNamespace(svc=svc, containers=AsyncMock(return_value=[row("app", False, "0.1.7")])), "org.mediahub.mediaseed")
    checked = asyncio.run(adapter.updateCheck())
    assert checked["installedVersion"] == "0.1.7"
    assert checked["checkStatus"] == "deferred" and checked["retryAt"] == 123456
    assert checked["bundledVersion"] == BUNDLED_VERSION


def test_matching_verified_core_commit_reuses_immutable_bundled_metadata():
    monitor = SimpleNamespace(
        check_platform=AsyncMock(return_value={"installedCommit": "a" * 40, "latestCommit": "a" * 40}),
        source_metadata=AsyncMock(side_effect=AssertionError("Unnecessary GitHub request")),
    )
    svc = SimpleNamespace(updates=monitor, settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository="owner/hub")))
    adapter = ManagedAdapter(SimpleNamespace(svc=svc, containers=AsyncMock(return_value=[row("app", True, BUNDLED_VERSION)])), "org.mediahub.mediaseed")
    checked = asyncio.run(adapter.updateCheck())
    assert checked["checkStatus"] == "checked"
    assert checked["latestVersion"] == BUNDLED_VERSION
    monitor.source_metadata.assert_not_awaited()


def test_preparation_finishing_during_check_publishes_replacement_version():
    monitor = SimpleNamespace(check_platform=AsyncMock(return_value={"installedCommit": "a" * 40, "latestCommit": "a" * 40}))
    svc = SimpleNamespace(updates=monitor, settings=SimpleNamespace(get=lambda: SimpleNamespace(release_repository="owner/hub")))
    adapter = ManagedAdapter(SimpleNamespace(svc=svc), "org.mediahub.mediaseed")
    adapter.installed_version = AsyncMock(side_effect=[
        {"installedVersion": "0.1.0", "bundledVersion": BUNDLED_VERSION, "preparationState": "preparing", "preparationMessage": None},
        {"installedVersion": BUNDLED_VERSION, "bundledVersion": BUNDLED_VERSION, "preparationState": "ready", "preparationMessage": None},
    ])
    checked = asyncio.run(adapter.updateCheck())
    assert checked["installedVersion"] == BUNDLED_VERSION
    assert checked["checkStatus"] == "checked"
