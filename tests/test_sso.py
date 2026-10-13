import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from mediahub.db import InstalledApp


def configure(client):
    client.app.state.services.config.sso_app_urls = {"org.mediahub.mediaseed": "https://seed.example"}
    with client.app.state.services.sessions.begin() as db:
        db.add(InstalledApp(package_id="org.mediahub.mediaseed", name="MediaSeed", version="0.1.0", state="running"))


def authorize(client):
    verifier = "v" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    response = client.get("/api/v1/sso/authorize", params={"packageId": "org.mediahub.mediaseed", "state": "s" * 64, "challenge": challenge}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("https://seed.example/auth/hub/callback?")
    code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    return {"code": code, "verifier": verifier, "packageId": "org.mediahub.mediaseed"}


def test_sso_code_is_single_use_and_bound_to_pkce(logged_in):
    configure(logged_in)
    body = authorize(logged_in)
    assert logged_in.post("/api/v1/sso/exchange", json={**body, "verifier": "wrong" * 12}).status_code == 401
    response = logged_in.post("/api/v1/sso/exchange", json=body)
    assert response.status_code == 200
    token = response.json()["data"]["token"]
    assert response.json()["data"]["user"]["username"] == "tester"
    assert logged_in.post("/api/v1/sso/exchange", json=body).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    assert logged_in.get("/api/v1/sso/session?packageId=org.mediahub.mediaseed", headers=headers).status_code == 200
    assert logged_in.post("/api/auth/logout").status_code == 200
    assert logged_in.get("/api/v1/sso/session?packageId=org.mediahub.mediaseed", headers=headers).status_code == 401


def test_revoked_app_access_invalidates_existing_sso_session(logged_in):
    configure(logged_in)
    own = logged_in.get("/api/auth/me").json()["data"]["id"]
    response = logged_in.post("/api/v1/sso/exchange", json=authorize(logged_in))
    token = response.json()["data"]["token"]
    assert logged_in.put(f"/api/users/{own}", json={"username": "tester", "appRoles": {"org.mediahub.mediaseed": "denied"}}).status_code == 200
    assert logged_in.get("/api/v1/sso/session?packageId=org.mediahub.mediaseed", headers={"Authorization": "Bearer " + token}).status_code == 403
    assert logged_in.get("/api/v1/sso/authorize", params={"packageId": "org.mediahub.mediaseed", "state": "s" * 64, "challenge": "c" * 43}, follow_redirects=False).status_code == 403


@pytest.mark.parametrize("module,prefix,package,read_path", [
    ("mediaseed", "MEDIASEED", "org.mediahub.mediaseed", "/api/storage"),
    ("mediavpn", "MEDIAVPN", "org.mediahub.mediavpn", "/api/profiles"),
])
@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("local_ip", [False, True])
def test_actual_app_hub_roundtrip(logged_in, tmp_path, monkeypatch, module, prefix, package, read_path, external, local_ip):
    import importlib
    from pathlib import Path

    import httpx
    from fastapi.testclient import TestClient

    roots = (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3])
    app_root = next(root / module for root in roots if (root / module / module / "app.py").exists())
    monkeypatch.syspath_prepend(str(app_root))
    create_app = importlib.import_module(module + ".app").create_app

    configure(logged_in)
    local_origin = "https://192.168.1.50:18803" if local_ip else "https://seed.example"
    logged_in.app.state.services.config.sso_app_urls[package] = local_origin
    monkeypatch.setenv(prefix + "_HUB_URL", "https://127.0.0.1:18765")
    browser_origin = "https://custom.example" if external else local_origin
    if external:
        assert logged_in.put("/api/v1/app-settings/" + package, json={"externalUrl": browser_origin}).status_code == 200
    creation = logged_in.post("/api/users", json={"username": "member", "password": "synthetic-password-123", "appRoles": {package: "viewer"}, "language": "da"})
    assert creation.status_code == 200
    created = creation.json()["data"]
    with TestClient(logged_in.app, base_url="http://127.0.0.1:18765") as member:
        assert member.post("/api/auth/login", json={"username": "member", "password": "synthetic-password-123"}).status_code == 200
        app = create_app(tmp_path / "seed", local_origin, hub_transport=httpx.ASGITransport(app=logged_in.app))
        with TestClient(app, base_url=browser_origin) as seed:
            assert seed.get("/api/auth/status").json()["loginUrl"] == browser_origin + "/auth/hub/start"
            assert seed.get("/", headers={"Host": "unregistered.example"}).status_code == 400
            assert seed.post("/api/auth/logout", headers={"Origin": "https://unregistered.example"}).status_code == 403
            start = seed.get("/auth/hub/start", follow_redirects=False)
            authorize_url = urlsplit(start.headers["location"])
            authorization = member.get(authorize_url.path + "?" + authorize_url.query, follow_redirects=False)
            assert authorization.status_code == 303
            callback_url = urlsplit(authorization.headers["location"])
            assert callback_url.netloc == urlsplit(browser_origin).netloc
            callback = seed.get(callback_url.path + "?" + callback_url.query, follow_redirects=False)
            assert callback.status_code == 303
            assert seed.get("/api/auth/me").json()["username"] == "member"
            assert seed.get("/api/auth/me").json()["role"] == "viewer"
            assert seed.get("/api/auth/me").json()["language"] == "da"
            member.headers["X-MediaHub-CSRF"] = member.get("/api/auth/me").json()["data"]["csrf"]
            assert member.put("/api/v1/auth/preferences", json={"language": "en"}).status_code == 200
            assert seed.get("/api/auth/me").json()["language"] == "en"
            appearance = {"accent": "#d044e8", "secondary": "#797df2", "background": "#19314c", "depth": 40,
                          "style": "precision-terminal", "mode": "light", "density": "compact", "reducedMotion": True, "navigation": "dock-top"}
            assert member.put("/api/v1/auth/preferences", json={"appearance": appearance}).status_code == 200
            identity = seed.get("/api/auth/me").json()
            assert identity["managed"] is True
            assert identity["appearance"] == appearance
            assert identity["theme"] == logged_in.app.state.services.settings.get().theme
            appearance = {**appearance, "style": "soft-orbit", "accent": "#52a1c7", "mode": "system"}
            assert member.put("/api/v1/auth/preferences", json={"appearance": appearance}).status_code == 200
            assert seed.get("/api/auth/me").json()["appearance"] == appearance
            # Per-user settings never become another user's theme.
            assert logged_in.get("/api/auth/me").json()["data"]["appearance"] is None
            assert member.put("/api/v1/auth/preferences", json={"appearance": None}).status_code == 200
            assert seed.get("/api/auth/me").json()["appearance"] is None

            assert seed.get("/api/auth/me").json()["themeOverride"] is None
            assert seed.put("/api/auth/preferences", json={"themeOverride": "edge-signal"}).status_code == 403
            seed.headers["X-MediaSeed-CSRF" if module == "mediaseed" else "X-MediaVPN-CSRF"] = seed.get("/api/auth/me").json()["csrf"]
            assert seed.put("/api/auth/preferences", json={"themeOverride": "invalid"}).status_code == 422
            assert seed.put("/api/auth/preferences", json={"themeOverride": "edge-signal", "user_id": "someone-else"}).status_code == 422
            assert seed.put("/api/auth/preferences", json={"themeOverride": "edge-signal"}).status_code == 200
            assert seed.get("/api/auth/me").json()["themeOverride"] == "edge-signal"
            # The app override never writes into MediaHub preferences, and survives restart.
            assert member.get("/api/auth/me").json()["data"]["appearance"] is None
            reopened = create_app(tmp_path / "seed", local_origin, hub_transport=httpx.ASGITransport(app=logged_in.app))
            with TestClient(reopened, base_url=browser_origin) as second_device:
                second_device.cookies.update(seed.cookies)
                assert second_device.get("/api/auth/me").json()["themeOverride"] == "edge-signal"
            with TestClient(app, base_url=browser_origin) as another_user:
                another_start = another_user.get("/auth/hub/start", follow_redirects=False)
                another_url = urlsplit(another_start.headers["location"])
                another_auth = logged_in.get(another_url.path + "?" + another_url.query, follow_redirects=False)
                another_callback = urlsplit(another_auth.headers["location"])
                assert another_user.get(another_callback.path + "?" + another_callback.query, follow_redirects=False).status_code == 303
                another_identity = another_user.get("/api/auth/me").json()
                assert another_identity["themeOverride"] is None
                another_user.headers["X-MediaSeed-CSRF" if module == "mediaseed" else "X-MediaVPN-CSRF"] = another_identity["csrf"]
                assert another_user.put("/api/auth/preferences", json={"themeOverride": "soft-orbit"}).status_code == 200
                assert seed.get("/api/auth/me").json()["themeOverride"] == "edge-signal"
            assert seed.put("/api/auth/preferences", json={"themeOverride": None}).status_code == 200
            assert seed.get("/api/auth/me").json()["themeOverride"] is None

            # Hub overview grants are read-only, package-bound and recheck roles.
            import time

            from mediahub.auth import digest
            from mediahub.db import Session, Setting
            from sqlalchemy import select
            token = "o" * 64
            svc = logged_in.app.state.services
            with svc.sessions.begin() as db:
                parent = db.scalar(select(Session).where(Session.user_id == created["id"]))
                grant = {"sessionId": parent.id, "packageId": package, "expires": int(time.time()) + 30}
                db.add(Setting(key="sso:session:" + digest(token), value=grant))
            assert seed.get("/api/hub/overview").status_code == 401
            headers = {"Authorization": "Bearer " + token}
            assert seed.get("/api/hub/overview", headers=headers).status_code == 403
            with svc.sessions.begin() as db:
                row = db.scalar(select(Setting).where(Setting.key == "sso:session:" + digest(token)))
                row.value = {**grant, "scope": "overview"}
            overview = seed.get("/api/hub/overview", headers=headers)
            assert overview.status_code == 200, overview.text
            assert "checkedAt" in overview.json()
            assert "api_key" not in overview.text and "private_key" not in overview.text
            with TestClient(app, base_url=browser_origin) as reader:
                # The overview bearer alone creates no app cookie/write session.
                assert reader.get("/api/hub/overview", headers=headers).status_code == 200
                assert reader.get(read_path, headers=headers).status_code == 401
            assert logged_in.put(f"/api/users/{created['id']}", json={"username": "member", "appRoles": {}}).status_code == 200
            assert seed.get(read_path).status_code == 403
            assert seed.get("/api/hub/overview", headers=headers).status_code == 403
        if external:
            with TestClient(app, base_url="http://custom.example") as proxy:
                start = proxy.get("/auth/hub/start", follow_redirects=False)
                assert start.status_code == 303
                assert start.headers["location"].startswith("https://127.0.0.1:18765/api/v1/sso/authorize?")
            with TestClient(app, base_url=local_origin) as local:
                redirect = local.get("/auth/hub/start", follow_redirects=False)
                assert redirect.status_code == 303
                assert redirect.headers["location"] == browser_origin + "/auth/hub/start"
                assert "set-cookie" not in redirect.headers
