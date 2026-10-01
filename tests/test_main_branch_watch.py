import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from mediahub.main_branch_watch import MainBranchWatch
from mediahub.update_monitor import UpdateMonitor


def test_conditional_checks_are_small_throttled_and_detect_changes():
    async def run():
        now = [1000]
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 2:
                assert request.headers["if-none-match"] == '"one"'
                return httpx.Response(304)
            return httpx.Response(
                200,
                json={"sha": ("a" if len(requests) == 1 else "b") * 40},
                headers={"etag": '"one"'},
            )

        watch = MainBranchWatch(httpx.MockTransport(respond), lambda: now[0])
        assert await watch.check("owner/repo", None) == "a" * 40
        now[0] += 60
        assert await watch.check("owner/repo", None) is None
        now[0] += 240
        assert await watch.check("owner/repo", None) == "a" * 40
        now[0] += 300
        assert await watch.check("owner/repo", None) == "b" * 40
        assert len(requests) == 3

    asyncio.run(run())


def test_token_interval_and_rate_limit_backoff():
    async def run():
        now = [1000]
        requests = []

        def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(200, json={"sha": "a" * 40})
            return httpx.Response(429, headers={"retry-after": "1800"})

        watch = MainBranchWatch(httpx.MockTransport(respond), lambda: now[0])
        await watch.check("owner/repo", "token")
        now[0] += 60
        await watch.check("owner/repo", "token")
        now[0] += 900
        await watch.check("owner/repo", "token")
        assert len(requests) == 2
        assert watch.commit == "a" * 40
        assert watch.next_check == 2860

    asyncio.run(run())


def test_new_commit_triggers_shared_verified_check_but_unchanged_does_not():
    async def run():
        settings = SimpleNamespace(update_check_interval_hours=1, release_repository="owner/repo")
        svc = SimpleNamespace(
            settings=SimpleNamespace(get=lambda: settings),
            release_credentials=SimpleNamespace(token=lambda: None),
        )
        monitor = UpdateMonitor(svc)
        monitor._load = lambda: {"items": [{"id": "mediahub-core", "latestVersion": "a" * 40}]}
        monitor.main_watch.check = AsyncMock(return_value="a" * 40)
        monitor.check_all = AsyncMock()
        await monitor.check_main_change()
        monitor.check_all.assert_not_awaited()
        monitor.main_watch.check.return_value = "b" * 40
        await monitor.check_main_change()
        monitor.check_all.assert_awaited_once()
        settings.update_check_interval_hours = 0
        monitor.main_watch.check.reset_mock()
        await monitor.check_main_change()
        monitor.main_watch.check.assert_not_awaited()

    asyncio.run(run())
