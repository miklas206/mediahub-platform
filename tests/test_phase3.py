import asyncio
import json
import secrets
import time

import pytest
from mediahub.db import Host, PairingRequest
from mediahub.errors import DomainError
from mediahub.hosts import path_shape, remote_address
from sqlalchemy import select
from test_phase2 import bootstrap
from test_phase2 import setup_client as phase2_client


@pytest.fixture
def setup_client(tmp_path):
    yield from phase2_client.__wrapped__(tmp_path)


@pytest.mark.parametrize(
    "address",
    [
        "http://192.168.1.5",
        "https://127.0.0.1",
        "https://169.254.1.1",
        "https://8.8.8.8",
        "https://user:pass@192.168.1.5",
        "https://192.168.1.5/path",
        "https://localhost",
        "https://192.168.1.5:0",
    ],
)
def test_remote_address_rejects_unsafe_targets(address):
    with pytest.raises(DomainError):
        remote_address(address)


@pytest.mark.parametrize(
    "path", ["/", "../media", "/media/../etc", "C:\\", "relative", "/media/\x00"]
)
def test_mapping_path_shape(path):
    with pytest.raises(DomainError):
        path_shape(path)


def test_pairing_single_use_encrypted_and_persistent(setup_client):
    bootstrap(setup_client)
    svc = setup_client.app.state.services
    invite = svc.hosts.invitation("Remote", "https://192.168.50.10:18767")
    secret = secrets.token_urlsafe(48)
    paired = asyncio.run(svc.hosts.pair(invite["token"], "https://192.168.50.10:18767", secret))
    with pytest.raises(DomainError):
        asyncio.run(svc.hosts.pair(invite["token"], "https://192.168.50.10:18767", secret))
    with svc.sessions() as db:
        row = db.get(Host, paired["host_id"])
        assert secret not in row.encrypted_token
        assert svc.catalog.cipher.decrypt(row.encrypted_token.encode()).decode() == secret
        assert invite["token"] != db.scalar(select(PairingRequest)).token_hash
    serialized = json.dumps(svc.hosts.list())
    assert secret not in serialized and invite["token"] not in serialized
    assert svc.hosts.client(paired["host_id"]).token == secret


def test_expired_pairing_and_http_blocked(setup_client):
    bootstrap(setup_client)
    svc = setup_client.app.state.services
    invite = svc.hosts.invitation("Expired", "https://192.168.50.11")
    with svc.sessions.begin() as db:
        db.scalar(select(PairingRequest)).expires_at = int(time.time()) - 1
    with pytest.raises(DomainError):
        asyncio.run(
            svc.hosts.pair(invite["token"], "https://192.168.50.11", secrets.token_urlsafe(48))
        )
    assert (
        setup_client.post(
            "/api/v1/hosts/pairing", json={"name": "Remote", "address": "https://192.168.50.12"}
        ).status_code
        == 403
    )


def test_logical_storage_two_hosts_no_file_changes(setup_client):
    bootstrap(setup_client)
    svc = setup_client.app.state.services
    root = setup_client.storage_root
    media = root / "downloads"
    media.mkdir()
    sentinel = media / "keep.mkv"
    sentinel.write_bytes(b"existing media")
    logical = svc.hosts.add_storage("downloads", "downloads", "dataset-A")
    invite = svc.hosts.invitation("Seedbox future", "https://192.168.50.13")
    remote = asyncio.run(
        svc.hosts.pair(invite["token"], "https://192.168.50.13", secrets.token_urlsafe(48))
    )["host_id"]
    assert svc.hosts.map_storage(logical["id"], "local", str(media), "ro")["mounted"] is False
    svc.hosts.map_storage(logical["id"], remote, "/data/downloads", "rw")
    mappings = svc.hosts.storage()[0]["mappings"]
    assert len(mappings) == 2
    resolved = asyncio.run(svc.hosts.resolve(logical["id"], "local"))
    assert resolved["path"] == str(media.resolve())
    assert not resolved["datasetIdentityVerified"]
    with pytest.raises(DomainError, match="read-only"):
        asyncio.run(svc.hosts.resolve(logical["id"], "local", "rw"))
    assert sentinel.read_bytes() == b"existing media"
    assert svc.agent.calls == [("POST", "/v1/directories/inspect")]
    assert not (root / "data").exists()


def test_hosts_refresh_and_auth(setup_client):
    assert setup_client.get("/api/v1/hosts").status_code == 401
    bootstrap(setup_client)
    response = setup_client.post("/api/v1/hosts/refresh")
    assert response.status_code == 200
    assert response.json()["data"][0]["status"] == "online"
    assert response.json()["data"][0]["last_seen"]
    svc = setup_client.app.state.services

    async def offline():
        return {"connected": False}

    svc.agent.status = offline
    asyncio.run(svc.hosts.refresh())
    assert svc.hosts.list()[0]["status"] == "offline"


def test_selected_host_and_seedbox_policy(setup_client):
    bootstrap(setup_client)
    svc = setup_client.app.state.services
    svc.config.seedbox_requires_remote_host = True
    plan = setup_client.post("/api/v1/catalog/org.mediahub.seedbox/plan", json={"host_id": "local"})
    assert plan.status_code == 200
    data = plan.json()["data"]
    assert data["hostId"] == "local" and data["recommendedIsolation"] == "dedicated-host"
    assert not data["executable"]
    assert any("separate host" in item for item in data["blockers"])
    assert any("capabilities" in item for item in data["blockers"])
    assert (
        setup_client.post(
            "/api/v1/catalog/org.mediahub.plex/plan", json={"host_id": "nonexistent"}
        ).status_code
        == 404
    )


def test_api_mapping_and_csrf(setup_client):
    bootstrap(setup_client)
    data = setup_client.post(
        "/api/v1/storage/logical", json={"name": "tv", "kind": "tv", "dataset_ref": "owner/shows"}
    ).json()["data"]
    response = setup_client.put(
        f"/api/v1/storage/logical/{data['id']}/mapping",
        json={"host_id": "local", "path": "/media/shows", "access": "ro"},
    )
    assert response.status_code == 200 and response.json()["data"]["filesChanged"] is False
    assert (
        setup_client.put(
            f"/api/v1/storage/logical/{data['id']}/mapping",
            json={"host_id": "local", "path": "/media/shows", "access": "admin"},
        ).status_code
        == 422
    )
    setup_client.headers.pop("X-MediaHub-CSRF")
    assert setup_client.post("/api/v1/hosts/refresh").status_code == 403


def test_https_pairing_endpoint(setup_client):
    bootstrap(setup_client)
    setup_client.base_url = "https://127.0.0.1:18765"
    response = setup_client.post(
        "/api/v1/hosts/pairing",
        json={"name": "TLS agent", "address": "https://192.168.50.80:18767"},
    )
    assert response.status_code == 200
    token = response.json()["data"]["token"]
    secret = secrets.token_urlsafe(48)
    response = setup_client.post(
        "/api/v1/hosts/pair",
        json={"token": token, "address": "https://192.168.50.80:18767", "agent_token": secret},
    )
    assert response.status_code == 200 and response.json()["data"]["paired"]
    assert secret not in response.text and token not in response.text


def test_production_compose_is_scoped():
    from pathlib import Path

    import yaml

    compose = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "compose.production.yaml").read_text()
    )
    assert set(compose["services"]) == {"core", "agent"}
    core, agent = compose["services"]["core"], compose["services"]["agent"]
    assert not any("docker.sock" in v for v in core["volumes"])
    assert any("docker.sock" in v for v in agent["volumes"])
    assert "ports" not in agent
    assert core["ports"] == ["${LAN_IP}:18765:18765"]
    assert all(s["cap_drop"] == ["ALL"] and not s.get("privileged") for s in [core, agent])
    assert all("media-v2" not in v for s in [core, agent] for v in s["volumes"])
    assert compose["networks"]["control"]["internal"]
