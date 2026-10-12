from types import SimpleNamespace

import pytest
from mediahub.db import InstalledApp, User
from sqlalchemy import select


def test_address_save_and_reset(logged_in):
    svc = logged_in.app.state.services
    svc.config.operator_app_urls["org.mediahub.mediavpn"] = "http://127.0.0.1:18802"
    path = "/api/v1/app-settings/org.mediahub.mediavpn"
    assert logged_in.get(path).json()["data"]["localUrl"] == "http://127.0.0.1:18802"
    assert logged_in.get(path).json()["data"]["removableApp"] is None
    response = logged_in.put(path, json={"externalUrl": "https://VPN.example.com:443/"})
    assert response.status_code == 200
    assert response.json()["data"]["externalUrl"] == "https://vpn.example.com"
    assert response.json()["data"]["routingManaged"] is False
    assert logged_in.get(path).json()["data"]["externalUrl"] == "https://vpn.example.com"
    assert logged_in.put(path, json={"externalUrl": ""}).json()["data"]["externalUrl"] == ""


@pytest.mark.parametrize("address", ["javascript:alert(1)", "http://example.com", "https://user:password@example.com", "https://example.com/path", "https://example.com?token=secret", "https://example.com/#fragment", "https://example.com:99999", "https://example.com\\evil", "https://example.com\n.evil"])
def test_reject_unsafe_addresses(logged_in, address):
    package = logged_in.get("/api/apps").json()["data"][0]["packageId"]
    assert logged_in.put("/api/v1/app-settings/" + package, json={"externalUrl": address}).status_code == 400


def test_sso_address_change_updates_registration_and_reset(logged_in):
    logged_in.app.state.services.config.sso_app_urls["org.mediahub.mediaseed"] = "https://seed.example"
    path = "/api/v1/app-settings/org.mediahub.mediaseed"
    changed = logged_in.put(path, json={"externalUrl": "https://other.example"})
    assert changed.status_code == 200
    assert changed.json()["data"]["ssoOrigin"] == "https://other.example"
    assert logged_in.get("/api/v1/sso/origin?packageId=org.mediahub.mediaseed").json()["data"]["origin"] == "https://other.example"
    assert logged_in.put(path, json={"externalUrl": ""}).json()["data"]["ssoOrigin"] == "https://seed.example"
    assert logged_in.put(path, json={"externalUrl": "https://seed.example"}).status_code == 200


def test_settings_require_admin_and_csrf(logged_in):
    package = logged_in.get("/api/apps").json()["data"][0]["packageId"]
    path = "/api/v1/app-settings/" + package
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.put(path, json={"externalUrl": ""}).status_code == 403
    with logged_in.app.state.services.sessions.begin() as db:
        db.scalar(select(User).where(User.username == "tester")).role = "user"
    assert logged_in.get(path).status_code == 403


def test_unknown_app_has_no_settings(logged_in):
    assert logged_in.get("/api/v1/app-settings/org.mediahub.unknown").status_code == 404


def test_only_installed_supported_apps_offer_uninstall(logged_in):
    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        app = InstalledApp(package_id="org.mediahub.jellyfin", name="Jellyfin", version="1", state="running", is_mock=False)
        db.add(app)
        db.flush()
        identifier = app.id
    path = "/api/v1/app-settings/org.mediahub.jellyfin"
    assert logged_in.get(path).json()["data"]["removableApp"] is None
    svc.apps.adapters[identifier] = SimpleNamespace(definition=SimpleNamespace(binding_key="container_installation_jellyfin", view_id="container"))
    assert logged_in.get(path).json()["data"]["removableApp"]["id"] == identifier
    with svc.sessions.begin() as db:
        db.get(InstalledApp, identifier).state = "uninstalled"
    svc.config.operator_app_urls["org.mediahub.jellyfin"] = "http://127.0.0.1:8096"
    assert logged_in.get(path).json()["data"]["removableApp"] is None
