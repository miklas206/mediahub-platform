import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mediahub.apps.seedbox_daily import VPNLocation
from pydantic import ValidationError

from agent.vpn_optimizer import VPNOptimizer, winner


def test_small_improvements_keep_current_but_large_improvement_switches():
    samples = {
        "old": {"downloadMbps": 100, "uploadMbps": 100},
        "new": {"downloadMbps": 120, "uploadMbps": 120},
    }
    assert winner(samples, "old") == "old"
    samples["new"] = {"downloadMbps": 130, "uploadMbps": 130}
    assert winner(samples, "old") == "new"
    # A high download rate cannot hide a poor upload path for seeding.
    samples["new"] = {"downloadMbps": 1000, "uploadMbps": 10}
    assert winner(samples, "old") == "old"


@pytest.mark.parametrize("hours", [0, 6, 24])
def test_schedule_choices(hours):
    assert VPNLocation(country="Denmark", intervalHours=hours).intervalHours == hours
    with pytest.raises(ValidationError):
        VPNLocation(country="Denmark", intervalHours=1)


@pytest.mark.parametrize("failed_measurement", [False, True])
def test_comparison_restores_verified_winner_or_previous_server(failed_measurement):
    async def run():
        forwarding = SimpleNamespace(renew=AsyncMock(return_value={"status": "healthy"}))
        driver = SimpleNamespace(
            forwarding=forwarding,
            measure_vpn_speed=AsyncMock(
                side_effect=ValueError("private detail")
                if failed_measurement
                else [
                    {"downloadMbps": 100, "uploadMbps": 100},
                    {"downloadMbps": 110, "uploadMbps": 110},
                ]
            ),
        )
        location = SimpleNamespace(
            control=SimpleNamespace(driver=driver),
            public=AsyncMock(return_value={"current": {"server": "old"}}),
            apply=AsyncMock(return_value=True),
        )
        optimizer = VPNOptimizer(location)
        optimizer.state = lambda: {"enabled": True, "intervalHours": 6}
        optimizer.save = Mock()
        await optimizer.run([{"id": "old"}, {"id": "new"}])
        assert location.apply.call_args.args[0]["id"] == "old"
        saved = optimizer.save.call_args.args[0]
        assert saved["selected"] == "old"
        assert saved["nextCheck"] >= saved["lastChecked"] + 21600
        assert "private detail" not in str(saved)
        assert not optimizer.running

    asyncio.run(run())


def test_unverified_port_excludes_faster_candidate():
    async def run():
        forwarding = SimpleNamespace(
            renew=AsyncMock(side_effect=[{"status": "healthy"}, {"status": "degraded"}])
        )
        driver = SimpleNamespace(
            forwarding=forwarding,
            measure_vpn_speed=AsyncMock(
                side_effect=[
                    {"downloadMbps": 10, "uploadMbps": 10},
                    {"downloadMbps": 100, "uploadMbps": 100},
                ]
            ),
        )
        location = SimpleNamespace(
            control=SimpleNamespace(driver=driver),
            public=AsyncMock(return_value={"current": {"server": "old"}}),
            apply=AsyncMock(return_value=True),
        )
        optimizer = VPNOptimizer(location)
        optimizer.state = lambda: {"intervalHours": 0}
        optimizer.save = Mock()
        await optimizer.run([{"id": "old"}, {"id": "new"}])
        assert optimizer.save.call_args.args[0]["selected"] == "old"
        assert "new" not in optimizer.save.call_args.args[0]["samples"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "enabled,hours,busy,expected",
    [
        (True, 6, False, 1),
        (True, 24, False, 1),
        (True, 0, False, 0),
        (False, 6, False, 0),
        (True, 6, True, 0),
    ],
)
def test_scheduler_respects_persisted_mode_and_busy_controller(
    monkeypatch, enabled, hours, busy, expected
):
    async def scenario():
        sleeps = 0

        async def sleep(_):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                raise asyncio.CancelledError()

        monkeypatch.setattr("agent.vpn_optimizer.asyncio.sleep", sleep)
        control = SimpleNamespace(
            job=SimpleNamespace(done=lambda: False) if busy else None,
            lifecycle=SimpleNamespace(lock=asyncio.Lock(), state={"desiredRunning": True}),
            driver=None,
        )
        provider = SimpleNamespace(
            servers=AsyncMock(return_value=[{"country": "Denmark", "id": "one"}])
        )
        locations = SimpleNamespace(control=control, context=lambda: (None, None, provider))
        optimizer = VPNOptimizer(locations)
        optimizer.state = lambda: {
            "enabled": enabled,
            "intervalHours": hours,
            "country": "Denmark",
            "nextCheck": 0,
        }
        optimizer.run = AsyncMock()
        with pytest.raises(asyncio.CancelledError):
            await optimizer.poll()
        assert optimizer.run.await_count == expected

    asyncio.run(scenario())
