import asyncio
import base64
import hashlib
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mediahub.app_releases import latest_release
from mediahub.db import InstalledApp, Setting, User
from mediahub.managed_apps import ManagedAdapter
from sqlalchemy import select


@pytest.mark.parametrize("state", ["uninstalled", "removing", "installing", "failed"])
def test_stale_installation_binding_is_not_an_available_vpn_or_domain_app(logged_in, state):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add(InstalledApp(package_id="org.mediahub.plex", name="Plex", version="1", state=state))
        db.add(Setting(key="plex_installation", value={"hostId": "gone"}))
    assert svc.shared_vpn.bindings() == []
    assert svc.cloudflare_management.public()["apps"] == [{"packageId": "mediahub", "name": "MediaHub"}]


def test_shared_status_does_not_query_uninstalled_seed(logged_in, monkeypatch):
    service = logged_in.app.state.services.shared_vpn
    machine = AsyncMock(return_value={"ready": False})
    monkeypatch.setattr(service, "vpn", machine)
    assert asyncio.run(service.public())["apps"] == []
    machine.assert_awaited_once_with()


@pytest.mark.parametrize("runtime,expected", [
    ({"Running": True, "Health": {"Status": "unhealthy"}}, "unhealthy"),
    ({"Running": True, "Restarting": True}, "degraded"),
    ({"Running": False}, "unknown"),
])
def test_managed_health_surfaces_container_failures(logged_in, monkeypatch, runtime, expected):
    manager = logged_in.app.state.services.managed_apps
    monkeypatch.setattr(manager, "containers", AsyncMock(return_value=[{
        "Config": {"Labels": {"com.docker.compose.service": "app"}}, "State": runtime,
    }]))
    report = asyncio.run(ManagedAdapter(manager, "org.mediahub.mediavpn").health())
    assert report.status == expected
    assert report.checks[0].status == expected


def test_upstream_version_is_fetched_without_claiming_unknown_installed_version():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"tag_name": "v10.11.1"}))
    result = asyncio.run(latest_release("org.mediahub.jellyfin", None, transport=transport))
    assert result["latestVersion"] == "10.11.1"
    assert result["installedVersion"] is None
    assert result["upstreamUpdateAvailable"] is None
    assert not result["updateAvailable"]


def test_vpn_app_delegation_requires_hub_admin_and_live_parent_session(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    package = "org.mediahub.mediavpn"
    svc.config.sso_app_urls[package] = "https://vpn.example"
    with svc.sessions.begin() as db:
        db.add(InstalledApp(package_id=package, name="MediaVPN", version="0.1.3", state="running"))
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redirect = logged_in.get("/api/v1/sso/authorize", params={"packageId": package, "state": "s" * 64, "challenge": challenge}, follow_redirects=False)
    code = parse_qs(urlsplit(redirect.headers["location"]).query)["code"][0]
    grant = logged_in.post("/api/v1/sso/exchange", json={"code": code, "verifier": verifier, "packageId": package}).json()["data"]
    headers = {"Authorization": "Bearer " + grant["token"]}
    monkeypatch.setattr(svc.shared_vpn, "public", AsyncMock(return_value={"apps": []}))
    monkeypatch.setattr(svc.vpn_gateway, "public", AsyncMock(return_value={"routes": []}))
    configure = AsyncMock(return_value={"routes": [], "enabled": False})
    monkeypatch.setattr(svc.vpn_gateway, "configure", configure)
    assert logged_in.get("/api/v1/sso/vpn/apps").status_code == 401
    assert logged_in.get("/api/v1/sso/vpn/apps", headers=headers).status_code == 200
    assert logged_in.get("/api/v1/sso/vpn-gateway").status_code == 401
    assert logged_in.get("/api/v1/sso/vpn-gateway", headers=headers).status_code == 200
    assert logged_in.put("/api/v1/sso/vpn-gateway/config", headers=headers, json={"enabled": False, "routes": []}).status_code == 202
    configure.assert_awaited_once()
    with svc.sessions.begin() as db:
        db.scalar(select(User).where(User.username == "tester")).role = "user"
    assert logged_in.get("/api/v1/sso/vpn/apps", headers=headers).status_code == 403
    assert logged_in.get("/api/v1/sso/vpn-gateway", headers=headers).status_code == 403
