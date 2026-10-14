import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.managed_apps import ManagedAdapter
from mediahub.update_monitor import UpdateMonitor


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
    [("0.1.2", "ready", "checked"), (None, "failed", "failed"), ("0.1.1", "ready", "unchecked"), ("0.1.0", "ready", "unchecked")],
)
def test_bundled_checks_use_running_app_version_and_report_preparation_failure(
    version, preparation, status, monkeypatch
):
    upstream = AsyncMock(return_value={"latestVersion": "0.1.2"})
    monkeypatch.setattr("mediahub.platform_source.GitHubSourceProvider.check", upstream)
    svc = SimpleNamespace(
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
    upstream.assert_awaited_once_with("miklas206/mediaseed", None)
    assert checked["latestVersion"] == "0.1.2"
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
