# ruff: noqa: F811
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from test_cloudflare_management import BASE, ZONE, managed  # noqa: F401

PROFILE = "d" * 24


@pytest.fixture
def vpn_dns(logged_in, managed, monkeypatch):
    svc, manager, remote = managed
    report = {
        "profiles": [
            {
                "id": PROFILE,
                "name": "My VPN",
                "healthy": True,
                "publicIp": "185.111.109.2",
                "forwardedPort": 35458,
            }
        ]
    }
    monkeypatch.setattr(
        svc.shared_vpn, "vpn", AsyncMock(side_effect=lambda **kwargs: deepcopy(report))
    )
    original = manager.call

    async def call(method, path, body=None, params=None, token=None):
        if "/dns_records/" in path:
            remote["calls"].append((method, path, deepcopy(body)))
            row = next(row for row in remote["records"] if row.get("id") == path.rsplit("/", 1)[-1])
            if method == "PATCH":
                row.update(body)
            return deepcopy(row)
        if path.endswith("/dns_records") and method == "POST":
            remote["calls"].append((method, path, deepcopy(body)))
            row = {"id": "e" * 32, **body}
            remote["records"].append(row)
            return deepcopy(row)
        return await original(method, path, body, params, token)

    monkeypatch.setattr(manager, "call", call)
    return manager, remote, report


def create(client):
    return client.post(
        BASE + "/vpn-dns", json={"zoneId": ZONE, "label": "vpn", "profileId": PROFILE}
    )


def test_create_and_follow_verified_vpn_ip_without_touching_tunnels(logged_in, vpn_dns):
    manager, remote, report = vpn_dns
    remote["calls"].clear()
    response = create(logged_in)
    assert response.status_code == 200, response.text
    row = response.json()["data"]["vpnRecords"][0]
    assert row["status"] == "synced" and row["content"] == "185.111.109.2"
    assert remote["records"][0]["proxied"] is False
    before = len(remote["calls"])
    asyncio.run(manager.sync_vpn_dns())
    assert len(remote["calls"]) == before
    report["profiles"][0]["publicIp"] = "185.111.109.3"
    asyncio.run(manager.sync_vpn_dns(force=True))
    assert remote["records"][0]["content"] == "185.111.109.3"
    assert not any("cfd_tunnel" in path for _, path, _ in remote["calls"])
    assert remote["config"]["ingress"][0]["hostname"] == "manual.example.com"


@pytest.mark.parametrize("address", ["192.168.1.50", "127.0.0.1", None])
def test_unverified_private_or_missing_vpn_ip_never_writes_dns(logged_in, vpn_dns, address):
    _, remote, report = vpn_dns
    report["profiles"][0]["publicIp"] = address
    assert create(logged_in).status_code == 409
    assert not remote["records"]


def test_existing_record_is_preserved_and_unhealthy_profile_keeps_last_address(logged_in, vpn_dns):
    manager, remote, report = vpn_dns
    remote["records"].append(
        {
            "id": "f" * 32,
            "name": "vpn.example.com",
            "type": "A",
            "content": "1.1.1.1",
            "proxied": False,
        }
    )
    response = create(logged_in)
    assert response.json()["data"]["vpnRecords"][0]["status"] == "error"
    assert remote["records"][0]["content"] == "1.1.1.1"
    remote["records"].clear()
    # Retry the journaled intent after the operator resolves the conflict.
    asyncio.run(manager.sync_vpn_dns(force=True))
    assert remote["records"][0]["content"] == "185.111.109.2"
    report["profiles"][0]["healthy"] = False
    before = len(remote["calls"])
    asyncio.run(manager.sync_vpn_dns(force=True))
    assert manager.state()["vpnRecords"][0]["status"] == "blocked"
    assert len(remote["calls"]) == before
    assert remote["records"][0]["content"] == "185.111.109.2"


def test_manual_changes_pause_sync_and_browser_cannot_submit_target_ip(logged_in, vpn_dns):
    manager, remote, report = vpn_dns
    assert create(logged_in).status_code == 200
    remote["records"][0]["content"] = "1.1.1.1"
    report["profiles"][0]["publicIp"] = "185.111.109.3"
    asyncio.run(manager.sync_vpn_dns(force=True))
    assert remote["records"][0]["content"] == "1.1.1.1"
    assert manager.state()["vpnRecords"][0]["status"] == "error"
    assert (
        logged_in.post(
            BASE + "/vpn-dns",
            json={"zoneId": ZONE, "label": "test", "profileId": PROFILE, "content": "1.1.1.1"},
        ).status_code
        == 422
    )
    assert logged_in.post(BASE + "/tunnels", json={"name": "New"}).status_code == 405


def test_ipv6_uses_aaaa_and_lost_create_response_is_recovered(logged_in, vpn_dns, monkeypatch):
    from mediahub.errors import DomainError

    manager, remote, report = vpn_dns
    report["profiles"][0]["publicIp"] = "2606:4700:4700::1111"
    original = manager.call
    failed = False

    async def call(method, path, body=None, params=None, token=None):
        nonlocal failed
        response = await original(method, path, body, params, token)
        if method == "POST" and path.endswith("/dns_records") and not failed:
            failed = True
            raise DomainError("cloudflare_api", "Synthetic lost response", 502)
        return response

    monkeypatch.setattr(manager, "call", call)
    response = create(logged_in)
    assert response.json()["data"]["vpnRecords"][0]["status"] == "error"
    asyncio.run(manager.sync_vpn_dns(force=True))
    row = manager.state()["vpnRecords"][0]
    assert row["status"] == "synced" and row["type"] == "AAAA"
    assert len(remote["records"]) == 1
    assert remote["records"][0]["content"] == "2606:4700:4700::1111"


def test_automatic_sync_can_be_disabled_and_credentials_are_required(logged_in, vpn_dns):
    manager, remote, report = vpn_dns
    row = create(logged_in).json()["data"]["vpnRecords"][0]
    endpoint = BASE + "/vpn-dns/" + row["id"]
    assert logged_in.put(endpoint, json={"autoSync": False}).status_code == 200
    report["profiles"][0]["publicIp"] = "185.111.109.3"
    manager.vpn_deadline = 0
    before = len(remote["calls"])
    asyncio.run(manager.sync_vpn_dns())
    assert len(remote["calls"]) == before
    assert remote["records"][0]["content"] == "185.111.109.2"
    logged_in.delete(BASE + "/credentials")
    asyncio.run(manager.sync_vpn_dns(force=True))
    assert len(remote["calls"]) == before
