"""Primary hub keeps package metadata and per-user app access consistent."""
import copy
from unittest.mock import Mock

import pytest
from flask import template_rendered

import app as hub
from services.auth import AuthService
from services.install_state import InstallState


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    auth = AuthService(tmp_path / "hub.db")
    admin = auth.create_user("owner", "test-only-password", role="admin")
    reader = auth.create_user("reader", "test-only-password", role="user")
    monkeypatch.setattr(hub, "_auth", auth)
    monkeypatch.setattr(hub, "_install_state", InstallState(tmp_path))
    monkeypatch.setattr(hub, "_get_apps", lambda: [
        {"id": "allowed", "name": "Allowed", "port": 8099},
        {"id": "private", "name": "Private", "port": 8100},
    ])
    monkeypatch.setattr(auth, "get_user_app_access", lambda uid: [{"app_id": "allowed"}])
    monkeypatch.setattr(hub, "_fallback_app_url", lambda app: f"http://localhost:{app['port']}")
    definitions = [{"id": "calendar", "name": "Kalender", "version": "2.0.0",
                    "tagline": "Aftaler", "accent": "#8b5cf6", "icon": "calendar"},
                   {"id": "notepad", "name": "Whiteboard", "version": "2.0.0"}]
    monkeypatch.setattr(hub, "_get_package_defs", lambda: copy.deepcopy(definitions))
    monkeypatch.setattr(hub.package_manager, "is_installed", lambda pid: pid == "calendar")
    monkeypatch.setattr(hub, "_installed_package_version", lambda pid: "1.0.0")
    monkeypatch.setattr(hub._package_catalog, "refresh_if_stale", lambda: None)
    return hub.app.test_client(), admin, reader


def rendered_context(client, user_id, path):
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context)

    template_rendered.connect(capture, hub.app)
    try:
        response = client.get(path)
    finally:
        template_rendered.disconnect(capture, hub.app)
    assert response.status_code == 200
    return contexts[-1]


def test_launcher_combines_installed_packages_without_changing_versions(launcher):
    client, admin, _ = launcher
    context = rendered_context(client, admin, "/")
    assert context["app_name"] == "MediaHub"
    assert {app["id"] for app in context["apps"]} == {"allowed", "private"}
    assert [package["id"] for package in context["hub_packages"]] == ["calendar"]
    assert context["hub_packages"][0]["version"] == "1.0.0"
    assert context["hub_packages"][0]["update_available"] is True
    library = rendered_context(client, admin, "/packages")
    assert context["hub_packages"] == library["packages"]


def test_launcher_preserves_regular_user_app_access(launcher):
    client, _, reader = launcher
    context = rendered_context(client, reader, "/")
    assert [app["id"] for app in context["apps"]] == ["allowed"]
    assert [package["id"] for package in context["hub_packages"]] == ["calendar"]


def test_launcher_requires_login(launcher):
    client, _, _ = launcher
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.location


@pytest.mark.parametrize("method,path", [
    ("post", "/apps/private/start"), ("post", "/apps/allowed/stop"),
    ("post", "/apps/allowed/update/check"), ("post", "/apps/allowed/update/start"),
    ("post", "/apps/allowed/uninstall"), ("post", "/apps/allowed/install"),
    ("get", "/apps/allowed/wizard"), ("get", "/apps/allowed/install/status"),
    ("post", "/api/registry/refresh"),
])
def test_app_access_does_not_allow_lifecycle_changes(launcher, monkeypatch, method, path):
    client, _, reader = launcher
    start = Mock()
    stop = Mock()
    install = Mock()
    monkeypatch.setattr(hub.docker_mgr, "start", start)
    monkeypatch.setattr(hub.docker_mgr, "stop", stop)
    monkeypatch.setattr(hub._installer, "start_install", install)
    with client.session_transaction() as session:
        session["_user_id"] = str(reader)
        session["_fresh"] = True
    assert getattr(client, method)(path).status_code == 403
    start.assert_not_called()
    stop.assert_not_called()
    install.assert_not_called()


def test_status_api_has_the_same_visibility_as_launcher(launcher, monkeypatch):
    client, admin, reader = launcher
    monkeypatch.setattr(hub, "_ensure_install_state_for_existing_apps", lambda apps: None)
    monkeypatch.setattr(hub.docker_mgr, "get_status", lambda app: {"state": "running"})
    for user_id, expected in ((reader, {"allowed"}), (admin, {"allowed", "private"})):
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        assert set(client.get("/api/apps-status").json) == expected
