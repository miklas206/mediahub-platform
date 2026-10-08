import secrets

import pytest
from fastapi.testclient import TestClient
from mediahub.config import Config
from mediahub.main import create_app


@pytest.fixture
def client(tmp_path):
    config = Config(
        dev_mode=True,
        mock_app=True,
        data_dir=tmp_path / "data",
        storage_roots=[tmp_path],
        sample_seconds=1,
        _env_file=None,
    )
    with TestClient(create_app(config), base_url="http://127.0.0.1:18765") as client:
        yield client


@pytest.fixture
def logged_in(client):
    password = secrets.token_urlsafe(24)
    client.app.state.services.auth.create_admin("tester", password)
    response = client.post("/api/auth/login", json={"username": "tester", "password": password})
    assert response.status_code == 200
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    return client
