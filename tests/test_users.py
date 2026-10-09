from fastapi.testclient import TestClient
from mediahub.db import User
from sqlalchemy import select


def test_manage_hub_users(logged_in):
    client = logged_in
    own = client.get("/api/auth/me").json()["data"]["id"]
    assert client.delete(f"/api/users/{own}").status_code == 409
    assert client.post("/api/users", json={"username": "other", "password": "short"}).status_code == 400
    created = client.post("/api/users", json={"username": "other", "password": "long-password-123"})
    assert created.status_code == 200
    identifier = created.json()["data"]["id"]
    assert "password_hash" not in created.json()["data"]
    assert len(client.get("/api/users").json()["data"]) == 2
    assert client.put(f"/api/users/{identifier}", json={"username": "renamed"}).status_code == 200
    assert client.delete(f"/api/users/{identifier}").status_code == 200


def test_users_require_login(client):
    assert client.get("/api/users").status_code == 401


def test_user_management_requires_admin_and_csrf(logged_in):
    client = logged_in
    headers = dict(client.headers)
    client.headers.pop("X-MediaHub-CSRF")
    assert client.post("/api/users", json={"username": "other", "password": "long-password-123"}).status_code == 403
    client.headers.update(headers)
    with client.app.state.services.sessions.begin() as db:
        user = db.scalar(select(User).where(User.username == "tester"))
        user.role = "viewer"
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", json={"username": "other", "password": "long-password-123"}).status_code == 403


def test_password_reset_revokes_sessions(logged_in):
    client = logged_in
    response = client.post("/api/users", json={"username": "other", "password": "long-password-123"})
    identifier = response.json()["data"]["id"]
    with TestClient(client.app, base_url="http://127.0.0.1:18765") as other:
        assert other.post("/api/auth/login", json={"username": "other", "password": "long-password-123"}).status_code == 200
        assert client.put(f"/api/users/{identifier}", json={"username": "other", "password": "new-password-1234"}).status_code == 200
        assert other.get("/api/auth/me").status_code == 401