import asyncio
import time

import pytest
from mediahub.apps.remote_status import RemoteStatusCache


class Client:
    def __init__(self):
        self.calls, self.fail, self.delay = 0, False, 0

    async def request(self, method, path):
        assert (method, path) == ("GET", "/v1/seedbox/status")
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ValueError("Authorization: Bearer secret")
        return {
            "observedAt": time.time(),
            "hostId": "test",
            "installationId": "test-app",
            "health": "healthy",
            "password": "secret",
            "vpn": {"privateKey": "secret"},
        }


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_cached_and_secrets_filtered():
    cache, client = RemoteStatusCache(), Client()
    first = await cache.get("test", client)
    second = await cache.get("test", client)
    assert first["health"] == "healthy" and second["cached"] and client.calls == 1
    assert "secret" not in str(first)


@pytest.mark.anyio
async def test_failure_and_timeout_never_return_previous_healthy():
    cache, client = RemoteStatusCache(ttl=0, timeout=0.01), Client()
    assert (await cache.get("test", client))["health"] == "healthy"
    client.fail = True
    failed = await cache.get("test", client)
    assert failed["health"] == "offline" and "secret" not in str(failed)
    client.fail, client.delay = False, 0.1
    assert (await cache.get("test", client))["health"] == "offline"


def test_forwarding_schema_retains_only_public_lease_fields():
    from mediahub.apps.remote_status import RuntimeStatus

    report = RuntimeStatus.model_validate(
        {
            "observedAt": time.time(),
            "hostId": "host",
            "installationId": "app",
            "health": "healthy",
            "portForwarding": {
                "status": "healthy",
                "currentPort": 54131,
                "lastRenewed": 100,
                "expiresAt": 160,
                "qBittorrentVerified": True,
                "password": "do-not-forward",
                "cookie": "do-not-forward",
            },
        }
    ).model_dump()
    assert report["portForwarding"]["currentPort"] == 54131
    assert report["portForwarding"]["qBittorrentVerified"] is True
    assert "do-not-forward" not in str(report)


def test_core_status_requires_authentication(client):
    assert client.get("/api/v1/seedbox/status").status_code == 401


def test_core_status_forwards_paired_host_only(logged_in):
    from mediahub.db import Setting

    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add(Setting(key="seedbox_installation", value={"hostId": "test"}))
    calls = []

    def factory(host):
        calls.append(host)
        return Client()

    svc.hosts.client = factory
    response = logged_in.get("/api/v1/seedbox/status")
    assert response.status_code == 200
    assert response.json()["data"]["health"] == "healthy"
    assert calls == ["test"]
    assert "secret" not in response.text
