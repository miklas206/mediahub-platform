from fastapi.testclient import TestClient
from mediahub.db import User
from sqlalchemy import select


def test_administrator_login_preserves_and_requires_username_case(client):
    auth = client.app.state.services.auth
    password = "Mixed-Password-1234"
    auth.create_admin("  TestAdmin  ", password)
    assert auth.users()[0]["username"] == "TestAdmin"
    for username in ("testadmin", "TESTADMIN"):
        assert client.post("/api/auth/login", json={
            "username": username, "password": password,
        }).status_code == 401
    assert client.post("/api/auth/login", json={
        "username": "TestAdmin", "password": password.lower(),
    }).status_code == 401
    response = client.post("/api/auth/login", json={
        "username": "TestAdmin", "password": password,
    })
    assert response.status_code == 200
    assert response.json()["data"]["username"] == "TestAdmin"


def test_managed_username_case_is_preserved_on_create_and_rename(logged_in):
    password = "Mixed-Password-1234"
    created = logged_in.post("/api/users", json={
        "username": "OtherUser", "password": password,
    })
    assert created.status_code == 200
    assert created.json()["data"]["username"] == "OtherUser"
    identifier = created.json()["data"]["id"]
    renamed = logged_in.put(f"/api/users/{identifier}", json={"username": "OTHERuser"})
    assert renamed.status_code == 200
    assert renamed.json()["data"]["username"] == "OTHERuser"
    with TestClient(logged_in.app, base_url="http://127.0.0.1:18765") as member:
        for username in ("OtherUser", "otheruser"):
            assert member.post("/api/auth/login", json={
                "username": username, "password": password,
            }).status_code == 401
        assert member.post("/api/auth/login", json={
            "username": "OTHERuser", "password": password,
        }).status_code == 200


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


def test_regular_user_is_not_a_hub_administrator(logged_in):
    created = logged_in.post("/api/users", json={"username": "member", "password": "long-password-123", "appRoles": {"org.mediahub.mediaseed": "viewer"}})
    assert created.status_code == 200
    assert created.json()["data"]["role"] == "user"
    identifier = created.json()["data"]["id"]
    assert logged_in.app.state.services.auth.app_role(identifier, "org.mediahub.mediaseed") == "viewer"
    with TestClient(logged_in.app, base_url="http://127.0.0.1:18765") as member:
        assert member.post("/api/auth/login", json={"username": "member", "password": "long-password-123"}).status_code == 200
        assert member.get("/api/users").status_code == 403
        assert member.get("/api/storage").status_code == 403
        assert member.get("/api/apps").json()["data"] == []


def test_last_administrator_cannot_be_demoted(logged_in):
    own = logged_in.get("/api/auth/me").json()["data"]["id"]
    assert logged_in.put(f"/api/users/{own}", json={"username": "tester", "role": "user"}).status_code == 409
