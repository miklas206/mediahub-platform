import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

from mediahub.db import InstalledApp


def configure(client):
    client.app.state.services.config.sso_app_urls = {"org.mediahub.mediaseed": "https://seed.example"}
    with client.app.state.services.sessions.begin() as db:
        db.add(InstalledApp(package_id="org.mediahub.mediaseed", name="MediaSeed", version="0.1.0", state="running"))


def authorize(client):
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    response = client.get("/api/v1/sso/authorize", params={"packageId": "org.mediahub.mediaseed", "state": "s" * 64, "challenge": challenge}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("https://seed.example/auth/hub/callback?")
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    return {"code": code, "verifier": verifier, "packageId": "org.mediahub.mediaseed"}


def test_sso_code_is_single_use_and_bound_to_pkce(logged_in):
    configure(logged_in)
    body = authorize(logged_in)
    assert logged_in.post("/api/v1/sso/exchange", json={**body, "verifier": "wrong" * 12}).status_code == 401
    response = logged_in.post("/api/v1/sso/exchange", json=body)
    assert response.status_code == 200
    token = response.json()["data"]["token"]
    assert response.json()["data"]["user"]["username"] == "tester"
    assert logged_in.post("/api/v1/sso/exchange", json=body).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    assert logged_in.get("/api/v1/sso/session?packageId=org.mediahub.mediaseed", headers=headers).status_code == 200
    assert logged_in.post("/api/auth/logout").status_code == 200
    assert logged_in.get("/api/v1/sso/session?packageId=org.mediahub.mediaseed", headers=headers).status_code == 401


def test_revoked_app_access_invalidates_existing_sso_session(logged_in):
    configure(logged_in)
    own = logged_in.get("/api/auth/me").json()["data"]["id"]
    response = logged_in.post("/api/v1/sso/exchange", json=authorize(logged_in))
    token = response.json()["data"]["token"]
    assert logged_in.put(f"/api/users/{own}", json={"username": "tester", "appRoles": {"org.mediahub.mediaseed": "denied"}}).status_code == 200
    assert logged_in.get("/api/v1/sso/session?packageId=org.mediahub.mediaseed", headers={"Authorization": "Bearer " + token}).status_code == 403
    assert logged_in.get("/api/v1/sso/authorize", params={"packageId": "org.mediahub.mediaseed", "state": "s" * 64, "challenge": "c" * 43}, follow_redirects=False).status_code == 403


def test_actual_mediaseed_hub_roundtrip(logged_in, tmp_path, monkeypatch):
    from pathlib import Path

    import httpx
    from fastapi.testclient import TestClient

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "mediaseed"))
    from mediaseed.app import create_app

    configure(logged_in)
    monkeypatch.setenv("MEDIASEED_HUB_URL", "https://127.0.0.1:18765")
    created = logged_in.post("/api/users", json={"username": "member", "password": "synthetic-password-123", "appRoles": {"org.mediahub.mediaseed": "viewer"}}).json()["data"]
    with TestClient(logged_in.app, base_url="http://127.0.0.1:18765") as member:
        assert member.post("/api/auth/login", json={"username": "member", "password": "synthetic-password-123"}).status_code == 200
        app = create_app(tmp_path / "seed", "https://seed.example", hub_transport=httpx.ASGITransport(app=logged_in.app))
        with TestClient(app, base_url="https://seed.example") as seed:
            start = seed.get("/auth/hub/start", follow_redirects=False)
            authorize_url = urlsplit(start.headers["location"])
            authorization = member.get(authorize_url.path + "?" + authorize_url.query, follow_redirects=False)
            assert authorization.status_code == 303
            callback_url = urlsplit(authorization.headers["location"])
            callback = seed.get(callback_url.path + "?" + callback_url.query, follow_redirects=False)
            assert callback.status_code == 303
            assert seed.get("/api/auth/me").json()["username"] == "member"
            assert seed.get("/api/auth/me").json()["role"] == "viewer"
            assert logged_in.put(f"/api/users/{created['id']}", json={"username": "member", "appRoles": {}}).status_code == 200
            assert seed.get("/api/storage").status_code == 403