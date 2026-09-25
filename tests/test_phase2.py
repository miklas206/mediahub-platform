import asyncio
import json
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from mediahub.config import Config
from mediahub.db import AppConfiguration, User, connect, migrate
from mediahub.errors import DomainError
from mediahub.main import create_app
from mediahub.path_policy import DirectoryPolicy
from mediahub.setup import Draft
from sqlalchemy import select, text

from agent.discovery import discovery_report
from agent.fixtures import containers
from agent.main import AgentConfig, AgentRuntime, create_agent, initialize


class LocalAgent:
    """In-process agent contract fixture. Only the pytest temporary root is writable."""

    def __init__(self, root):
        self.policy = DirectoryPolicy([root], True)
        self.calls = []
        self.available = True

    async def status(self):
        return {
            "connected": True,
            "version": "test",
            "docker": {"available": self.available},
            "fixtureMode": True,
        }

    async def request(self, method, path, payload=None):
        self.calls.append((method, path))
        if path == "/v1/discovery":
            return discovery_report(containers(), True)
        if path == "/v1/directories/inspect":
            return self.policy.inspect(payload["path"])
        if path == "/v1/directories/create":
            return self.policy.create(payload["path"], payload["confirmed_path"])
        if path.startswith("/v1/files"):
            query = parse_qs(urlsplit(path).query)
            return self.policy.list_entries(query["path"][0])
        if path.startswith("/v1/directories"):
            query = parse_qs(urlsplit(path).query)
            return self.policy.browse(query.get("path", [None])[0])
        raise DomainError("unexpected_agent_call", "Unexpected agent operation")

    async def upload(self, path, filename, content, expected_size=None):
        self.calls.append(("PUT", "/v1/files/upload"))
        return await self.policy.upload(path, filename, content, expected_size)


@pytest.fixture
def setup_client(tmp_path):
    config = Config(data_dir=tmp_path / "core", _env_file=None)
    with TestClient(create_app(config), base_url="http://127.0.0.1:18765") as client:
        root = tmp_path / "storage"
        root.mkdir()
        agent = LocalAgent(root)
        svc = client.app.state.services
        svc.agent = agent
        svc.catalog.agent = agent
        svc.imports.agent = agent
        client.storage_root = root
        yield client


def bootstrap(client):
    token = (client.app.state.services.config.data_dir / "bootstrap.token").read_text()
    response = client.post(
        "/api/v1/setup/administrator",
        json={"username": "owner", "password": secrets.token_urlsafe(24), "token": token},
    )
    assert response.status_code == 200, response.text
    client.headers["X-MediaHub-CSRF"] = response.json()["data"]["csrf"]
    return response


def save(client, draft):
    state = client.get("/api/v1/setup/draft").json()["data"]
    response = client.put(
        "/api/v1/setup/draft", json={"revision": state["revision"], "draft": draft}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_fresh_setup_and_default_catalog_no_mock(setup_client):
    assert setup_client.get("/api/v1/setup/status").json()["data"]["setup_required"]
    assert setup_client.get("/api/v1/setup/draft").status_code == 401
    assert setup_client.get("/api/v1/setup/public-checks").status_code == 200
    bootstrap(setup_client)
    apps = setup_client.get("/api/v1/apps").json()["data"]
    assert apps == []
    catalog = setup_client.get("/api/v1/catalog").json()["data"]
    assert {a["name"] for a in catalog} == {
        "Cloudflare Tunnel",
        "FjordHub",
        "Plex",
        "Seedbox",
    }
    assert next(a for a in catalog if a["id"] == "org.mediahub.plex")["availability"] == "available"
    assert all(a["availability"] in {"coming-soon", "available"} for a in catalog)


def test_bootstrap_token_cannot_be_guessed_or_reused(setup_client):
    values = {"username": "owner", "password": secrets.token_urlsafe(24), "token": "x" * 64}
    assert setup_client.post("/api/v1/setup/administrator", json=values).status_code == 403
    bootstrap(setup_client)
    assert setup_client.post("/api/v1/setup/administrator", json=values).status_code == 409
    assert setup_client.get("/api/v1/setup/status").json()["data"][
        "setup_required"
    ]  # user alone is not setup


def test_setup_resume_revision_and_completion(setup_client):
    bootstrap(setup_client)
    root = setup_client.storage_root
    existing = root / "existing"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("untouched")
    before = marker.read_bytes(), marker.stat().st_mtime_ns
    draft = Draft(step=7).model_dump()
    draft["storage"] = [
        {
            "name": "Movies",
            "kind": "movies",
            "path": str(root / "new-movies"),
            "action": "create",
            "confirmed_path": str(root / "new-movies"),
        },
        {
            "name": "Existing",
            "kind": "downloads",
            "path": str(existing),
            "action": "existing",
            "confirmed_path": None,
        },
    ]
    state = save(setup_client, draft)
    # Browser resumption reads a persisted draft, not localStorage.
    assert setup_client.get("/api/v1/setup/draft").json()["data"]["draft"] == draft
    assert (
        setup_client.put("/api/v1/setup/draft", json={"revision": 0, "draft": draft}).status_code
        == 409
    )
    assert not (root / "new-movies").exists()
    review = setup_client.get("/api/v1/setup/review").json()["data"]
    assert review["canApply"] and review["willMigrate"] is False
    applied = setup_client.post("/api/v1/setup/apply", json={"revision": state["revision"]})
    assert applied.status_code == 200, applied.text
    assert (root / "new-movies").is_dir()
    assert (marker.read_bytes(), marker.stat().st_mtime_ns) == before
    assert not setup_client.get("/api/v1/setup/status").json()["data"]["setup_required"]
    assert len(setup_client.get("/api/v1/storage/locations").json()["data"]) == 2
    assert setup_client.post("/api/v1/setup/apply", json={"revision": state["revision"]}).json()[
        "data"
    ]["alreadyApplied"]
    assert all("container" not in path for _, path in setup_client.app.state.services.agent.calls)


def test_setup_can_complete_core_without_agent_or_storage(setup_client):
    bootstrap(setup_client)
    setup_client.app.state.services.agent.available = False
    state = save(setup_client, Draft(step=7).model_dump())
    assert (
        setup_client.get("/api/v1/setup/checks").json()["data"]["runtime"][1]["state"] == "warning"
    )
    assert (
        setup_client.post("/api/v1/setup/apply", json={"revision": state["revision"]}).status_code
        == 200
    )


def test_unconfirmed_directory_creation_is_blocked(setup_client):
    bootstrap(setup_client)
    path = str(setup_client.storage_root / "new")
    draft = Draft(step=7).model_dump()
    draft["storage"] = [
        {"name": "Bad", "kind": "movies", "path": path, "action": "create", "confirmed_path": None}
    ]
    state = save(setup_client, draft)
    assert not setup_client.get("/api/v1/setup/review").json()["data"]["canApply"]
    assert (
        setup_client.post("/api/v1/setup/apply", json={"revision": state["revision"]}).status_code
        == 400
    )
    assert not Path(path).exists()


def test_directory_browser_only_directories_and_safe_paths(tmp_path):
    policy = DirectoryPolicy([tmp_path], True)
    (tmp_path / "directory").mkdir()
    (tmp_path / "private.txt").write_text("secret")
    listing = policy.browse(str(tmp_path))
    assert [f["name"] for f in listing["folders"]] == ["directory"]
    for path in [
        str(tmp_path.parent),
        str(tmp_path.anchor),
        str(tmp_path / ".." / "escape"),
        str(tmp_path / "private.txt"),
    ]:
        with pytest.raises(DomainError):
            policy.inspect(path)
    with pytest.raises(DomainError):
        policy.create(str(tmp_path / "new"), "wrong")
    created = policy.create(str(tmp_path / "new"), str(tmp_path / "new"))
    assert created["directory"] and created["readable"]
    assert "owner" in created and "filesystem" in created
    with pytest.raises(DomainError):
        policy.create(str(tmp_path / "new"), str(tmp_path / "new"))


def test_media_file_listing_is_bounded_metadata_only(tmp_path):
    policy = DirectoryPolicy([tmp_path], True)
    (tmp_path / "Movies").mkdir()
    (tmp_path / "Movies" / "nested.mkv").write_bytes(b"nested-media")
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"sample-media")
    (tmp_path / ".mediahub-write-probe-test").write_text("internal")

    listing = policy.list_entries(str(tmp_path))
    assert [(item["name"], item["type"]) for item in listing["items"]] == [
        ("Movies", "folder"),
        ("movie.mkv", "file"),
    ]
    file_item = listing["items"][1]
    assert file_item["sizeBytes"] == len(b"sample-media")
    folder_item = listing["items"][0]
    assert folder_item["sizeBytes"] == len(b"nested-media")
    assert folder_item["sizeComplete"] is True
    assert set(file_item) == {
        "name",
        "path",
        "type",
        "sizeBytes",
        "sizeComplete",
        "modifiedAt",
    }
    assert "sample-media" not in json.dumps(listing)


def test_registered_media_location_can_be_browsed_read_only(setup_client):
    bootstrap(setup_client)
    movies = setup_client.storage_root / "movies"
    movies.mkdir()
    (movies / "Example.mkv").write_bytes(b"not-returned")
    response = setup_client.post(
        "/api/v1/storage/locations",
        json={"name": "Movies", "kind": "movies", "path": str(movies)},
    )
    assert response.status_code == 201, response.text
    identifier = response.json()["data"]["id"]

    listing = setup_client.get(f"/api/v1/storage/locations/{identifier}/files")
    assert listing.status_code == 200, listing.text
    body = listing.json()["data"]
    assert body["location"]["name"] == "Movies"
    assert body["parent"] is None
    assert body["items"][0]["name"] == "Example.mkv"
    assert "not-returned" not in listing.text

    escaped = setup_client.get(
        f"/api/v1/storage/locations/{identifier}/files",
        params={"path": str(setup_client.storage_root)},
    )
    assert escaped.status_code == 403


def test_media_upload_streams_to_approved_folder_without_overwrite(setup_client):
    bootstrap(setup_client)
    movies = setup_client.storage_root / "movies"
    movies.mkdir()
    response = setup_client.post(
        "/api/v1/storage/locations",
        json={"name": "Movies", "kind": "movies", "path": str(movies)},
    )
    identifier = response.json()["data"]["id"]

    uploaded = setup_client.post(
        f"/api/v1/storage/locations/{identifier}/files/upload",
        params={"path": str(movies), "filename": "Example.mkv"},
        content=b"streamed-media",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["data"]["sizeBytes"] == len(b"streamed-media")
    assert (movies / "Example.mkv").read_bytes() == b"streamed-media"

    duplicate = setup_client.post(
        f"/api/v1/storage/locations/{identifier}/files/upload",
        params={"path": str(movies), "filename": "Example.mkv"},
        content=b"replacement",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert duplicate.status_code == 409
    assert (movies / "Example.mkv").read_bytes() == b"streamed-media"

    escaped = setup_client.post(
        f"/api/v1/storage/locations/{identifier}/files/upload",
        params={"path": str(setup_client.storage_root), "filename": "escape.mkv"},
        content=b"blocked",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert escaped.status_code == 403
    assert not (setup_client.storage_root / "escape.mkv").exists()

    invalid_name = setup_client.post(
        f"/api/v1/storage/locations/{identifier}/files/upload",
        params={"path": str(movies), "filename": "../escape.mkv"},
        content=b"blocked",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert invalid_name.status_code == 400


def test_agent_auth_and_readonly_runtime(tmp_path):
    config = AgentConfig(
        state_dir=tmp_path,
        token_file=tmp_path / "token",
        dev_mode=True,
        fixtures=True,
        _env_file=None,
    )
    initialize(config)
    with TestClient(create_agent(config)) as client:
        assert client.get("/v1/health").status_code == 401
        client.headers["Authorization"] = "Bearer " + config.token_file.read_text()
        assert client.get("/v1/health").json()["status"] == "healthy"
        assert client.get("/v1/version").json()["protocolVersion"] == 1
        assert client.get("/v1/status").json()["docker"]["operations"] == "read-only"
        assert client.get("/v1/discovery").json()["source"] == "fixture"
        assert client.post("/v1/containers/start").status_code == 404
        response = client.post("/v1/seedbox/plan", json={"vpnConfig": "SECRET_INPUT_SENTINEL"})
        assert response.status_code == 422
        assert "SECRET_INPUT_SENTINEL" not in response.text


def test_fixtures_require_dev_mode(tmp_path):
    runtime = AgentRuntime(AgentConfig(fixtures=True, dev_mode=False, _env_file=None))
    with pytest.raises(DomainError):
        asyncio.run(runtime.discover())


def test_discovery_detection_and_secret_filtering():
    report = discovery_report(containers())
    assert {c["candidates"][0]["app"] for c in report["containers"]} == {
        "plex",
        "qbittorrent",
        "vpn",
    }
    assert all(c["candidates"][0]["confidence"] == "possible" for c in report["containers"])
    serialized = json.dumps(report)
    assert "fixture-value-must-not-leave-agent" not in serialized
    assert "fixture-key-must-not-leave-agent" not in serialized
    assert "WIREGUARD_PRIVATE_KEY" in serialized
    assert report["relationships"][0]["targetId"] == "c" * 64
    assert report["containers"][2]["protocol"] == "wireguard"


def test_discovery_and_import_plan_do_not_migrate(setup_client):
    bootstrap(setup_client)
    report = setup_client.post("/api/v1/discovery/scan").json()["data"]
    selected = [c["id"] for c in report["containers"]]
    plans = setup_client.post("/api/v1/imports/preview", json={"selected": selected}).json()["data"]
    assert len(plans) == 3 and all(p["status"] == "blocked" and not p["executable"] for p in plans)
    assert any("Port conflict" in f for p in plans for f in p["findings"])
    draft = Draft(step=7, installation_type="import", selected_imports=selected).model_dump()
    state = save(setup_client, draft)
    assert (
        setup_client.post("/api/v1/setup/apply", json={"revision": state["revision"]}).status_code
        == 200
    )
    assert all(
        plan["status"] != "imported" for plan in setup_client.get("/api/v1/imports").json()["data"]
    )


def test_dynamic_config_secret_encryption_and_plan(setup_client):
    bootstrap(setup_client)
    secret = secrets.token_urlsafe(32)
    url = "/api/v1/catalog/org.mediahub.seedbox"
    response = setup_client.put(
        url + "/configuration",
        json={"values": {"credential": secret, "protocol": "wireguard", "provider": "custom"}},
    )
    assert response.status_code == 200
    assert (
        secret not in response.text
        and response.json()["data"]["secrets"]["credential"]["configured"]
    )
    assert secret not in setup_client.get(url + "/configuration").text
    with setup_client.app.state.services.sessions() as db:
        record = db.scalar(select(AppConfiguration))
        assert secret not in json.dumps(record.encrypted_secrets)
        assert (
            setup_client.app.state.services.catalog.cipher.decrypt(
                record.encrypted_secrets["credential"].encode()
            ).decode()
            == secret
        )
    plan = setup_client.post(url + "/plan", json={"mappings": {}}).json()["data"]
    assert plan["executable"] is False and set(plan["containers"]) == {"vpn", "torrent"}
    assert secret not in json.dumps(plan)
    assert (
        setup_client.put(
            url + "/configuration", json={"values": {"protocol": "invalid"}}
        ).status_code
        == 400
    )


def test_phase1_database_upgrade_preserves_user(tmp_path):
    url = "sqlite:///" + (tmp_path / "upgrade.db").as_posix()
    migrate(url, "0001")
    engine, sessions = connect(url)
    with sessions.begin() as db:
        db.add(User(username="existing", password_hash="test-hash", role="administrator"))
    migrate(url)
    with sessions() as db:
        assert db.scalar(select(User)).username == "existing"
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
    engine.dispose()


def test_network_is_pending_not_applied(setup_client):
    bootstrap(setup_client)
    from mediahub.setup import NetworkSettings

    network = NetworkSettings(
        listen_host="0.0.0.0", port=18800, base_url="http://localhost:18800"
    ).model_dump()
    assert setup_client.put("/api/v1/network", json=network).json()["data"]["restartRequired"]
    read = setup_client.get("/api/v1/network").json()["data"]
    assert read["pending"]["port"] == 18800
    assert read["active"]["base_url"] == "http://127.0.0.1:18765"


def test_mapping_edit_never_moves_files(setup_client):
    bootstrap(setup_client)
    root = setup_client.storage_root
    (root / "one").mkdir()
    (root / "two").mkdir()
    (root / "one" / "keep.txt").write_text("keep")
    row = setup_client.post(
        "/api/v1/storage/locations",
        json={"name": "Movies", "kind": "movies", "path": str(root / "one")},
    ).json()["data"]
    response = setup_client.put(
        "/api/v1/storage/locations/" + row["id"],
        json={"name": "Movies", "kind": "movies", "path": str(root / "two")},
    )
    assert response.json()["data"]["filesMoved"] is False
    assert (root / "one" / "keep.txt").read_text() == "keep"
    assert list((root / "two").iterdir()) == []
