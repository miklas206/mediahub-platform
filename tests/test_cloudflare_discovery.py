# ruff: noqa: F811
import asyncio
import copy

import pytest
from mediahub.errors import DomainError
from test_cloudflare_management import BASE, TUNNEL, ZONE, managed  # noqa: F401


def test_discovery_fetches_records_and_caches_polling(logged_in, managed, monkeypatch):
    _, manager, remote = managed
    original = manager.call
    record = {"id": "c" * 32, "name": "existing.example.com", "type": "A", "content": "203.0.113.1"}

    async def call(method, path, **kwargs):
        if path.endswith("/dns_records"):
            return [record]
        return await original(method, path, **kwargs)

    monkeypatch.setattr(manager, "call", call)
    manager.discovery_at = 0
    data = logged_in.get(BASE).json()["data"]
    assert data["discovery"]["records"] == [{**record, "zoneId": ZONE, "proxied": False}]
    assert data["discovery"]["apps"][0]["origin"] == "https://192.168.1.50:18765"
    assert not data["discovery"]["apps"][1]["origin"]
    before = copy.deepcopy(remote["calls"])
    logged_in.get(BASE)
    logged_in.post(BASE + "/discover")
    assert remote["calls"] == before


def test_complete_pagination_and_explicit_limit(logged_in, managed, monkeypatch):
    _, manager, _ = managed
    pages = []

    async def call(method, path, params):
        pages.append(params["page"])
        return [{"id": "item"}] * (50 if params["page"] < 3 else 1)

    monkeypatch.setattr(manager, "call", call)
    assert len(asyncio.run(manager.pages("/zones"))) == 101
    assert pages == [1, 2, 3]

    async def endless(method, path, params):
        return [{}] * 50

    monkeypatch.setattr(manager, "call", endless)
    with pytest.raises(DomainError, match="narrow the token scope"):
        asyncio.run(manager.pages("/zones"))


def test_permission_failure_preserves_previous_records_and_is_scoped(
    logged_in, managed, monkeypatch
):
    _, manager, _ = managed
    state = manager.state()
    state["discovery"]["records"] = [{"id": "old", "zoneId": ZONE, "name": "old.example.com"}]
    manager.save(state)
    original = manager.call

    async def call(method, path, **kwargs):
        if path.endswith("/dns_records"):
            raise DomainError("cloudflare_permissions", "Missing DNS permission", 409)
        return await original(method, path, **kwargs)

    monkeypatch.setattr(manager, "call", call)
    manager.discovery_at = 0
    data = logged_in.get(BASE).json()["data"]["discovery"]
    assert not data["complete"]
    assert data["records"][0]["name"] == "old.example.com"
    assert "DNS" in data["issues"][0]["permission"]
    assert data["issues"][0]["resource"] == "example.com"


def test_dns_only_token_can_connect_and_reports_missing_tunnel_access(
    logged_in, managed, monkeypatch
):
    _, manager, _ = managed
    original = manager.call

    async def call(method, path, **kwargs):
        if path.endswith("/cfd_tunnel"):
            raise DomainError("cloudflare_permissions", "Missing tunnel permission", 409)
        return await original(method, path, **kwargs)

    monkeypatch.setattr(manager, "call", call)
    response = logged_in.put(
        BASE + "/credentials", json={"accountId": "a" * 32, "token": "synthetic-dns-only-token"}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["configured"]
    assert data["discovery"]["zones"][0]["id"] == ZONE
    assert data["discovery"]["issues"][0]["resource"] == "tunnels"
    assert "Cloudflare Tunnel" in data["discovery"]["issues"][0]["permission"]


def test_discovered_route_uses_server_hostname_and_preserves_other_dns(
    logged_in, managed, monkeypatch
):
    _, manager, remote = managed
    original = manager.call

    async def call(method, path, body=None, **kwargs):
        if "/dns_records/" in path:
            return {"name": "existing.example.com", "type": "A", "content": "203.0.113.10"}
        return await original(method, path, body, **kwargs)

    monkeypatch.setattr(manager, "call", call)
    payload = {"tunnelId": TUNNEL, "zoneId": ZONE, "packageId": "mediahub"}
    response = logged_in.post(BASE + "/routes/discovered", json={**payload, "recordId": "c" * 32})
    assert response.status_code == 409
    assert not remote["records"]
    response = logged_in.post(BASE + "/routes/discovered", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["routes"][0]["hostname"] == "mediahub.example.com"
    assert remote["records"][0]["content"] == TUNNEL + ".cfargotunnel.com"


def test_existing_tunnel_requires_explicit_selection_and_remote_config(
    logged_in, managed, monkeypatch
):
    _, manager, remote = managed
    tunnel = "99999999-2222-4333-8444-555555555555"
    original = manager.call

    async def call(method, path, body=None, **kwargs):
        if path.endswith("/" + tunnel):
            return {"id": tunnel, "name": "Existing", "config_src": "cloudflare"}
        return await original(method, path, body, **kwargs)

    monkeypatch.setattr(manager, "call", call)
    assert not any(row["id"] == tunnel for row in manager.state()["tunnels"])
    before = copy.deepcopy(remote["config"])
    response = logged_in.post(BASE + "/tunnels/" + tunnel + "/adopt")
    assert response.status_code == 200
    assert any(row["id"] == tunnel for row in response.json()["data"]["tunnels"])
    assert remote["config"] == before
    assert (
        logged_in.post(
            BASE + "/routes/discovered",
            json={
                "tunnelId": tunnel,
                "zoneId": ZONE,
                "packageId": "mediahub",
                "recordId": "../outside",
            },
        ).status_code
        == 422
    )
