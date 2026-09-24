import asyncio


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
    assert logged_in.put("/api/v1/settings", json=settings).status_code == 200
    summary = logged_in.get("/api/v1/updates/summary").json()["data"]
    assert summary["intervalHours"] == 72
    assert summary["count"] == 0


def test_recording_an_app_result_updates_the_shared_badge(logged_in):
    svc = logged_in.app.state.services
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
