from types import SimpleNamespace

from mediahub.apps.remote_adapter import RemoteAppAdapter, RemoteAppDefinition
from mediahub.apps.remote_status import RemoteStatusCache


def test_action_requires_login(client):
    assert client.post("/api/v1/apps/test/actions/start").status_code == 401


def test_component_action_auth_csrf_and_host_scope(logged_in):
    svc = logged_in.app.state.services
    calls = []

    class Client:
        async def request(self, method, path):
            calls.append((method, path))
            return {"state": "accepted"}

    def client(host):
        assert host == "isolated-host"
        return Client()

    events = []
    adapter = RemoteAppAdapter(
        RemoteAppDefinition("test.package", "test", "/v1/test", ("test-vpn",)),
        "isolated-host",
        client,
        RemoteStatusCache(),
        SimpleNamespace(record=lambda *args: events.append(args)),
        "test-app",
    )
    # Scoped adapter lookup stands in for the existing installed-app DB fixture.
    svc.apps.adapter = lambda app: adapter if app == "test-app" else None
    response = logged_in.post(
        "/api/v1/apps/test-app/actions/test-vpn", headers={"X-MediaHub-CSRF": "invalid"}
    )
    assert response.status_code == 403 and calls == []
    response = logged_in.post("/api/v1/apps/test-app/actions/test-vpn")
    assert response.status_code == 200
    assert calls == [("POST", "/v1/test/actions/test-vpn")]
    assert events[-1][0] == "app.action_accepted"
