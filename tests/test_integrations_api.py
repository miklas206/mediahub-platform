import json

import httpx
from mediahub.db import ExternalIntegration, User
from mediahub.integrations.fjordhub import FjordHubClient
from sqlalchemy import select


def body():
    return {
        "name": "Private FjordHub",
        "baseUrl": "https://192.168.50.20:8443",
        "accessToken": "test-private-access-token-123456",
    }


def wire(client, code=200):
    def handler(request):
        assert request.method == "GET"
        if code != 200:
            return httpx.Response(code)
        if request.url.path == "/api/integrations/v1/resources":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "/api/integrations/v1/apps": {
                    "items": [
                        {
                            "id": "new-app",
                            "name": "Dynamic future app",
                            "description": "Future catalog entry",
                        }
                    ]
                },
            }[request.url.path],
        )

    client.app.state.services.integrations.provider_factory = lambda url, token, **kw: (
        FjordHubClient(url, token, transport=httpx.MockTransport(handler), **kw)
    )


def test_integration_auth_and_csrf(client, logged_in):
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert client.post("/api/v1/integrations/fjordhub", json=body()).status_code == 403


def test_save_never_returns_or_persists_plain_token(logged_in):
    client = logged_in
    response = client.post("/api/v1/integrations/fjordhub", json=body())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["tokenConfigured"]
    secret = body()["accessToken"]
    assert secret not in response.text
    assert secret not in client.get("/api/v1/integrations").text
    svc = client.app.state.services
    for path in svc.config.data_dir.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
    assert "secret_reference" not in data
    with svc.sessions() as db:
        saved = db.scalar(select(ExternalIntegration))
        assert svc.integrations.store.get(saved.secret_reference).decode() == secret


def test_test_save_sync_dynamic_and_disconnect(logged_in):
    client = logged_in
    wire(client)
    response = client.post("/api/v1/integrations/fjordhub/test", json=body())
    assert response.json()["data"]["status"] == "online"
    assert client.get("/api/v1/integrations").json()["data"] == []
    identifier = client.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    data = client.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"]
    assert data["snapshot"]["apps"][0]["name"] == "Dynamic future app"
    assert data["lastSuccessfulSync"]
    response = client.post(f"/api/v1/integrations/{identifier}/disconnect", json={})
    assert response.json()["data"]["tokenConfigured"] is False
    assert client.post(f"/api/v1/integrations/{identifier}/refresh", json={}).status_code == 409


def test_multiple_and_real_auth_errors(logged_in):
    wire(logged_in, 401)
    result = logged_in.post("/api/v1/integrations/fjordhub/test", json=body()).json()["data"]
    assert result["status"] == "authentication_failed"
    for _ in range(2):
        assert logged_in.post("/api/v1/integrations/fjordhub", json=body()).status_code == 200
    assert len(logged_in.get("/api/v1/integrations").json()["data"]) == 2
    assert logged_in.get("/api/v1/health").status_code == 200


def test_validation_error_never_echoes_token(logged_in):
    invalid = {**body(), "accessToken": body()["accessToken"] + "\n"}
    response = logged_in.post("/api/v1/integrations/fjordhub", json=invalid)
    assert response.status_code == 422
    assert body()["accessToken"] not in response.text
    assert "accessToken" not in json.dumps(response.json().get("data"))


def test_production_http_cannot_receive_credentials(logged_in):
    logged_in.app.state.services.config.dev_mode = False
    response = logged_in.post("/api/v1/integrations/fjordhub", json=body())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "https_required"


def test_viewer_cannot_configure_or_test_tokens(logged_in):
    with logged_in.app.state.services.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    for endpoint in ("/fjordhub", "/fjordhub/test"):
        assert logged_in.post("/api/v1/integrations" + endpoint, json=body()).status_code == 403


def test_offline_retains_last_success_and_marks_stale(logged_in):
    wire(logged_in)
    identifier = logged_in.post("/api/v1/integrations/fjordhub", json=body()).json()["data"]["id"]
    first = logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"]
    with logged_in.app.state.services.sessions.begin() as db:
        db.get(ExternalIntegration, identifier).next_sync = 0
    wire(logged_in, 503)
    latest = logged_in.post(f"/api/v1/integrations/{identifier}/refresh", json={}).json()["data"]
    assert latest["snapshot"]["status"] == "offline"
    assert latest["snapshot"]["stale"] is True
    assert latest["snapshot"]["apps"] == first["snapshot"]["apps"]
    assert latest["lastSuccessfulSync"] == first["lastSuccessfulSync"]
