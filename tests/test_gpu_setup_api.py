import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from test_gpu_installation import INTEL, NVIDIA, gpu_runtime

from agent.gpu_setup import GPUSetup, encode_arguments


@pytest.mark.parametrize("grant", [INTEL, NVIDIA])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_real_encoder_scoped_devices_and_cleanup(tmp_path, monkeypatch, grant, exit_code):
    apps, _ = gpu_runtime(tmp_path, monkeypatch, grant)
    monkeypatch.setattr("agent.gpu_setup.available", lambda _: True)
    image = "sha256:" + "a" * 64
    monkeypatch.setattr("agent.gpu_setup.pull_latest", AsyncMock(return_value={"Id": image}))
    gpu = GPUSetup(apps)
    gpu.logs = AsyncMock(return_value=["FFmpeg hardware encoder output"])
    rows, events = {}, []

    async def request(method, path, body=None, **kwargs):
        events.append((method, path))
        if path == "/info":
            return {"Runtimes": {"nvidia": {}}}
        if path.startswith("/containers/create"):
            name = path.split("name=")[1]
            rows[name] = {
                "Config": {"Labels": body["Labels"]},
                "Image": image,
                "HostConfig": copy.deepcopy(body["HostConfig"]),
                "Mounts": [],
            }
            assert body["Cmd"] == encode_arguments(gpu.grant(grant["id"]))
            assert body["Entrypoint"] == ["/usr/lib/jellyfin-ffmpeg/ffmpeg"]
            assert body["HostConfig"]["NetworkMode"] == "none"
            assert body["HostConfig"]["ReadonlyRootfs"]
            assert body["HostConfig"]["Mounts"] == []
            assert body["HostConfig"]["GroupAdd"] == ["104"]
            assert {d["PathOnHost"] for d in body["HostConfig"]["Devices"]} == set(grant["devices"])
            return {"Id": name}
        name = path.split("/")[2].split("?")[0]
        if method == "GET":
            return rows.get(name)
        if "/wait?" in path:
            return {"StatusCode": exit_code}
        if method == "DELETE":
            assert "v=false" in path
            assert gpu.report["verified"] is False
            del rows[name]
        return {}

    apps.request = request

    async def scenario():
        await gpu.start(grant["id"])
        await gpu.task

    asyncio.run(scenario())
    assert rows == {}
    assert gpu.report["verified"] is (exit_code == 0)
    assert gpu.report["state"] == ("succeeded" if exit_code == 0 else "failed")
    if exit_code:
        assert "GPU encoding failed" in gpu.report["message"]
    assert events[-1][0] == "DELETE"


def test_unapproved_gpu_and_busy_test_rejected(tmp_path, monkeypatch):
    apps, _ = gpu_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr("agent.gpu_setup.available", lambda _: True)
    gpu = GPUSetup(apps)

    async def scenario():
        with pytest.raises(DomainError, match="Choose a GPU"):
            await gpu.start("unknown")
        gpu.task = asyncio.create_task(asyncio.Event().wait())
        with pytest.raises(DomainError, match="already running"):
            await gpu.start(NVIDIA["id"])
        await gpu.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["ownership", "revoked", "cleanup", "cancel"])
def test_failure_never_verified_and_cleanup_respects_ownership(tmp_path, monkeypatch, failure):
    apps, _ = gpu_runtime(tmp_path, monkeypatch, INTEL)
    approved = True
    monkeypatch.setattr("agent.gpu_setup.available", lambda _: approved)
    image = "sha256:" + "a" * 64
    monkeypatch.setattr("agent.gpu_setup.pull_latest", AsyncMock(return_value={"Id": image}))
    gpu = GPUSetup(apps)
    gpu.logs = AsyncMock(return_value=[])
    row = None
    removed = False
    waiting = asyncio.Event()

    async def request(method, path, body=None, **kwargs):
        nonlocal row, removed, approved
        if path.startswith("/containers/create"):
            row = {
                "Config": {"Labels": body["Labels"]},
                "Image": image,
                "HostConfig": copy.deepcopy(body["HostConfig"]),
                "Mounts": [],
            }
            if failure == "ownership":
                row["Config"]["Labels"] = {"org.mediahub.gpu.test": "foreign"}
            return {}
        if method == "GET":
            return row
        if "/wait?" in path:
            waiting.set()
            if failure == "cancel":
                await asyncio.Event().wait()
            if failure == "revoked":
                approved = False
            return {"StatusCode": 0}
        if method == "DELETE":
            if failure == "cleanup":
                raise DomainError("runtime_failed", "Docker unavailable", 503)
            removed = True
        return {}

    apps.request = request

    async def scenario():
        await gpu.start(INTEL["id"])
        if failure == "cancel":
            await waiting.wait()
            await gpu.close()
        else:
            await gpu.task

    asyncio.run(scenario())
    assert gpu.report["state"] == "failed"
    assert gpu.report["verified"] is False
    assert removed is (failure in {"revoked", "cancel"})


def test_core_gpu_routes_require_auth_https_and_csrf(client, logged_in):
    assert client.get("/api/v1/gpu-setup").status_code == 403
    assert logged_in.get("/api/v1/gpu-setup").status_code == 403
    response = logged_in.post(
        "/api/v1/gpu-setup/test", json={"gpuId": INTEL["id"]}, headers={"X-MediaHub-CSRF": "wrong"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_rejected"


def test_core_gpu_forwards_only_approved_contract(logged_in):
    from mediahub.db import InstallationState
    from sqlalchemy import select

    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.scalar(select(InstallationState)).setup_completed = True
    agent = SimpleNamespace(
        trusted_transport=True, request=AsyncMock(return_value={"state": "running"})
    )
    svc.hosts.client = lambda host: agent
    response = logged_in.post(
        "https://127.0.0.1:18765/api/v1/gpu-setup/test",
        json={"hostId": "local", "gpuId": INTEL["id"]},
    )
    assert response.status_code == 202
    agent.request.assert_awaited_once_with("POST", "/v1/gpu-setup/test", {"gpuId": INTEL["id"]})
    response = logged_in.post(
        "https://127.0.0.1:18765/api/v1/gpu-setup/test",
        json={"gpuId": INTEL["id"], "command": "arbitrary"},
    )
    assert response.status_code == 422
