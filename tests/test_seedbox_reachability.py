import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mediahub.seedbox_reachability import SeedboxReachability, target

from agent.port_listener import listening


def report(ip="46.29.25.141", port=53593):
    return {
        "vpn": {"verified": True, "externalIp": ip},
        "portForwarding": {
            "currentPort": port,
            "status": "healthy",
            "qBittorrentVerified": True,
            "expiresAt": time.time() + 60,
        },
    }


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "192.168.1.148", "169.254.169.254", "::1", "224.0.0.1", "ff02::1", "not-an-ip"],
)
def test_rejects_non_public_probe_targets(ip):
    with pytest.raises(ValueError):
        target(report(ip))


@pytest.mark.parametrize(
    "field,value",
    [
        ("expiresAt", 0),
        ("currentPort", 80),
        ("currentPort", True),
        ("qBittorrentVerified", False),
        ("status", "degraded"),
    ],
)
def test_rejects_unverified_or_expired_lease(field, value):
    data = report()
    data["portForwarding"][field] = value
    with pytest.raises(ValueError):
        target(data)


def test_listener_requires_listen_state_expected_port_and_non_loopback():
    def rows(address="00000000", port="D159", state="0A"):
        return "header\n 0: " + address + ":" + port + " 00000000:0000 " + state + " 0 0 0"

    assert listening(rows(), 53593)
    assert not listening(rows(state="01"), 53593)
    assert not listening(rows(address="0100007F"), 53593)
    assert not listening(rows(address="0200007F"), 53593)
    assert not listening(rows(port="D158"), 53593)


def service(monkeypatch, reports):
    db = Mock()
    db.scalar.return_value = SimpleNamespace(value={"hostId": "seedbox"})
    sessions = Mock()
    sessions.return_value.__enter__ = Mock(return_value=db)
    sessions.return_value.__exit__ = Mock(return_value=False)
    client = SimpleNamespace(request=AsyncMock(side_effect=reports))
    svc = SimpleNamespace(
        sessions=sessions, hosts=SimpleNamespace(client=lambda identifier: client), events=Mock()
    )
    return SeedboxReachability(svc)


def test_tcp_success_and_request_throttling(monkeypatch):
    checker = service(monkeypatch, [report(), report()])
    connect = AsyncMock()
    monkeypatch.setattr("mediahub.seedbox_reachability.tcp_connect", connect)
    assert asyncio.run(checker.check())["status"] == "reachable"
    assert asyncio.run(checker.check())["status"] == "reachable"
    connect.assert_awaited_once_with("46.29.25.141", 53593)


def test_failure_alert_after_two_checks_and_clear_on_recovery(monkeypatch):
    checker = service(monkeypatch, [report() for _ in range(6)])
    monkeypatch.setattr(
        "mediahub.seedbox_reachability.tcp_connect",
        AsyncMock(side_effect=[TimeoutError(), TimeoutError(), None]),
    )
    assert asyncio.run(checker.check())["status"] == "unreachable"
    checker.svc.events.record.assert_not_called()
    checker.state["checkedAt"] = 0
    assert asyncio.run(checker.check())["status"] == "unreachable"
    checker.svc.events.record.assert_called_once()
    checker.state["checkedAt"] = 0
    assert asyncio.run(checker.check())["status"] == "reachable"
    checker.svc.events.read_notifications.assert_called_once()


def test_endpoint_change_does_not_publish_false_success(monkeypatch):
    checker = service(monkeypatch, [report(), report(port=53594)])
    monkeypatch.setattr("mediahub.seedbox_reachability.tcp_connect", AsyncMock())
    assert asyncio.run(checker.check())["status"] == "unknown"


def test_stale_result_is_not_green():
    checker = SeedboxReachability(None)
    checker.state = {"status": "reachable", "checkedAt": time.time() - 100}
    assert checker.status()["status"] == "unknown"
