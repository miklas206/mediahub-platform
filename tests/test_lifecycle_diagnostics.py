import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mediahub.errors import DomainError

from agent.diagnostics import Diagnostics, cause, trace_async


def test_agent_diagnostics_survive_restart_and_async_cause(tmp_path):
    diagnostic = Diagnostics(tmp_path, "plex")

    @trace_async("hub", "shared_configuration")
    async def recreate():
        diagnostic.record("stop_requested")
        await asyncio.sleep(0)
        diagnostic.record("start_requested")

    with cause("supervisor", "relay_unhealthy"):
        asyncio.run(recreate())
    rows = Diagnostics(tmp_path).entries()
    assert rows[0]["operationId"] == rows[1]["operationId"]
    assert all(r["origin"] == "supervisor" and r["reason"] == "relay_unhealthy" for r in rows)


def test_agent_and_vpn_use_same_diagnostic_contract():
    root = Path(__file__).resolve().parents[1]
    assert (root / "agent/diagnostics.py").read_bytes().replace(b"\r\n", b"\n") == (
        root / "docker/bundled/mediavpn/mediavpn/diagnostics.py").read_bytes().replace(b"\r\n", b"\n")


def test_core_logs_aggregate_persistent_agent_and_vpn(logged_in):
    svc = logged_in.app.state.services
    entry = {"timestamp": 1792060000, "severity": "warning", "type": "plex.monitor.stop_requested",
             "message": "storage_blocked operationId=synthetic"}
    svc.agent = SimpleNamespace(request=AsyncMock(return_value={"entries": [entry]}))
    svc.vpn_gateway.vpn = AsyncMock(return_value={"entries": [{**entry, "type": "vpn.provider.replace"}]})
    response = logged_in.get("/api/v1/logs")
    assert response.status_code == 200
    rows = response.json()["data"]
    assert {"plex.monitor.stop_requested", "vpn.provider.replace"} <= {r["component"] for r in rows}
    svc.agent.request.assert_awaited_with("GET", "/v1/diagnostics/logs")
    svc.vpn_gateway.vpn.assert_awaited_with(diagnostics=True)


def test_logs_report_unavailable_old_component_without_losing_core(logged_in):
    svc = logged_in.app.state.services
    svc.agent = SimpleNamespace(request=AsyncMock(side_effect=DomainError("old_agent", "unavailable", 404)))
    svc.vpn_gateway.vpn = AsyncMock(side_effect=DomainError("old_vpn", "unavailable", 404))
    response = logged_in.get("/api/v1/logs")
    assert response.status_code == 200
    assert len([r for r in response.json()["data"] if "Persistent lifecycle diagnostics unavailable" in r["message"]]) == 2
