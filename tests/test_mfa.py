import time

import pyotp
from mediahub.db import Session, UserSecurity
from sqlalchemy import select

PASSWORD = "test-only-password-for-auth-123!"


def login(client, code=""):
    return client.post(
        "/api/v1/auth/login",
        json={"username": "secure", "password": PASSWORD, "secondFactor": code},
    )


def prepare(client):
    svc = client.app.state.services
    svc.auth.create_admin("secure", PASSWORD)
    response = login(client)
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    response = client.post("/api/v1/security/totp/enroll", json={"password": PASSWORD})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "<svg" in response.json()["data"]["qrSvg"]
    with svc.sessions() as db:
        row = db.scalar(select(UserSecurity))
        seed = svc.auth.mfa.store.get(row.secret_reference).decode()
        assert seed not in str(row.__dict__)
    return svc, seed


def enable(client):
    svc, seed = prepare(client)
    with svc.sessions() as db:
        previous_session = db.scalar(select(Session)).id
    response = client.post("/api/v1/security/totp/confirm", json={"code": pyotp.TOTP(seed).now()})
    assert response.status_code == 200
    codes = response.json()["data"]["recoveryCodes"]
    assert len(codes) == 10
    with svc.sessions() as db:
        assert db.get(Session, previous_session) is None
        row = db.scalar(select(UserSecurity))
        assert all(c not in row.recovery_hashes for c in codes)
    return svc, seed, codes


def test_totp_required_and_replay_rejected(client, monkeypatch):
    svc, seed, _ = enable(client)
    assert login(client).json()["error"]["code"] == "second_factor_required"
    assert login(client, pyotp.TOTP(seed).now()).status_code == 401
    now = time.time() + 30
    monkeypatch.setattr("mediahub.mfa.time.time", lambda: now)
    code = pyotp.TOTP(seed).at(now)
    response = login(client, code)
    assert response.status_code == 200
    assert response.json()["data"]["totpEnabled"]
    assert login(client, code).status_code == 401


def test_recovery_one_use_and_csrf(client):
    svc, seed, codes = enable(client)
    response = login(client, codes[0])
    assert response.status_code == 200
    csrf = response.json()["data"]["csrf"]
    assert login(client, codes[0]).status_code == 401
    # Stale pre-enrollment CSRF must be rejected even after successful MFA login.
    response = client.post(
        "/api/v1/security/totp/recovery-codes", json={"password": PASSWORD, "code": codes[1]}
    )
    assert response.status_code == 403
    client.headers["X-MediaHub-CSRF"] = csrf
    response = client.post(
        "/api/v1/security/totp/recovery-codes", json={"password": PASSWORD, "code": codes[1]}
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert login(client, codes[2]).status_code == 401


def test_wrong_code_and_expired_enrollment(client, monkeypatch):
    _, seed = prepare(client)
    response = client.post("/api/v1/security/totp/confirm", json={"code": "abcdef"})
    assert response.status_code == 422
    now = time.time() + 601
    monkeypatch.setattr("mediahub.mfa.time.time", lambda: now)
    response = client.post("/api/v1/security/totp/confirm", json={"code": pyotp.TOTP(seed).at(now)})
    assert response.status_code == 409


def test_security_no_seed_readback_and_session_revocation(client):
    svc, seed, codes = enable(client)
    response = login(client, codes[0])
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    response = client.get("/api/v1/security")
    assert response.json()["data"] == {
        "totpEnabled": True,
        "recoveryCodesRemaining": 9,
        "requireTotp": False,
    }
    assert seed not in response.text
    rows = client.get("/api/v1/security/sessions").json()["data"]
    assert len(rows) == 2
    current = next(row for row in rows if row["current"])
    assert "token" not in str(rows) and "csrf" not in str(rows)
    assert client.delete("/api/v1/security/sessions/" + current["id"]).status_code == 200
    assert client.get("/api/v1/security").status_code == 401


def test_password_change_revokes_sessions(client):
    svc = client.app.state.services
    svc.auth.create_admin("secure", PASSWORD)
    response = login(client)
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    response = client.post(
        "/api/v1/security/password", json={"password": PASSWORD, "newPassword": PASSWORD + "new"}
    )
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert login(client).status_code == 401


def test_required_policy_blocks_disable_and_unenrolled_account(client):
    from mediahub.auth import hasher
    from mediahub.db import User

    svc, _, codes = enable(client)
    response = login(client, codes[0])
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    response = client.post(
        "/api/v1/security/policy",
        json={"password": PASSWORD, "code": codes[1], "requireTotp": True},
    )
    assert response.status_code == 200
    response = client.post(
        "/api/v1/security/totp/disable", json={"password": PASSWORD, "code": codes[2]}
    )
    assert response.status_code == 409
    with svc.sessions.begin() as db:
        db.add(
            User(username="unenrolled", password_hash=hasher.hash(PASSWORD), role="administrator")
        )
    response = client.post(
        "/api/v1/auth/login", json={"username": "unenrolled", "password": PASSWORD}
    )
    assert response.status_code == 200
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    assert client.get("/api/v1/system/status").status_code == 403
    assert client.get("/api/v1/security").status_code == 200
    assert (
        client.post("/api/v1/security/totp/enroll", json={"password": PASSWORD}).status_code == 200
    )


def test_disable_requires_second_factor_and_revokes_sessions(client):
    _, _, codes = enable(client)
    response = login(client, codes[0])
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    assert (
        client.post("/api/v1/security/totp/disable", json={"password": PASSWORD}).status_code == 401
    )
    assert (
        client.post(
            "/api/v1/security/totp/disable", json={"password": PASSWORD, "code": codes[1]}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/security").status_code == 401
    assert login(client).status_code == 200
