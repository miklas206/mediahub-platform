import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mediahub.cloudflare_management import CloudflareManagement
from mediahub.db import InstalledApp, User
from mediahub.errors import DomainError
from sqlalchemy import select

ACCOUNT = "a" * 32
ZONE = "b" * 32
TUNNEL = "11111111-2222-4333-8444-555555555555"
TOKEN = "synthetic-cloudflare-token-secret"
BASE = "/api/v1/cloudflare/manage"


@pytest.fixture
def managed(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    manager = svc.cloudflare_management
    svc.config.base_url = "https://192.168.1.50:18765"
    logged_in.base_url = "https://127.0.0.1:18765"
    svc.config.allowed_origins.append("https://127.0.0.1:18765")
    remote = {
        "config": {
            "ingress": [
                {
                    "hostname": "manual.example.com",
                    "service": "http://192.168.1.20:80",
                    "originRequest": {"httpHostHeader": "manual"},
                },
                {"service": "http_status:404"},
            ]
        },
        "records": [],
        "calls": [],
    }

    async def call(method, path, body=None, params=None, token=None):
        remote["calls"].append((method, path, copy.deepcopy(body)))
        if path.endswith("/cfd_tunnel"):
            return {"id": TUNNEL} if method == "POST" else []
        if path.endswith("/token"):
            return "connector-private-token"
        if path == "/zones/" + ZONE:
            return {"name": "example.com"}
        if path.endswith("/dns_records"):
            if method == "POST":
                remote["records"].append(body)
                return {"id": "record"}
            return remote["records"]
        if path.endswith("/configurations"):
            if method == "PUT":
                remote["config"] = copy.deepcopy(body["config"])
            return {"config": copy.deepcopy(remote["config"])}
        raise AssertionError(path)

    monkeypatch.setattr(manager, "call", call)
    response = logged_in.put(BASE + "/credentials", json={"accountId": ACCOUNT, "token": TOKEN})
    assert response.status_code == 200, response.text
    assert logged_in.post(BASE + "/tunnels", json={"name": "Home"}).status_code == 200
    return svc, manager, remote


def link(client, **values):
    return client.post(
        BASE + "/routes",
        json={
            "tunnelId": TUNNEL,
            "zoneId": ZONE,
            "hostname": "hub.example.com",
            "packageId": "mediahub",
            **values,
        },
    )


def test_create_encrypts_credentials_and_download_requires_owned_tunnel(logged_in, managed):
    _, manager, remote = managed
    assert TOKEN not in logged_in.get(BASE).text
    assert TOKEN.encode() not in (manager.store.directory / "api_token.sealed").read_bytes()
    creates = [
        body
        for method, path, body in remote["calls"]
        if method == "POST" and path.endswith("/cfd_tunnel")
    ]
    assert creates == [{"name": "Home", "config_src": "cloudflare"}]
    assert logged_in.post(BASE + "/tunnels", json={"name": "Home"}).status_code == 409
    response = logged_in.post(BASE + "/tunnels/" + TUNNEL + "/token")
    assert response.content == b"connector-private-token"
    assert response.headers["cache-control"] == "no-store"
    assert (
        logged_in.post(BASE + "/tunnels/99999999-2222-4333-8444-555555555555/token").status_code
        == 409
    )


def test_sync_tracks_origin_preserves_manual_rules_and_avoids_repeated_writes(logged_in, managed):
    svc, manager, remote = managed
    manual = copy.deepcopy(remote["config"]["ingress"][0])
    response = link(logged_in)
    assert response.status_code == 200, response.text
    route = response.json()["data"]["routes"][0]
    assert route["status"] == "synced"
    assert "https://hub.example.com" in svc.config.origins
    assert logged_in.get("https://hub.example.com/api/auth/status").status_code == 200
    assert logged_in.get("https://unregistered.example.com/api/auth/status").status_code == 400
    assert remote["records"][0]["content"] == TUNNEL + ".cfargotunnel.com"
    assert remote["config"]["ingress"][1] == manual
    assert remote["config"]["ingress"][0]["originRequest"] == {
        "caPool": "/etc/cloudflared/mediahub-ca.pem"
    }
    before = len(remote["calls"])
    asyncio.run(manager.sync())
    assert len(remote["calls"]) == before
    svc.config.base_url = "https://192.168.1.60:19765"
    asyncio.run(manager.sync())
    assert remote["config"]["ingress"][0]["service"] == svc.config.base_url
    assert remote["config"]["ingress"][1] == manual
    assert len(remote["records"]) == 1
    # Persisted state survives a management service restart.
    restored = CloudflareManagement(svc)
    assert restored.public()["routes"][0]["lastApplied"] == svc.config.base_url
    assert restored.configured()
    assert (
        logged_in.put(BASE + "/routes/" + route["id"], json={"autoSync": False}).status_code == 200
    )
    svc.config.base_url = "https://192.168.1.61:19765"
    before = len(remote["calls"])
    asyncio.run(manager.sync())
    assert len(remote["calls"]) == before


@pytest.mark.parametrize("conflict", ["dns", "ingress"])
def test_conflicts_do_not_overwrite_existing_remote_configuration(logged_in, managed, conflict):
    svc, manager, remote = managed
    if conflict == "dns":
        remote["records"] = [{"type": "A", "content": "203.0.113.10"}]
        assert link(logged_in).json()["data"]["routes"][0]["status"] == "error"
    else:
        link(logged_in)
        remote["config"]["ingress"][0]["service"] = "http://192.168.1.99:1234"
        svc.config.base_url = "https://192.168.1.60:19765"
    snapshot = copy.deepcopy(remote["config"])
    asyncio.run(manager.sync(force=True))
    assert remote["config"] == snapshot
    assert manager.public()["routes"][0]["status"] == "error"


def test_managed_app_uses_live_docker_ip_and_port_not_public_url(logged_in, managed, monkeypatch):
    svc, manager, remote = managed
    package = "org.mediahub.mediavpn"
    with svc.sessions.begin() as db:
        db.add(
            InstalledApp(package_id=package, name="MediaVPN", version="managed", state="running")
        )
    svc.config.sso_app_urls[package] = "https://192.168.1.50:18803"
    svc.managed_apps.policy[package] = SimpleNamespace()
    monkeypatch.setattr(
        svc.managed_apps,
        "containers",
        AsyncMock(
            return_value=[
                {
                    "Id": "a" * 64,
                    "Config": {"Labels": {"com.docker.compose.service": "sso-proxy"}},
                    "State": {"Running": True},
                }
            ]
        ),
    )
    inspect = AsyncMock(
        return_value={
            "NetworkSettings": {
                "Ports": {"443/tcp": [{"HostIp": "192.168.1.70", "HostPort": "19803"}]}
            }
        }
    )
    monkeypatch.setattr(svc.managed_apps, "docker", inspect)
    response = link(logged_in, packageId=package, hostname="vpn.example.com")
    assert response.json()["data"]["routes"][0]["lastApplied"] == "https://192.168.1.70:19803"
    inspect.return_value["NetworkSettings"]["Ports"]["443/tcp"][0]["HostPort"] = "20803"
    asyncio.run(manager.sync())
    assert remote["config"]["ingress"][0]["service"] == "https://192.168.1.70:20803"
    assert (
        logged_in.get("/api/v1/app-settings/" + package).json()["data"]["externalUrl"]
        == "https://vpn.example.com"
    )


def test_failed_publish_is_persisted_and_retried_without_duplicate_dns(
    logged_in, managed, monkeypatch
):
    _, manager, remote = managed
    original = manager.call
    failed = False

    async def call(method, path, *args, **kwargs):
        nonlocal failed
        if method == "PUT" and not failed:
            failed = True
            raise DomainError("cloudflare_api", "Synthetic API failure", 502)
        return await original(method, path, *args, **kwargs)

    monkeypatch.setattr(manager, "call", call)
    assert link(logged_in).json()["data"]["routes"][0]["status"] == "error"
    assert len(remote["records"]) == 1
    asyncio.run(manager.sync())
    assert manager.public()["routes"][0]["status"] == "synced"
    assert len(remote["records"]) == 1


def test_zone_and_local_origin_validation(logged_in, managed):
    svc, _, remote = managed
    assert link(logged_in, hostname="app.other.com").status_code == 422
    svc.config.base_url = "https://public.example.com"
    assert link(logged_in).status_code == 409
    assert not remote["records"]


def test_admin_csrf_https_and_disconnect(logged_in, managed):
    svc, manager, remote = managed
    assert logged_in.delete(BASE + "/credentials").status_code == 200
    before = len(remote["calls"])
    asyncio.run(manager.sync())
    assert len(remote["calls"]) == before
    svc.config.dev_mode = False
    logged_in.base_url = "http://127.0.0.1:18765"
    assert logged_in.get(BASE).status_code in {400, 403}
    svc.config.dev_mode = True
    logged_in.base_url = "https://127.0.0.1:18765"
    csrf = logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.post(BASE + "/tunnels", json={"name": "Blocked"}).status_code == 403
    logged_in.headers["X-MediaHub-CSRF"] = csrf
    with svc.sessions.begin() as db:
        db.scalar(select(User).where(User.username == "tester")).role = "user"
    assert logged_in.get(BASE).status_code == 403


def test_rate_limit_backoff_and_sanitized_errors(logged_in, monkeypatch):
    manager = logged_in.app.state.services.cloudflare_management
    original = httpx.AsyncClient
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            429, headers={"Retry-After": "120"}, json={"success": False, "errors": [TOKEN]}
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    for _ in range(2):
        with pytest.raises(DomainError) as error:
            asyncio.run(manager.call("GET", "/accounts/" + ACCOUNT + "/cfd_tunnel", token=TOKEN))
        assert TOKEN not in error.value.message
    assert len(calls) == 1
