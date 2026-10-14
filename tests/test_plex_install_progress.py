from unittest.mock import AsyncMock

import pytest
from mediahub.db import InstalledApp, Setting


@pytest.mark.parametrize("state", ["starting", "uninstalled"])
def test_install_status_uses_bound_agent_without_requiring_plex_health(logged_in, monkeypatch, state):
    client = logged_in
    with client.app.state.services.sessions.begin() as db:
        db.add(Setting(key="plex_installation", value={"hostId": "paired-host"}))
        db.add(InstalledApp(package_id="org.mediahub.plex", name="Plex", version="unknown", state=state, is_mock=False))
    operation = {"action": "install", "state": "running", "phase": "download", "progress": 10, "indeterminate": True}
    agent = AsyncMock()
    agent.request.return_value = {"operation": operation}
    hosts = []
    monkeypatch.setattr("mediahub.plex_api.target", lambda request, host: hosts.append(host) or agent)
    response = client.get("/api/v1/plex/install-status")
    assert response.status_code == 200
    if state == "uninstalled":
        assert response.json()["data"]["operation"]["state"] == "idle"
        agent.request.assert_not_awaited()
    else:
        assert response.json()["data"] == {"operation": operation}
        assert hosts == ["paired-host"]
        agent.request.assert_awaited_once_with("GET", "/v1/plex/install-status")


def test_install_status_is_idle_before_install_and_requires_login(client, logged_in):
    assert logged_in.get("/api/v1/plex/install-status").json()["data"] == {"operation": {"state": "idle"}}
    client.cookies.clear()
    assert client.get("/api/v1/plex/install-status").status_code == 401
