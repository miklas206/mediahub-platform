import asyncio
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from mediahub.errors import DomainError
from mediahub.update_queue import UpdateQueue


def queue_fixture(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    queue = UpdateQueue(svc)
    monkeypatch.setattr(
        svc.updates,
        "summary",
        lambda: {
            "items": [
                {"id": "mediahub-core", "name": "Core", "updateAvailable": True},
                {"id": "seedbox-agent", "name": "Agent", "updateAvailable": True},
            ]
        },
    )
    monkeypatch.setattr(svc.updates, "check_all", AsyncMock())
    monkeypatch.setattr(queue, "check", AsyncMock(return_value={"updateAvailable": True}))
    return queue


def test_queue_continues_after_request_task_has_finished(logged_in, monkeypatch):
    queue = queue_fixture(logged_in, monkeypatch)

    async def scenario():
        gate = asyncio.Event()
        launched = []

        async def launch(item, checked):
            launched.append(item["kind"])
            await gate.wait()
            return {"operationId": item["kind"], "state": "running"}

        async def operation(item):
            if item["state"] == "pending":
                return {"state": "idle"}
            return {"operationId": item["kind"], "state": "succeeded", "message": "Verified"}

        monkeypatch.setattr(queue, "launch", launch)
        monkeypatch.setattr(queue, "operation", operation)
        request_id = uuid4()
        request = asyncio.create_task(queue.start(["mediahub-core", "seedbox-agent"], request_id))
        result = await request
        assert request.done() and result["state"] == "running"
        assert queue.task is not request and not queue.task.done()
        # A retry after losing the HTTP acknowledgement returns the same queue.
        assert (await queue.start(["mediahub-core"], request_id))["operationId"] == str(request_id)
        with pytest.raises(DomainError, match="already running"):
            await queue.start(["mediahub-core"], uuid4())
        gate.set()
        await queue.task
        assert launched == ["agent", "core"]
        restored = UpdateQueue(queue.svc).status()
        assert restored["state"] == "succeeded"
        assert restored["coreUpdated"]
        assert restored["progress"] == 100

    asyncio.run(scenario())


def test_resume_waits_for_same_operation_without_reinstall(logged_in, monkeypatch):
    queue = queue_fixture(logged_in, monkeypatch)
    queue.save(
        {
            "operationId": str(uuid4()),
            "state": "running",
            "logs": [],
            "coreUpdated": False,
            "items": [
                {
                    "id": "mediahub-core",
                    "name": "Core",
                    "kind": "core",
                    "state": "waiting",
                    "operationId": "existing",
                    "deadline": time.time() + 300,
                }
            ],
        }
    )
    launch = AsyncMock()
    monkeypatch.setattr(queue, "launch", launch)
    monkeypatch.setattr(
        queue,
        "operation",
        AsyncMock(return_value={"operationId": "existing", "state": "succeeded"}),
    )

    async def scenario():
        queue.resume()
        await queue.task

    asyncio.run(scenario())
    assert queue.status()["state"] == "succeeded"
    launch.assert_not_called()


@pytest.mark.parametrize("state", ["failed", "rolled_back", "interrupted"])
def test_failure_stops_queue_and_keeps_console(logged_in, monkeypatch, state):
    queue = queue_fixture(logged_in, monkeypatch)
    launch = AsyncMock(return_value={"operationId": "new"})
    monkeypatch.setattr(queue, "launch", launch)

    async def operation(item):
        return (
            {"state": "idle"}
            if item["state"] == "pending"
            else {
                "state": state,
                "operationId": "new",
                "message": "Verification failed",
                "logs": ["Build finished"],
            }
        )

    monkeypatch.setattr(queue, "operation", operation)

    async def scenario():
        await queue.start(["mediahub-core", "seedbox-agent"], uuid4())
        await queue.task

    asyncio.run(scenario())
    assert queue.status()["state"] == "failed"
    assert "Build finished" in queue.status()["logs"]
    assert queue.status()["items"][1]["state"] == "pending"
    assert launch.await_count == 1


def test_uncertain_acknowledgement_never_repeats_install(logged_in, monkeypatch):
    queue = queue_fixture(logged_in, monkeypatch)
    queue.save(
        {
            "operationId": str(uuid4()),
            "state": "running",
            "logs": [],
            "coreUpdated": False,
            "items": [
                {
                    "id": "mediahub-core",
                    "name": "Core",
                    "kind": "core",
                    "state": "starting",
                    "previousOperationId": "old",
                    "deadline": time.time() + 300,
                }
            ],
        }
    )
    monkeypatch.setattr(
        queue, "operation", AsyncMock(return_value={"operationId": "old", "state": "succeeded"})
    )
    launch = AsyncMock()
    monkeypatch.setattr(queue, "launch", launch)
    asyncio.run(queue.run(queue.status(), recovering=True))
    assert queue.status()["state"] == "failed"
    launch.assert_not_called()


def test_no_update_is_not_installed_and_unknown_selection_is_rejected(logged_in, monkeypatch):
    queue = queue_fixture(logged_in, monkeypatch)
    monkeypatch.setattr(queue, "check", AsyncMock(return_value={"updateAvailable": False}))
    launch = AsyncMock()
    monkeypatch.setattr(queue, "launch", launch)

    async def scenario():
        with pytest.raises(DomainError):
            await queue.start(["unverified-app"], uuid4())
        await queue.start(["mediahub-core"], uuid4())
        await queue.task

    asyncio.run(scenario())
    assert queue.status()["state"] == "succeeded"
    assert not queue.status()["coreUpdated"]
    launch.assert_not_called()


def test_queue_api_requires_https_and_does_not_start_on_get(logged_in, monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(logged_in.app.state.services.update_queue, "start", start)
    assert logged_in.get("/api/v1/updates/queue").json()["data"]["state"] == "idle"
    response = logged_in.post(
        "/api/v1/updates/queue", json={"requestId": str(uuid4()), "ids": ["mediahub-core"]}
    )
    assert response.status_code == 403
    start.assert_not_called()
