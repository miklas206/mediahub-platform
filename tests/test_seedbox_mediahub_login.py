from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.db import User, UserSecurity
from mediahub.errors import DomainError
from mediahub.seedbox_wizard_api import MediaHubClientImport, target
from sqlalchemy import select

PASSWORD = "synthetic-mediahub-password-123!"
URL = "/api/v1/seedbox/wizard/client/mediahub"


@pytest.fixture
def shared_login(client, monkeypatch):
    svc = client.app.state.services
    svc.auth.create_admin("tester", PASSWORD)
    response = client.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    client.base_url = "https://127.0.0.1:18765"
    agent = SimpleNamespace(request=AsyncMock(return_value={"accepted": True}))
    monkeypatch.setattr("mediahub.seedbox_wizard_api.target", lambda request: agent)
    return client, svc, agent


def payload(**changes):
    return {"revision": 3, "operation": "install", "password": PASSWORD, **changes}


@pytest.mark.parametrize("operation,path", [("install", "/client"), ("rotate", "/rotate/client")])
def test_copy_uses_verified_account_and_existing_secure_path(shared_login, operation, path):
    client, svc, agent = shared_login
    response = client.post(URL, json=payload(operation=operation))
    assert response.status_code == 202
    assert PASSWORD not in response.text
    agent.request.assert_awaited_once_with(
        "POST",
        "/v1/seedbox/wizard" + path,
        {"revision": 3, "webUsername": "tester", "webPassword": PASSWORD},
    )
    with svc.sessions() as db:
        assert db.scalar(select(User)).username == "tester"


def test_changed_password_requires_sign_in_again_and_copies_new_password(shared_login):
    client, svc, agent = shared_login
    updated_password = "synthetic-changed-password-123!"
    response = client.post(
        "/api/v1/security/password",
        json={"password": PASSWORD, "newPassword": updated_password},
    )
    assert response.status_code == 200
    assert response.json()["data"]["signInAgain"]
    assert (
        client.post(URL, json=payload(operation="rotate", password=updated_password)).status_code
        == 401
    )
    agent.request.assert_not_awaited()
    client.base_url = svc.config.base_url
    response = client.post(
        "/api/auth/login", json={"username": "tester", "password": updated_password}
    )
    assert response.status_code == 200, response.text
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    client.base_url = "https://127.0.0.1:18765"
    assert client.post(URL, json=payload(operation="rotate")).status_code == 401
    assert (
        client.post(URL, json=payload(operation="rotate", password=updated_password)).status_code
        == 202
    )
    agent.request.assert_awaited_once_with(
        "POST",
        "/v1/seedbox/wizard/rotate/client",
        {"revision": 3, "webUsername": "tester", "webPassword": updated_password},
    )


def test_password_reauthentication_and_throttling(shared_login):
    client, _, agent = shared_login
    for _ in range(5):
        response = client.post(URL, json=payload(password="wrong-test-password"))
        assert response.status_code == 401
        assert "wrong-test-password" not in response.text
    assert client.post(URL, json=payload()).status_code == 429
    agent.request.assert_not_awaited()


@pytest.mark.parametrize(
    "username,password", [("tester", "test-short-12"), ("invalid user", PASSWORD)]
)
def test_incompatible_login_does_not_weaken_seedbox_policy(shared_login, username, password):
    from mediahub.auth import hasher

    client, svc, agent = shared_login
    with svc.sessions.begin() as db:
        user = db.scalar(select(User))
        user.username = username
        user.password_hash = hasher.hash(password)
    response = client.post(URL, json=payload(password=password))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "seedbox_login_incompatible"
    assert password not in response.text
    agent.request.assert_not_awaited()


def test_csrf_admin_session_and_mfa_are_not_bypassed(shared_login, monkeypatch):
    client, svc, agent = shared_login
    csrf = client.headers.pop("X-MediaHub-CSRF")
    assert client.post(URL, json=payload()).status_code == 403
    client.headers["X-MediaHub-CSRF"] = csrf
    with svc.sessions.begin() as db:
        db.scalar(select(User)).role = "viewer"
    assert client.post(URL, json=payload()).status_code == 403
    with svc.sessions.begin() as db:
        db.scalar(select(User)).role = "administrator"

    def require_mfa(db, user_id, password, code):
        assert password == PASSWORD
        assert code == "synthetic-code"
        raise DomainError("second_factor_required", "Authenticator required", 401)

    monkeypatch.setattr(svc.auth, "reauthenticate", require_mfa)
    assert client.post(URL, json=payload(secondFactor="synthetic-code")).status_code == 401
    client.cookies.clear()
    assert client.post(URL, json=payload()).status_code == 401
    agent.request.assert_not_awaited()


def test_enabled_mfa_is_verified_by_existing_reauthentication(shared_login, monkeypatch):
    client, svc, agent = shared_login
    with svc.sessions.begin() as db:
        user = db.scalar(select(User))
        db.add(UserSecurity(user_id=user.id, enabled=True))
    calls = []

    def verify(db, row, code):
        calls.append(code)
        if code != "synthetic-code":
            raise DomainError("invalid_second_factor", "Invalid authenticator code", 401)

    monkeypatch.setattr(svc.auth.mfa, "verify", verify)
    assert client.post(URL, json=payload()).status_code == 401
    agent.request.assert_not_awaited()
    assert client.post(URL, json=payload(secondFactor="synthetic-code")).status_code == 202
    assert calls == ["", "synthetic-code"]
    assert "secondFactor" not in agent.request.call_args.args[2]


def test_https_guard_is_preserved(shared_login, monkeypatch):
    client, _, agent = shared_login
    monkeypatch.setattr("mediahub.seedbox_wizard_api.target", target)
    client.base_url = "http://127.0.0.1:18765"
    response = client.post(URL, json=payload())
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "https_required"
    agent.request.assert_not_awaited()


def test_secret_model_and_invalid_input_never_return_secrets(shared_login):
    client, _, agent = shared_login
    body = MediaHubClientImport(**payload(secondFactor="synthetic-code"))
    assert "password" not in body.model_dump()
    assert "secondFactor" not in body.model_dump()
    assert PASSWORD not in repr(body)
    response = client.post(URL, json=payload(webUsername="attacker"))
    assert response.status_code == 422
    assert PASSWORD not in response.text
    agent.request.assert_not_awaited()


def test_forward_failure_is_not_reported_as_success(shared_login):
    client, _, agent = shared_login
    agent.request.side_effect = DomainError("revision_conflict", "Reload the wizard", 409)
    response = client.post(URL, json=payload(operation="rotate"))
    assert response.status_code == 409
    assert PASSWORD not in response.text
