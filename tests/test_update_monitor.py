import asyncio

from mediahub.apps.cloudflared import register_cloudflared_app


def available_item(version="0.4.0"):
    return {
        "id": "mediahub-core",
        "name": "MediaHub Core",
        "installedVersion": "0.3.0",
        "latestVersion": version,
        "updateAvailable": True,
        "message": "Verified update available",
    }


def test_update_notifications_are_persistent_deduplicated_and_dismissible(logged_in):
    svc = logged_in.app.state.services
    svc.updates._store_results([available_item()])
    first = logged_in.get("/api/v1/updates/summary").json()["data"]
    assert first["count"] == 1
    assert first["items"][0]["latestVersion"] == "0.4.0"
    assert len(first["notifications"]) == 1

    svc.updates._store_results([available_item()])
    repeated = logged_in.get("/api/v1/updates/summary").json()["data"]
    assert len(repeated["notifications"]) == 1

    notification_id = repeated["notifications"][0]["id"]
    dismissed = logged_in.post(f"/api/v1/notifications/{notification_id}/read")
    assert dismissed.status_code == 200
    assert logged_in.get("/api/v1/updates/summary").json()["data"]["notifications"] == []


def test_update_notifications_auto_resolve_when_no_updates_remain(logged_in):
    svc = logged_in.app.state.services
    svc.updates._store_results([available_item()])
    assert len(svc.updates.summary()["notifications"]) == 1

    resolved = {**available_item(), "updateAvailable": False}
    svc.updates._store_results([resolved])

    summary = svc.updates.summary()
    assert summary["count"] == 0
    assert summary["notifications"] == []
    assert len(svc.events.notifications(pending_only=False)) == 1
    assert svc.events.notifications(pending_only=False)[0]["state"] == "read"


def test_failed_zero_update_check_keeps_previous_notification(logged_in):
    svc = logged_in.app.state.services
    svc.updates._store_results([available_item()])

    resolved = {**available_item(), "updateAvailable": False}
    svc.updates._store_results([resolved], error="Update source unavailable")

    summary = svc.updates.summary()
    assert summary["count"] == 0
    assert summary["lastError"] == "Update source unavailable"
    assert len(summary["notifications"]) == 1


def test_same_version_notifies_again_only_after_it_was_no_longer_available(logged_in):
    svc = logged_in.app.state.services
    svc.updates._store_results([available_item()])
    first_id = svc.updates.summary()["notifications"][0]["id"]
    assert svc.events.read_notification(first_id)

    svc.updates._store_results(
        [{**available_item(), "updateAvailable": False, "message": "Up to date"}]
    )
    svc.updates._store_results([available_item()])
    notifications = svc.updates.summary()["notifications"]
    assert len(notifications) == 1
    assert notifications[0]["id"] != first_id


def test_update_schedule_is_configurable_and_does_not_install(logged_in):
    settings = logged_in.get("/api/v1/settings").json()["data"]
    settings["update_check_interval_hours"] = 72
    settings["release_repository"] = "owner/repo"
    assert logged_in.put("/api/v1/settings", json=settings).status_code == 200
    summary = logged_in.get("/api/v1/updates/summary").json()["data"]
    assert summary["intervalHours"] == 72
    assert summary["mainCheckIntervalSeconds"] == 900
    assert summary["count"] == 0


def test_recording_an_app_result_updates_the_shared_badge(logged_in):
    svc = logged_in.app.state.services
    register_cloudflared_app(svc)
    app = next(item for item in svc.apps.list() if not item["isMock"])
    asyncio.run(
        svc.updates.record_app(
            app,
            {
                "installedVersion": "1.0.0",
                "latestVersion": "1.1.0",
                "updateAvailable": True,
                "message": "Update available",
            },
        )
    )
    summary = svc.updates.summary()
    assert summary["count"] == 1
    assert summary["items"][0]["id"] == app["id"]


def test_unknown_notification_cannot_be_marked_read(logged_in):
    response = logged_in.post("/api/v1/notifications/not-a-real-notification/read")
    assert response.status_code == 404


def test_platform_install_api_stays_locked_without_host_updater(logged_in):
    operation = logged_in.get("/api/v1/updates/platform/operation")
    assert operation.status_code == 200
    assert operation.json()["data"]["state"] == "unavailable"
    install = logged_in.post("/api/v1/updates/platform/install")
    assert install.status_code == 409
    assert install.json()["error"]["code"] == "platform_updater_unavailable"


def test_refresh_joins_running_check_and_disconnect_does_not_cancel_it():
    from mediahub.update_monitor import UpdateMonitor

    async def scenario():
        monitor = UpdateMonitor(None)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def check():
            calls.append(True)
            started.set()
            await release.wait()
            return {"count": 2}

        monitor._check_all = check
        original = asyncio.create_task(monitor.check_all())
        await started.wait()
        original.cancel()
        try:
            await original
        except asyncio.CancelledError:
            pass
        refreshed = asyncio.create_task(monitor.check_all())
        scheduled = asyncio.create_task(monitor.check_all())
        await asyncio.sleep(0)
        assert calls == [True]
        release.set()
        assert await refreshed == {"count": 2}
        assert await scheduled == {"count": 2}
        assert await monitor.check_all() == {"count": 2}
        assert len(calls) == 2

    asyncio.run(scenario())


def test_partial_success_preserves_other_source_failure(logged_in):
    from mediahub.errors import DomainError

    svc = logged_in.app.state.services
    failure = svc.updates._failure(
        {"id": "cloudflare", "name": "Cloudflare Tunnel"},
        DomainError("update_source_timeout", "GitHub cloudflared release lookup timed out", 503),
    )
    svc.updates._store_results([failure])
    asyncio.run(svc.updates.record_platform({"updateAvailable": False}))
    summary = svc.updates.summary()
    assert summary["lastError"] == "Could not check: Cloudflare Tunnel"
    assert summary["items"][1]["errorCode"] == "update_source_timeout"
    asyncio.run(
        svc.updates.record_app(
            {"id": "cloudflare", "name": "Cloudflare Tunnel"}, {"updateAvailable": False}
        )
    )
    assert svc.updates.summary()["lastError"] is None


def test_failed_sources_are_all_identified(logged_in, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from mediahub.errors import DomainError

    svc = logged_in.app.state.services
    monkeypatch.setattr(
        svc.updates,
        "check_platform",
        AsyncMock(side_effect=DomainError("github_unavailable", "GitHub unavailable")),
    )
    monkeypatch.setattr(
        svc.agent_updates,
        "check",
        AsyncMock(side_effect=DomainError("agent_offline", "Agent offline")),
    )
    monkeypatch.setattr(
        svc.apps, "list", lambda: [{"id": "cloudflare", "name": "Cloudflare Tunnel"}]
    )
    monkeypatch.setattr(
        svc.apps,
        "adapter",
        lambda _: SimpleNamespace(updateCheck=AsyncMock(side_effect=asyncio.TimeoutError())),
    )
    result = asyncio.run(svc.updates.check_all())
    assert len(result["items"]) == 3
    assert all(item["checkStatus"] == "failed" for item in result["items"])
    assert result["items"][2]["errorCode"] == "update_check_timeout"
    assert result["lastError"] == "Could not check: MediaHub Core, Seedbox Agent, Cloudflare Tunnel"
