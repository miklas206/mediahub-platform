import time
from unittest.mock import AsyncMock

from mediahub.auth import digest
from mediahub.db import InstalledApp, Session, Setting
from mediahub.errors import DomainError
from sqlalchemy import select


def test_plex_port_sso_endpoint_checks_grant_and_preserves_prerequisite_error(
    logged_in, monkeypatch, tmp_path
):
    svc = logged_in.app.state.services
    svc.config.sso_app_urls = {"org.mediahub.mediavpn": "https://vpn.example"}
    token = "synthetic-vpn-session-" + "a" * 48
    with svc.sessions.begin() as db:
        parent = db.scalar(select(Session))
        db.add(
            InstalledApp(
                package_id="org.mediahub.mediavpn",
                name="MediaVPN",
                version="0.2.4",
                state="running",
            )
        )
        grant = {
            "packageId": "org.mediahub.mediavpn",
            "sessionId": parent.id,
            "expires": int(time.time()) + 600,
        }
        db.add(Setting(key="sso:session:" + digest(token), value=grant))
    endpoint = "/api/v1/sso/vpn-gateway/plex-port"
    method = AsyncMock(return_value={"plexPort": {"enabled": True, "ready": False}})
    monkeypatch.setattr(svc.vpn_gateway, "configure_plex_port", method)
    assert logged_in.put(endpoint, json={"enabled": True}).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    result = logged_in.put(endpoint, headers=headers, json={"enabled": True})
    assert result.status_code == 202, result.text
    method.assert_awaited_once_with(True)
    method.side_effect = DomainError(
        "plex_shared_vpn_required",
        "Connect Plex to the shared VPN before enabling its separate port",
        409,
    )
    result = logged_in.put(endpoint, headers=headers, json={"enabled": True})
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "plex_shared_vpn_required"
    # Exercise the actual app -> Core SSO route, including its error boundary.
    from pathlib import Path
    from urllib.parse import urlsplit

    import httpx
    from fastapi.testclient import TestClient

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "docker/bundled/mediavpn"))
    monkeypatch.setenv("MEDIAVPN_HUB_URL", "https://127.0.0.1:18765")
    from mediavpn.app import create_app

    app = create_app(
        tmp_path / "vpn",
        "https://vpn.example",
        hub_transport=httpx.ASGITransport(app=logged_in.app),
    )
    with TestClient(app, base_url="https://vpn.example") as vpn:
        start = vpn.get("/auth/hub/start", follow_redirects=False)
        target = urlsplit(start.headers["location"])
        authorize = logged_in.get(target.path + "?" + target.query, follow_redirects=False)
        target = urlsplit(authorize.headers["location"])
        assert vpn.get(target.path + "?" + target.query, follow_redirects=False).status_code == 303
        vpn.headers["X-MediaVPN-CSRF"] = vpn.get("/api/auth/me").json()["csrf"]
        result = vpn.put("/api/hub-web-gateway/plex-port", json={"enabled": True})
        assert result.status_code == 409, result.text
        assert (
            result.json()["detail"]
            == "Connect Plex to the shared VPN before enabling its separate port"
        )
    with svc.sessions.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key == "sso:session:" + digest(token)))
        row.value = {**grant, "scope": "overview"}
    assert logged_in.put(endpoint, headers=headers, json={"enabled": True}).status_code == 403
