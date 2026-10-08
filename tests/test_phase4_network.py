import secrets

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from mediahub.config import Config
from mediahub.main import create_app
from mediahub.network import absolute_url
from mediahub.serve import InternalAPI
from pydantic import ValidationError


def test_public_url_and_lan_cookies(tmp_path):
    config = Config(
        data_dir=tmp_path, public_url="https://media.example", cookie_samesite="lax", _env_file=None
    )
    app = create_app(config)
    password = secrets.token_urlsafe(24)
    with TestClient(app, base_url=config.base_url) as client:
        app.state.services.auth.create_admin("test", password)
        credentials = {"username": "test", "password": password}
        local = client.post("/api/auth/login", json=credentials)
        assert local.status_code == 200
        assert "Secure" not in local.headers["set-cookie"]
        assert "SameSite=lax" in local.headers["set-cookie"]
        client.base_url = config.public_url
        public = client.post("/api/auth/login", json=credentials)
        assert "Secure" in public.headers["set-cookie"]
        assert "Domain=" not in public.headers["set-cookie"]
        client.base_url = "http://media.example"
        assert client.post("/api/auth/login", json=credentials).status_code == 403


@pytest.mark.parametrize("trusted", [False, True])
def test_forwarded_headers_have_explicit_trust_boundary(tmp_path, trusted):
    config = Config(
        data_dir=tmp_path,
        public_url="https://media.example",
        trusted_proxies=["127.0.0.1"] if trusted else [],
        _env_file=None,
    )
    app = create_app(config)

    @app.get("/probe")
    async def probe(request: Request):
        return {
            "scheme": request.url.scheme,
            "client": request.client.host,
            "url": absolute_url(config, "/apps", request=request),
        }

    app.router.routes.insert(0, app.router.routes.pop())

    with TestClient(
        app,
        client=("127.0.0.1", 5000),
        base_url="http://media.example" if trusted else config.base_url,
    ) as client:
        response = client.get(
            "/probe",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": "198.51.100.10",
                "X-Forwarded-Host": "attacker.example",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scheme"] == ("https" if trusted else "http")
        assert data["client"] == ("198.51.100.10" if trusted else "127.0.0.1")
        assert "attacker" not in data["url"]


def test_network_config_and_absolute_urls():
    for invalid in [
        {"public_url": "http://media.example"},
        {"trusted_proxies": ["0.0.0.0/0"]},
        {"trusted_proxies": ["::/0"]},
        {"cookie_samesite": "none"},
        {"internal_tls_cert": "/cert.pem"},
    ]:
        with pytest.raises(ValidationError):
            Config(**invalid, _env_file=None)
    config = Config(public_url="https://media.example", _env_file=None)
    assert absolute_url(config, "/apps", public=True) == "https://media.example/apps"
    assert absolute_url(config, "/apps") == config.base_url + "/apps"
    for unsafe in ["//attacker.example", "https://attacker.example", "/\\attacker", "/\nfoo"]:
        with pytest.raises(ValueError):
            absolute_url(config, unsafe)


def test_internal_listener_has_no_ui_or_login(client):
    internal = TestClient(InternalAPI(client.app), base_url="https://127.0.0.1:18766")
    assert internal.get("/api/v1/health").status_code == 200
    assert internal.get("/").status_code == 404
    assert internal.post("/api/auth/login", json={}).status_code == 404
    internal.close()


@pytest.mark.parametrize("spoof", [False, True])
def test_https_deployment_rejects_plaintext_before_credentials(tmp_path, spoof):
    config = Config(data_dir=tmp_path, base_url="https://media.example", _env_file=None)
    with TestClient(create_app(config), base_url="http://media.example") as client:
        headers = {"X-Forwarded-Proto": "https"} if spoof else {}
        response = client.post(
            "/api/v1/auth/login", json={"password": "do-not-echo"}, headers=headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "https_required"
        assert "do-not-echo" not in response.text
        assert "location" not in response.headers
        assert client.get("/api/v1/security", headers=headers).status_code == 403


def test_https_deployment_accepts_explicitly_trusted_proxy(tmp_path):
    config = Config(
        data_dir=tmp_path,
        base_url="https://media.example",
        trusted_proxies=["127.0.0.1"],
        _env_file=None,
    )
    with TestClient(
        create_app(config), base_url="http://media.example", client=("127.0.0.1", 5000)
    ) as client:
        password = secrets.token_urlsafe(24)
        client.app.state.services.auth.create_admin("test", password)
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "test", "password": password},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
