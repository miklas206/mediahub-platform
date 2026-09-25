import asyncio
import hashlib
import json
import secrets

import pytest
from mediahub.apps.framework import Registry
from mediahub.apps.manifest import Environment, Manifest, parse_manifest
from mediahub.config import ROOT, Config
from mediahub.contracts import Health
from mediahub.db import Session, User, migrate
from mediahub.errors import DomainError
from pydantic import ValidationError
from sqlalchemy import inspect, select, text


def manifest_data():
    return parse_manifest(ROOT / "apps/mock/manifest.yaml").model_dump()


def test_config_validation():
    for value in ["ftp://localhost", "https://user:secret@example.com", "https://example.com/path"]:
        with pytest.raises(ValidationError):
            Config(base_url=value, _env_file=None)
    with pytest.raises(ValidationError):
        Config(trusted_proxies=["*"], _env_file=None)
    with pytest.raises(ValidationError):
        Config(sample_seconds=0, _env_file=None)
    assert Config(base_url="https://media.example", _env_file=None).secure_cookies
    assert not Config(_env_file=None).secure_cookies


def test_health_model():
    assert Health(status="healthy", summary="Ready").lastChecked
    with pytest.raises(ValidationError):
        Health(status="green", summary="Bad status")


def test_manifest_valid():
    manifest = parse_manifest(ROOT / "apps/mock/manifest.yaml")
    assert manifest.id == "org.mediahub.mock"
    assert manifest.services == {}
    assert "properties" in Manifest.model_json_schema()


def test_cloudflared_manifest_has_guided_secret_setup():
    manifest = parse_manifest(ROOT / "apps/cloudflared/manifest.yaml")
    assert manifest.availability == "available"
    assert [step.id for step in manifest.installGuide] == [
        "prepare-domain",
        "create-tunnel",
        "connect-origin",
        "verify-route",
    ]
    fields = {field.name: field for field in manifest.configFields}
    assert fields["public_hostnames"].required is True
    assert fields["status_url"].required is False
    assert not any(field.secret for field in manifest.configFields)
    assert all(
        not step.helpUrl or step.helpUrl.startswith("https://developers.cloudflare.com/")
        for step in manifest.installGuide
    )


def test_install_guide_rejects_unknown_fields_and_unsafe_help_links():
    data = manifest_data()
    data["installGuide"] = [
        {
            "id": "setup",
            "title": "Setup",
            "description": "Guided setup",
            "fields": ["missing"],
        }
    ]
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)
    data["installGuide"][0]["fields"] = []
    data["installGuide"][0]["helpUrl"] = "https://user:secret@example.com/help"
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "latest"),
        ("id", "bad id"),
        ("capabilities", ["host.root"]),
        ("schemaVersion", 9),
    ],
)
def test_manifest_rejects_invalid(field, value):
    data = manifest_data()
    data[field] = value
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


def test_manifest_no_unknown_fields_or_missing_references():
    data = manifest_data()
    data["run_shell"] = "not permitted"
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)
    data.pop("run_shell")
    data["services"] = {"bad": {"image": "missing"}}
    with pytest.raises(ValidationError):
        Manifest.model_validate(data)


def test_yaml_alias_rejected(tmp_path):
    path = tmp_path / "alias.yaml"
    path.write_text("x: &anchor yes\ny: *anchor", encoding="utf-8")
    with pytest.raises(DomainError, match="YAML"):
        parse_manifest(path)


def test_environment_reference_exclusivity():
    assert Environment(secretRef="token").secretRef == "token"
    with pytest.raises(ValidationError):
        Environment(secretRef="token", literal="bad")


def test_duplicate_yaml_keys_rejected(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text("schemaVersion: 1\nschemaVersion: 2", encoding="utf-8")
    with pytest.raises(DomainError):
        parse_manifest(path)


def test_cookie_flags_and_expiry(client):
    service = client.app.state.services
    password = secrets.token_urlsafe(24)
    service.auth.create_admin("admin", password)
    response = client.post("/api/auth/login", json={"username": "admin", "password": password})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    token = client.cookies.get("mediahub_session")
    with service.sessions.begin() as db:
        row = db.scalar(select(Session))
        row.expires_at = 1
    with pytest.raises(DomainError):
        service.auth.authenticate(token)


def test_schema_matches_migration(client):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from mediahub.db import Base

    with client.app.state.services.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []


def test_compose_is_isolated_and_has_no_proxy():
    import yaml

    compose = yaml.safe_load((ROOT / "compose.dev.yaml").read_text())
    assert set(compose["services"]) == {"core"}
    core = compose["services"]["core"]
    assert core["ports"] == ["127.0.0.1:18765:18765"]
    assert core["volumes"] == ["foundation-data:/data"]
    assert "docker.sock" not in json.dumps(compose)


def test_registry_duplicates_and_missing_dependency():
    registry = Registry()
    manifest = Manifest.model_validate(manifest_data())
    registry.register(manifest)
    registry.validate_dependencies()
    with pytest.raises(DomainError, match="already registered"):
        registry.register(manifest)
    data = manifest_data()
    data["id"] = "org.mediahub.second"
    data["dependencies"] = [{"id": "org.mediahub.missing", "version": ">=1.0.0"}]
    registry.register(Manifest.model_validate(data))
    with pytest.raises(DomainError, match="dependency"):
        registry.validate_dependencies()


def test_registry_cycle():
    registry = Registry()
    for name, dependency in [("one", "two"), ("two", "one")]:
        data = manifest_data()
        data["id"] = "org.mediahub." + name
        data["dependencies"] = [{"id": "org.mediahub." + dependency, "version": ">=0.1.0"}]
        registry.register(Manifest.model_validate(data))
    with pytest.raises(DomainError, match="cycle"):
        registry.validate_dependencies()


def test_health_and_no_admin(client):
    assert client.get("/api/health").json()["data"]["status"] == "healthy"
    from mediahub import __version__

    assert client.get("/api/v1/health").json()["data"]["version"] == __version__
    assert client.get("/api/auth/status").json()["data"]["needsSetup"]
    assert client.get("/api/system/status").status_code == 401
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/events/stream").status_code == 401


def test_auth_password_and_session_storage(logged_in):
    svc = logged_in.app.state.services
    assert not logged_in.get("/api/auth/status").json()["data"]["needsSetup"]
    with svc.sessions() as db:
        user = db.scalar(select(User))
        session = db.scalar(select(Session))
        assert user.password_hash.startswith("$argon2id$")
        cookie = logged_in.cookies.get("mediahub_session")
        assert session.token_hash == hashlib.sha256(cookie.encode()).hexdigest()
        assert session.token_hash != cookie
    assert logged_in.get("/api/auth/me").json()["data"]["role"] == "administrator"


def test_auth_csrf_logout_and_revocation(logged_in):
    token = logged_in.cookies.get("mediahub_session")
    response = logged_in.post("/api/auth/logout", headers={"X-MediaHub-CSRF": "incorrect"})
    assert response.status_code == 403
    assert logged_in.post("/api/auth/logout").status_code == 200
    assert logged_in.get("/api/apps").status_code == 401
    with pytest.raises(DomainError):
        logged_in.app.state.services.auth.authenticate(token)


def test_bad_origin_and_no_password_echo(client):
    secret = secrets.token_urlsafe(24)
    body = {"username": "unknown", "password": secret}
    assert (
        client.post(
            "/api/auth/login", json=body, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    response = client.post("/api/auth/login", json={**body, "extra": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert secret not in client.post("/api/auth/login", json=body).text


def test_login_rate_limit(client):
    body = {"username": "unknown", "password": "incorrect"}
    for _ in range(5):
        assert client.post("/api/auth/login", json=body).status_code == 401
    assert client.post("/api/auth/login", json=body).status_code == 429


def test_first_admin_cannot_be_replaced(logged_in):
    with pytest.raises(DomainError, match="already exists"):
        logged_in.app.state.services.auth.create_admin("other", secrets.token_urlsafe(24))


def test_migrations_are_repeatable_and_schema_complete(client):
    svc = client.app.state.services
    migrate(svc.config.database_url)
    tables = set(inspect(svc.engine).get_table_names())
    assert {
        "users",
        "sessions",
        "settings",
        "installed_apps",
        "storage_locations",
        "storage_mappings",
        "events",
        "activity_log",
        "notifications",
        "update_history",
        "alembic_version",
    } <= tables
    with svc.engine.connect() as db:
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_metrics_real_and_protected(logged_in):
    response = logged_in.get("/api/system/status")
    data = response.json()["data"]
    assert data["ram"]["totalBytes"] > 0
    assert data["disk"]["totalBytes"] > 0
    assert data["uptimeSeconds"] > 0
    assert data["hostname"]
    assert response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


def test_mock_lifecycle_and_activity(logged_in):
    app = next(item for item in logged_in.get("/api/apps").json()["data"] if item["isMock"])
    assert app["isMock"] and app["health"]["status"] == "healthy"
    app_id = app["id"]
    for action, expected in [
        ("stop", "stopped"),
        ("stop", "stopped"),
        ("start", "running"),
        ("restart", "running"),
    ]:
        assert (
            logged_in.post(f"/api/apps/{app_id}/actions/{action}").json()["data"]["state"]
            == expected
        )
    assert logged_in.get(f"/api/apps/{app_id}/health").json()["data"]["status"] == "healthy"
    assert logged_in.get("/api/apps/missing").status_code == 404
    events = logged_in.get("/api/events/history").json()["data"]
    assert {"system.started", "app.registered", "user.logged_in", "app.health.changed"} <= {
        e["event"] for e in events
    }


def test_storage_validation_readonly(logged_in, tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    file = media / "keep.txt"
    file.write_text("never change this", encoding="utf-8")
    before = (file.read_bytes(), file.stat().st_mtime_ns, sorted(media.iterdir()))
    result = logged_in.post("/api/storage/validate", json={"path": str(media)}).json()["data"]
    assert result["exists"] and result["readable"] and result["totalBytes"] > 0
    assert result["permissionCheck"] == "advisory-no-write-probe"
    response = logged_in.post(
        "/api/storage", json={"name": "Test media", "kind": "movies", "path": str(media)}
    )
    assert response.status_code == 201
    assert logged_in.get("/api/storage").json()["data"][0]["path"] == str(media)
    assert (file.read_bytes(), file.stat().st_mtime_ns, sorted(media.iterdir())) == before
    assert (
        logged_in.post("/api/storage/validate", json={"path": str(tmp_path / "missing")}).json()[
            "data"
        ]["exists"]
        is False
    )
    assert (
        logged_in.post("/api/storage/validate", json={"path": str(tmp_path.parent)}).status_code
        == 403
    )
    assert logged_in.post("/api/storage/validate", json={"path": "relative"}).status_code == 400


def test_storage_permission_denied(logged_in, tmp_path, monkeypatch):
    import mediahub.storage

    monkeypatch.setattr(mediahub.storage.os, "access", lambda *args: False)
    response = logged_in.post(
        "/api/storage", json={"name": "Denied", "kind": "custom", "path": str(tmp_path)}
    )
    assert response.status_code == 400


def test_settings_persist_and_reject_secrets(logged_in):
    values = {"display_name": "My control room", "theme": "dark", "activity_page_size": 20}
    assert logged_in.put("/api/settings", json=values).status_code == 200
    saved = logged_in.get("/api/settings").json()["data"]
    assert saved == {
        **values,
        "advanced_mode": False,
        "release_repository": None,
        "update_check_interval_hours": 24,
        "visible_navigation": [
            "/",
            "/apps",
            "/storage",
            "/updates",
            "/backups",
            "/settings",
        ],
        "dashboard_sections": ["storage", "apps", "system"],
    }
    assert logged_in.put("/api/settings", json={**values, "advanced_mode": True}).status_code == 200
    assert logged_in.get("/api/settings").json()["data"]["advanced_mode"] is True
    customized = {
        **values,
        "visible_navigation": ["/", "/storage", "/settings"],
        "dashboard_sections": ["storage"],
    }
    assert logged_in.put("/api/settings", json=customized).status_code == 200
    assert logged_in.get("/api/settings").json()["data"]["visible_navigation"] == [
        "/",
        "/storage",
        "/settings",
    ]
    assert (
        logged_in.put(
            "/api/settings",
            json={**customized, "visible_navigation": ["/", "/storage"]},
        ).status_code
        == 422
    )
    assert (
        logged_in.put("/api/settings", json={**values, "password": "never returned"}).status_code
        == 422
    )


def test_central_errors_hide_internals(logged_in, monkeypatch):
    def failure():
        raise RuntimeError("secret internal path or token")

    monkeypatch.setattr(logged_in.app.state.services.apps, "list", failure)
    response = logged_in.get("/api/apps")
    assert response.status_code == 500
    assert "secret internal" not in response.text
    assert response.json()["error"]["code"] == "internal_error"


def test_event_bus_bounded_and_encoded(client):
    bus = client.app.state.services.events
    queue = asyncio.Queue(maxsize=1)
    bus.subscribers.add(queue)
    bus.publish("system.status", {"sample": 1})
    bus.publish("system.status", {"sample": 2})
    assert queue.qsize() == 1
    event = queue.get_nowait()
    assert event["data"]["sample"] == 2
    assert "event: system.status\n" in bus.encode(event)
    bus.subscribers.remove(queue)


def test_api_unknown_is_not_spa(logged_in):
    assert logged_in.get("/api/unknown").status_code == 404
    assert logged_in.get("/api/unknown").json()["error"]


def test_docker_readonly_filters_and_redacts():
    import sys

    sys.path.insert(0, str(ROOT))
    from agent.docker_readonly import DockerReader, DockerReadError

    class Transport:
        async def get(self, path):
            if path.startswith("/containers/json"):
                return [
                    {
                        "Id": "a" * 64,
                        "State": "running",
                        "Image": "mock",
                        "Labels": {"org.mediahub.instance": "test"},
                    },
                    {"Id": "b" * 64, "State": "running", "Image": "production", "Labels": {}},
                ]
            return {
                "Id": "a" * 64,
                "Image": "digest",
                "Config": {"Env": ["PASSWORD=hidden"], "Labels": {"org.mediahub.instance": "test"}},
                "State": {"Status": "running", "Error": "hidden"},
            }

    reader = DockerReader(Transport(), "test")
    assert len(asyncio.run(reader.list_containers())) == 1
    assert "hidden" not in json.dumps(asyncio.run(reader.inspect("a" * 64)))
    with pytest.raises(DockerReadError):
        asyncio.run(reader.inspect("../../anything"))
