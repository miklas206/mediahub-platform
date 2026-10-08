"""Direct browser TLS is opt-in and cannot downgrade on bad key material."""

import secrets
import ssl

import pytest
from fastapi.testclient import TestClient
from mediahub.config import Config
from mediahub.main import create_app
from mediahub.serve import browser_server_config
from pydantic import ValidationError
from test_internal_tls import certificates, handshake


@pytest.mark.parametrize(
    "fields",
    [
        {"browser_tls_cert": "/cert.pem"},
        {"browser_tls_key": "/key.pem"},
        {"browser_tls_cert": "/cert.pem", "browser_tls_key": "/key.pem"},
    ],
)
def test_incomplete_or_plaintext_browser_tls_rejected(fields):
    with pytest.raises(ValidationError):
        Config(_env_file=None, **fields)


def test_direct_tls_on_same_port_with_verified_certificate(tmp_path):
    ca, cert, key = certificates(tmp_path)
    config = Config(
        _env_file=None,
        base_url="https://127.0.0.1:18765",
        browser_tls_cert=cert,
        browser_tls_key=key,
        allowed_origins=["https://127.0.0.1:18765"],
    )
    server = browser_server_config(lambda scope, receive, send: None, config, "127.0.0.1", 18765)
    server.load()
    assert server.port == 18765
    assert server.is_ssl and server.ssl is not None
    assert not server.proxy_headers and not server.access_log
    assert config.secure_cookies
    assert handshake(cert, key, ssl.create_default_context(cafile=str(ca))) == b"verified"


def test_invalid_key_cannot_fall_back_to_http(tmp_path):
    _, cert, _ = certificates(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _, _, key = certificates(other)
    config = Config(
        _env_file=None,
        base_url="https://127.0.0.1:18765",
        browser_tls_cert=cert,
        browser_tls_key=key,
    )
    server = browser_server_config(lambda scope, receive, send: None, config, "127.0.0.1", 18765)
    with pytest.raises(ssl.SSLError):
        server.load()


def test_default_listener_remains_unchanged():
    config = Config(_env_file=None)
    server = browser_server_config(lambda scope, receive, send: None, config, "127.0.0.1", 18765)
    assert not server.is_ssl
    assert server.port == 18765


def test_dual_listener_does_not_initialize_core_twice(tmp_path):
    _, cert, key = certificates(tmp_path)
    config = Config(_env_file=None, internal_tls_cert=cert, internal_tls_key=key)
    server = browser_server_config(lambda scope, receive, send: None, config, "127.0.0.1", 18765)
    server.load()
    from uvicorn.lifespan.off import LifespanOff

    assert server.lifespan_class is LifespanOff


def test_https_login_secure_cookie_session_and_csrf(tmp_path):
    config = Config(
        _env_file=None,
        data_dir=tmp_path,
        base_url="https://127.0.0.1:18765",
        allowed_origins=["https://127.0.0.1:18765"],
        mock_app=True,
    )
    with TestClient(create_app(config), base_url=config.base_url) as client:
        password = secrets.token_urlsafe(24)
        client.app.state.services.auth.create_admin("tls-test", password)
        response = client.post(
            "/api/v1/auth/login", json={"username": "tls-test", "password": password}
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert "Domain=" not in cookie
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 403
        assert (
            client.post(
                "/api/v1/auth/logout",
                headers={
                    "X-MediaHub-CSRF": response.json()["data"]["csrf"],
                    "Origin": config.base_url,
                },
            ).status_code
            == 200
        )
        assert client.get("/api/v1/auth/me").status_code == 401
