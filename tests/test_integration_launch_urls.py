import pytest
from mediahub.db import ExternalIntegration, Setting, User
from mediahub.integrations.service import IntegrationService
from sqlalchemy import select
from test_integrations_api import body


def setup_apps(client, port=8443):
    identifier = client.post(
        "/api/v1/integrations/fjordhub",
        json={**body(), "baseUrl": f"https://192.168.50.20:{port}"},
    ).json()["data"]["id"]
    with client.app.state.services.sessions.begin() as db:
        db.get(ExternalIntegration, identifier).snapshot = {
            "status": "online",
            "apps": [{"id": "fjordflix", "url": "https://192.168.50.20:8096"}],
        }
    return identifier, f"/api/v1/integrations/{identifier}/apps/fjordflix/launch-url"


def test_overrides_persist_scoped_clear_and_cleanup(logged_in):
    first, endpoint = setup_apps(logged_in)
    second, _ = setup_apps(logged_in, 8444)
    url = "https://192.168.50.20:9000/movies"
    response = logged_in.put(endpoint, json={"url": url})
    assert response.status_code == 200
    svc = logged_in.app.state.services
    restarted = IntegrationService(svc.config, svc.sessions, svc.events)
    records = {row["id"]: row for row in restarted.list()}
    assert records[first]["appLaunchOverrides"] == {"fjordflix": url}
    assert records[second]["appLaunchOverrides"] == {}
    assert records[first]["snapshot"]["apps"][0]["url"] == "https://192.168.50.20:8096"
    assert logged_in.put(endpoint, json={"url": None}).json()["data"]["appLaunchOverrides"] == {}
    assert logged_in.put(endpoint, json={"url": url}).status_code == 200
    logged_in.post(f"/api/v1/integrations/{first}/disconnect", json={})
    assert logged_in.delete(f"/api/v1/integrations/{first}").status_code == 200
    with svc.sessions() as db:
        assert db.scalar(select(Setting).where(Setting.key == restarted.launch_key(first))) is None


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://user:pass@192.168.50.20:9000",
        "https://192.168.50.20:9000/?token=secret",
        "https://192.168.50.20:9000/#token",
        "https://192.168.50.21:9000",
        "http://192.168.50.20:9000",
        "https://192.168.50.20:0",
        "https://192.168.50.20:9000/\n",
        "https://192.168.50.20:9000/%0A",
        "https://192.168.50.20:9000/%7f",
        "https://192.168.50.20:9000/" + "x" * 501,
        "https://192.168.50.20:9000/" + body()["accessToken"].replace("-", "%2D"),
        "https://192.168.50.20:9000/\\evil",
        "https://192.168.50.20:9000/test-private-access-token-123456",
    ],
)
def test_bad_urls_not_reflected_or_persisted(logged_in, url):
    identifier, endpoint = setup_apps(logged_in)
    response = logged_in.put(endpoint, json={"url": url})
    assert response.status_code == 422
    assert url not in response.text
    assert logged_in.app.state.services.integrations.launch_overrides(identifier) == {}


def test_override_requires_auth_admin_csrf_known_scoped_app(client, logged_in):
    identifier, endpoint = setup_apps(logged_in)
    url = "https://192.168.50.20:9000"
    assert (
        logged_in.put(endpoint.replace("fjordflix/", "unknown/"), json={"url": url}).status_code
        == 404
    )
    assert (
        logged_in.put(endpoint.replace(identifier, "missing"), json={"url": url}).status_code == 404
    )
    csrf = logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.put(endpoint, json={"url": url}).status_code == 403
    logged_in.headers["X-MediaHub-CSRF"] = csrf
    with logged_in.app.state.services.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    assert logged_in.put(endpoint, json={"url": url}).status_code == 403
    logged_in.cookies.clear()
    assert client.put(endpoint, json={"url": url}).status_code == 401


def test_lan_http_requires_explicit_consent_and_unknown_clear(logged_in):
    identifier, endpoint = setup_apps(logged_in)
    with logged_in.app.state.services.sessions.begin() as db:
        db.get(ExternalIntegration, identifier).allow_http = True
    assert logged_in.put(endpoint, json={"url": "http://192.168.50.20:9000"}).status_code == 200
    with logged_in.app.state.services.sessions.begin() as db:
        db.get(ExternalIntegration, identifier).snapshot = {"apps": []}
    assert logged_in.put(endpoint, json={"url": None}).status_code == 200
    assert logged_in.app.state.services.integrations.launch_overrides(identifier) == {}
