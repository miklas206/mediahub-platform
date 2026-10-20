import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mediahub.errors import DomainError

from agent.plex_gpu import NAME, PACKAGE, PlexGPU


def fixture(tmp_path):
    media = {"Source": "/verified/media", "Destination": "/media/movies/1", "RW": False}
    row = {
        "Image": "sha256:" + "a" * 64,
        "Config": {"User": "1000:1000", "Labels": {"org.mediahub.package": PACKAGE,
                               "org.mediahub.plex.installation": "plex-main"}},
        "HostConfig": {"ReadonlyRootfs": True,
                       "PortBindings": {"8090/tcp": [{"HostIp": "192.168.1.10", "HostPort": "8090"}]}},
        "Mounts": [dict(media)],
        "State": {"Running": True, "StartedAt": "2026-01-01T00:00:00Z",
                  "Health": {"Status": "healthy"}},
    }
    policy = SimpleNamespace(installationId="plex-main", hostId="local")
    runtime = SimpleNamespace(
        state_dir=tmp_path,
        policy=lambda: SimpleNamespace(bindAddress="192.168.1.10", uid=1000, gid=1000),
        control=SimpleNamespace(policy=lambda: policy,
                                inspect=AsyncMock(return_value={"Mounts": [media]}),
                                storage_verified=AsyncMock(return_value=True)),
        request=AsyncMock(return_value=row),
    )
    service = PlexGPU(runtime)
    service.path.write_text(json.dumps({"enabled": True, "container": NAME,
        "imageId": row["Image"], "plexInstallationId": "plex-main",
        "installationId": "plex-main-gpu", "version": "0.2.0"}))
    return service, runtime, row


def test_fresh_hub_does_not_invent_an_installed_sidecar(tmp_path):
    runtime = SimpleNamespace(state_dir=tmp_path, request=AsyncMock())
    assert asyncio.run(PlexGPU(runtime).status()) == {"installed": False}
    runtime.request.assert_not_called()


def test_agent_gpu_endpoints_require_authentication_and_https(tmp_path):
    from fastapi.testclient import TestClient

    from agent.main import AgentConfig, create_agent, initialize

    config = AgentConfig(state_dir=tmp_path, token_file=tmp_path / "token", _env_file=None)
    initialize(config)
    client = TestClient(create_agent(config), base_url="https://embedded.mediahub")
    assert client.get("/v1/plex-gpu/status").status_code == 401
    client.headers["Authorization"] = "Bearer " + config.token_file.read_text().strip()
    assert client.get("/v1/plex-gpu/status").json() == {"installed": False}
    assert client.post("/v1/plex-gpu/actions/stop").status_code == 409
    assert client.post("http://embedded.mediahub/v1/plex-gpu/actions/stop").status_code == 403
    assert client.post("/v1/plex-gpu/actions/arbitrary-command").status_code == 422


@pytest.mark.parametrize("change", ["image", "owner", "writable_media", "new_media", "public_port"])
def test_controls_refuse_unowned_or_changed_runtimes(tmp_path, change):
    service, runtime, row = fixture(tmp_path)
    if change == "image":
        row["Image"] = "sha256:" + "b" * 64
    elif change == "owner":
        row["Config"]["Labels"]["org.mediahub.plex.installation"] = "other-plex"
    elif change == "writable_media":
        row["Mounts"][0]["RW"] = True
    elif change == "new_media":
        row["Mounts"].append({"Source": "/unapproved", "Destination": "/media/other", "RW": False})
    else:
        row["HostConfig"]["PortBindings"]["8090/tcp"][0]["HostIp"] = "0.0.0.0"
    with pytest.raises(DomainError):
        asyncio.run(service.action("stop"))
    assert all(call.args[0] != "POST" for call in runtime.request.call_args_list)


def test_stop_and_restart_target_only_the_gpu_container(tmp_path):
    service, runtime, _ = fixture(tmp_path)
    asyncio.run(service.action("stop"))
    runtime.request.assert_any_await("POST", f"/containers/{NAME}/stop?t=10")
    assert json.loads(service.path.read_text())["desiredRunning"] is False
    runtime.request.reset_mock()
    runtime.control.storage_verified.return_value = False
    with pytest.raises(DomainError):
        asyncio.run(service.action("restart"))
    assert all(call.args[0] != "POST" for call in runtime.request.call_args_list)


def test_status_is_observed_and_does_not_forward_private_job_records(tmp_path, monkeypatch):
    service, _, _ = fixture(tmp_path)
    payload = {"gpu": {"name": "Test NVIDIA", "encoder": "43", "memoryUsed": "512",
                       "memoryTotal": "8192", "temperature": "40"},
               "adapterInstalled": True, "active": 2,
               "jobs": [{"token": "private-test-token", "source": "/private/media"}]}
    client = httpx.AsyncClient
    monkeypatch.setattr("agent.plex_gpu.httpx.AsyncClient", lambda **kw: client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), **kw))
    report = asyncio.run(service.status())
    assert report["health"] == "healthy"
    assert report["gpu"]["encoderPercent"] == 43
    assert report["gpu"]["activeJobs"] == 2
    assert "private-test-token" not in json.dumps(report)
    assert "/private/media" not in json.dumps(report)
    payload["adapterInstalled"] = False
    assert asyncio.run(service.status())["health"] == "degraded"


def test_discovery_is_idempotent_and_preserves_existing_registration(client):
    from mediahub.apps.plex_gpu import discover
    from mediahub.db import InstalledApp, Setting
    from sqlalchemy import select

    svc = client.app.state.services
    original = svc.hosts
    report = {"installed": True, "hostId": "local", "installationId": "plex-main-gpu",
              "state": "running", "version": "0.2.0"}
    remote = SimpleNamespace(request=AsyncMock(return_value=report))
    svc.hosts = SimpleNamespace(client=lambda host: remote)
    with svc.sessions.begin() as db:
        db.add(Setting(key="plex_gpu_installation", value={"hostId": "local"}))
    try:
        asyncio.run(discover(svc))
        with svc.sessions() as db:
            first = db.scalar(select(InstalledApp).where(InstalledApp.package_id == PACKAGE)).id
        report.update(state="stopped", version="0.2.1")
        asyncio.run(discover(svc))
        with svc.sessions() as db:
            rows = list(db.scalars(select(InstalledApp).where(InstalledApp.package_id == PACKAGE)))
            assert len(rows) == 1 and rows[0].id == first
            assert rows[0].state == "stopped" and rows[0].version == "0.2.1"
    finally:
        svc.hosts = original
