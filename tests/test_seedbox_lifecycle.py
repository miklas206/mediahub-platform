import copy

import pytest
from mediahub.errors import DomainError

from agent.seedbox_lifecycle import Lifecycle


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Driver:
    def __init__(self):
        self.calls = []
        self.fail = None

    async def call(self, name):
        self.calls.append(name)
        if name == self.fail:
            raise RuntimeError("Authorization: secret-must-not-escape")
        return "198.51.100.20"

    async def stop_torrent(self):
        return await self.call("stop-torrent")

    async def stop_vpn(self):
        return await self.call("stop-vpn")

    async def storage_guard(self):
        return await self.call("storage")

    async def device_guard(self):
        return await self.call("devices")

    async def write_probe(self):
        return await self.call("write-probe")

    async def start_vpn(self, restart=False):
        return await self.call("restart-vpn" if restart else "start-vpn")

    async def verify_vpn(self):
        return await self.call("verify-vpn")

    async def start_torrent(self):
        return await self.call("start-torrent")

    async def verify_torrent(self, ip):
        assert ip == "198.51.100.20"
        return await self.call("verify-torrent")


def setup():
    driver, saved, events, now = Driver(), [], [], [1000]
    lifecycle = Lifecycle(
        driver,
        {},
        lambda state: saved.append(copy.deepcopy(state)),
        lambda kind, level: events.append((kind, level)),
        lambda: now[0],
    )
    return lifecycle, driver, saved, events, now


@pytest.mark.anyio
async def test_start_order_and_intent_persisted():
    lifecycle, d, saved, events, _ = setup()
    assert await lifecycle.action("start") == {"state": "healthy"}
    assert saved[0]["desiredRunning"] is True
    assert d.calls == [
        "stop-torrent",
        "storage",
        "devices",
        "write-probe",
        "start-vpn",
        "verify-vpn",
        "storage",
        "devices",
        "start-torrent",
        "verify-torrent",
        "storage",
    ]
    assert events[-1][0] == "seedbox.started"


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["storage", "devices", "write-probe", "verify-vpn"])
async def test_failed_gate_never_starts_torrent(failure):
    lifecycle, d, _, events, _ = setup()
    d.fail = failure
    with pytest.raises(DomainError) as error:
        await lifecycle.action("start")
    assert "secret" not in str(error.value)
    assert "start-torrent" not in d.calls
    assert "secret" not in str(events)


@pytest.mark.anyio
async def test_failed_egress_stops_torrent():
    lifecycle, d, *_ = setup()
    d.fail = "verify-torrent"
    with pytest.raises(DomainError):
        await lifecycle.action("restart")
    assert d.calls[-1] == "stop-torrent"


@pytest.mark.anyio
async def test_stop_survives_restart_without_auto_recovery():
    lifecycle, d, saved, *_ = setup()
    await lifecycle.action("stop")
    assert saved[-1]["desiredRunning"] is False
    assert await lifecycle.recover("vpn") == "stopped"
    assert d.calls == ["stop-torrent", "stop-vpn"]


@pytest.mark.anyio
async def test_three_attempts_then_persistent_latch():
    lifecycle, d, saved, events, now = setup()
    lifecycle.state["desiredRunning"] = True
    d.fail = "verify-vpn"
    for _ in range(3):
        assert await lifecycle.recover("vpn") == "failed"
    assert await lifecycle.recover("vpn") == "manual-intervention"
    assert d.calls.count("restart-vpn") == 3
    now[0] += 601
    assert await lifecycle.recover("vpn") == "manual-intervention"
    assert saved[-1]["manualIntervention"] == ["vpn"]
    assert ("recovery.rate_limited", "error") in events
    d.fail = None
    await lifecycle.action("start")
    assert lifecycle.state["manualIntervention"] == []


@pytest.mark.anyio
async def test_storage_wait_never_spends_attempt_or_starts_vpn():
    lifecycle, d, *_ = setup()
    lifecycle.state["desiredRunning"] = True
    d.fail = "storage"
    assert await lifecycle.recover("storage") == "waiting-for-storage"
    assert lifecycle.state["attempts"] == {}
    assert d.calls == ["stop-torrent", "storage"]


def test_independent_components_clock_rollback_and_stability():
    lifecycle, _, _, _, now = setup()
    for _ in range(3):
        assert lifecycle.reserve_attempt("vpn")
    now[0] -= 60
    assert not lifecycle.reserve_attempt("vpn")
    assert lifecycle.reserve_attempt("qbittorrent")
    lifecycle.observed_healthy()
    now[0] += 300
    lifecycle.observed_healthy()
    assert len(lifecycle.state["attempts"]["vpn"]) == 3
    now[0] += 601
    lifecycle.observed_healthy()
    assert lifecycle.state["attempts"] == {}
    assert lifecycle.state["manualIntervention"] == ["vpn"]


@pytest.mark.anyio
async def test_uncertain_start_response_still_stops_torrent():
    lifecycle, d, *_ = setup()
    d.fail = "start-torrent"
    with pytest.raises(DomainError):
        await lifecycle.action("start")
    assert d.calls[-1] == "stop-torrent"


@pytest.mark.anyio
async def test_manual_start_does_not_reset_rolling_automatic_budget():
    lifecycle, _, _, _, _ = setup()
    for _ in range(3):
        assert lifecycle.reserve_attempt("vpn")
    await lifecycle.action("start")
    assert not lifecycle.reserve_attempt("vpn")
