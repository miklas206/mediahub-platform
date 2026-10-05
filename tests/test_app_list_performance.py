import asyncio
from types import SimpleNamespace

import pytest
from mediahub.api import apps, stream
from mediahub.contracts import Health
from mediahub.db import InstalledApp
from mediahub.events import EventBus
from sqlalchemy import event


def test_app_list_checks_independent_apps_concurrently():
    async def scenario():
        started = set()
        all_started = asyncio.Event()
        rows = [{"id": str(index), "name": f"App {index}"} for index in range(4)]

        async def health(app_id):
            started.add(app_id)
            if len(started) == len(rows):
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return Health(status="healthy", summary=app_id)

        manager = SimpleNamespace(list=lambda: rows, health=health)
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(apps=manager)))
        )
        payload = await apps(request, user={"id": "test"})
        assert [row["id"] for row in payload["data"]] == [row["id"] for row in rows]
        assert all(row["health"]["summary"] == row["id"] for row in payload["data"])

    asyncio.run(scenario())


def test_app_list_lightweight_endpoint_skips_health(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    rows = svc.apps.list()
    assert rows

    async def unexpected_health(app_id):
        pytest.fail(f"Lightweight listing requested health for {app_id}")

    monkeypatch.setattr(svc.apps, "health", unexpected_health)
    response = logged_in.get("/api/v1/apps?include_health=false")
    assert response.status_code == 200
    assert response.json()["data"] == rows
    assert all("health" not in row for row in response.json()["data"])


@pytest.mark.parametrize("query", ["", "?include_health=true"])
def test_app_list_endpoint_includes_health_by_default(logged_in, monkeypatch, query):
    svc = logged_in.app.state.services
    rows = svc.apps.list()
    checked = []
    reports = {row["id"]: Health(status="healthy", summary=row["id"]) for row in rows}

    async def health(app_id):
        checked.append(app_id)
        return reports[app_id]

    monkeypatch.setattr(svc.apps, "health", health)
    response = logged_in.get("/api/v1/apps" + query)
    assert response.status_code == 200
    assert checked == [row["id"] for row in rows]
    assert response.json()["data"] == [
        {**row, "health": reports[row["id"]].model_dump(mode="json")} for row in rows
    ]


def test_live_stream_checks_initial_apps_concurrently_and_cleans_up():
    async def scenario():
        started = set()
        all_started = asyncio.Event()

        async def health(app_id):
            started.add(app_id)
            if len(started) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return Health(status="healthy", summary=app_id)

        events = EventBus(None)
        events.stopping = True
        manager = SimpleNamespace(list=lambda: [{"id": str(i)} for i in range(3)], health=health)
        svc = SimpleNamespace(apps=manager, events=events, snapshot={"cpu": {"percent": 1}})
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(services=svc)), cookies={}
        )
        response = await stream(request, user={"id": "test"})
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks[0] == "retry: 5000\n\n"
        assert chunks[1].startswith("event: system.status\n")
        assert len(chunks) == 5
        assert all(chunk.startswith("event: app.health.changed\n") for chunk in chunks[2:])
        assert not events.subscribers

    asyncio.run(scenario())


def test_app_list_limits_parallel_health_checks():
    async def scenario():
        active = peak = 0
        release = asyncio.Event()

        async def health(app_id):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 8:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=1)
            await asyncio.sleep(0)
            active -= 1
            return Health(status="unknown", summary=app_id)

        manager = SimpleNamespace(
            list=lambda: [{"id": str(index)} for index in range(20)], health=health
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(apps=manager)))
        )
        payload = await apps(request, user={"id": "test"})
        assert len(payload["data"]) == 20
        assert peak == 8
        manager.list = lambda: []
        assert (await apps(request, user={"id": "test"}))["data"] == []

    asyncio.run(scenario())


def test_app_list_still_propagates_health_errors():
    async def health(app_id):
        raise ValueError("Invalid app health")

    manager = SimpleNamespace(list=lambda: [{"id": "broken"}], health=health)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(apps=manager)))
    )
    with pytest.raises(ValueError, match="Invalid app health"):
        asyncio.run(apps(request, user={"id": "test"}))


def test_app_list_uses_one_query_and_preserves_fields(logged_in):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add_all(
            [
                InstalledApp(
                    id="perf-app",
                    package_id="org.test.perf",
                    name="Performance app",
                    version="1.0",
                    state="running",
                    is_mock=False,
                ),
                InstalledApp(
                    id="perf-removed",
                    package_id="org.test.removed",
                    name="Removed app",
                    version="1.0",
                    state="uninstalled",
                    is_mock=False,
                ),
            ]
        )
    svc.apps.adapters["perf-app"] = SimpleNamespace(definition=object())
    queries = []
    engine = svc.sessions.kw["bind"]

    def count_queries(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        rows = svc.apps.list()
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
    assert len(queries) == 1
    assert next(row for row in rows if row["id"] == "perf-app") == {
        "id": "perf-app",
        "packageId": "org.test.perf",
        "name": "Performance app",
        "version": "1.0",
        "state": "running",
        "isMock": False,
        "detailPath": "/apps/perf-app",
    }
    assert not any(row["id"] == "perf-removed" for row in rows)
    assert any(row["isMock"] for row in rows)
    svc.apps.config.mock_app = False
    assert all(not row["isMock"] for row in svc.apps.list())
