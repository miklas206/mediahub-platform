import asyncio
import hashlib
import xml.etree.ElementTree as ET
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.plex_forwarding import PlexForwarding
from pydantic import ValidationError

from agent.plex_remote_access import KEYS, RemoteAccessChoice, configure


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


@pytest.fixture
def runtime(tmp_path):
    values = dict(zip(KEYS, ("0", "32400", "0")))
    original = dict(values)

    async def plex_get(policy, path, method="GET", params=None):
        if path == "/identity":
            return ET.Element("MediaContainer", machineIdentifier="owned-plex")
        if path == "/myplex/refreshReachability":
            return ET.Element("Empty")
        if method == "PUT":
            values.update(params)
        root = ET.Element("MediaContainer")
        for key, value in values.items():
            ET.SubElement(root, "Setting", id=key, value=value)
        return root

    control = SimpleNamespace(
        lock=asyncio.Lock(),
        policy=lambda: SimpleNamespace(installationId="plex-main"),
        plex_get=AsyncMock(side_effect=plex_get),
    )
    return (
        SimpleNamespace(control=control, state_dir=tmp_path, checkpoint=AsyncMock()),
        values,
        original,
    )


@run_async
async def test_port_changes_keep_original_and_restore_on_disable(runtime):
    app, values, original = runtime
    shared = SimpleNamespace(status=AsyncMock(return_value={"enabled": True, "ready": True}))
    for port in (50001, 50002):
        reply = await configure(
            app, shared, RemoteAccessChoice(enabled=True, publicPort=port, publicIp="8.8.8.8")
        )
        assert values[KEYS[1]] == str(port)
        assert reply["identityHash"] == hashlib.sha256(b"owned-plex").hexdigest()
    await configure(app, shared, RemoteAccessChoice(enabled=False))
    assert values == original
    assert not (app.state_dir / "plex-shared-remote.json").exists()


@run_async
async def test_publication_refreshes_for_new_endpoint_and_retries_failed_refresh(runtime):
    app, _, _ = runtime
    shared = SimpleNamespace(status=AsyncMock(return_value={"enabled": True, "ready": True}))
    original = app.control.plex_get.side_effect
    attempts = []

    async def plex_get(policy, path, method="GET", params=None):
        if path == "/myplex/refreshReachability":
            attempts.append(path)
            if len(attempts) == 1:
                raise DomainError("plex_api_unavailable", "Synthetic unavailable", 503)
        return await original(policy, path, method, params)

    app.control.plex_get.side_effect = plex_get
    body = RemoteAccessChoice(enabled=True, publicPort=50001, publicIp="8.8.8.8")
    with pytest.raises(DomainError):
        await configure(app, shared, body)
    await configure(app, shared, body)
    await configure(app, shared, body)
    assert len(attempts) == 2
    await configure(app, shared, body.model_copy(update={"publicIp": "1.1.1.1"}))
    assert len(attempts) == 3


@run_async
async def test_user_changes_are_preserved_and_unattached_plex_is_rejected(runtime):
    app, values, _ = runtime
    shared = SimpleNamespace(status=AsyncMock(return_value={"enabled": False, "ready": False}))
    body = RemoteAccessChoice(enabled=True, publicPort=50001, publicIp="8.8.8.8")
    with pytest.raises(DomainError):
        await configure(app, shared, body)
    app.control.plex_get.assert_not_called()
    shared.status.return_value = {"enabled": True, "ready": True}
    await configure(app, shared, body)
    values[KEYS[1]] = "55555"
    with pytest.raises(DomainError):
        await configure(app, shared, body)
    await configure(app, shared, RemoteAccessChoice(enabled=False))
    assert values[KEYS[1]] == "55555"


def test_browser_cannot_supply_lan_or_extra_target():
    with pytest.raises(ValidationError):
        RemoteAccessChoice(enabled=True, publicPort=50001, publicIp="192.168.1.1")
    with pytest.raises(ValidationError):
        RemoteAccessChoice(enabled=True, publicPort=50001, publicIp="8.8.8.8", address="10.0.0.1")


@run_async
async def test_unclaimed_plex_returns_account_setup_requirement(runtime):
    app, _, _ = runtime
    app.control.plex_get = AsyncMock(
        return_value=ET.Element("MediaContainer", machineIdentifier="owned-plex", claimed="0")
    )
    shared = SimpleNamespace(status=AsyncMock(return_value={"enabled": True, "ready": True}))
    with pytest.raises(DomainError) as error:
        await configure(
            app, shared, RemoteAccessChoice(enabled=True, publicPort=50001, publicIp="8.8.8.8")
        )
    assert error.value.code == "plex_remote_settings_unavailable"
    assert "account setup" in error.value.message
    assert app.control.plex_get.await_count == 1
    app.checkpoint.assert_not_called()


@run_async
async def test_hub_requires_distinct_port_and_public_identity():
    client = SimpleNamespace(
        request=AsyncMock(
            return_value={
                "enabled": True,
                "ready": True,
                "publicPort": 50003,
                "identityHash": "verified-hash",
            }
        )
    )
    shared = SimpleNamespace(bindings=lambda: [{"id": "plex"}], target=lambda _: (None, client))
    service = SimpleNamespace(
        shared_vpn=shared,
        cloudflare_management=SimpleNamespace(
            origin=AsyncMock(return_value="http://192.168.1.20:32400")
        ),
    )
    gateway = SimpleNamespace(svc=service, gateway={"providerReady": True})
    forwarding = PlexForwarding(gateway)
    assert await forwarding.target() == {"address": "192.168.1.20", "port": 32400}
    state = {"enabled": True, "plexPortEnabled": True}
    reply = {
        "publicPort": 50001,
        "torrentPort": 50002,
        "plexPort": {"ready": True, "publicPort": 50001, "publicIp": "8.8.8.8"},
    }
    with pytest.raises(DomainError):
        await forwarding.apply(state, reply)
    reply["plexPort"]["publicPort"] = 50003
    forwarding.probe = AsyncMock(return_value=False)
    await forwarding.apply(state, reply)
    assert not state["plexPortStatus"]["ready"]
    forwarding.probe.return_value = True
    await forwarding.apply(state, reply)
    assert state["plexPortStatus"]["ready"]
    gateway.gateway["providerReady"] = False
    assert not forwarding.public(state)["ready"]
    state["enabled"] = False
    await forwarding.apply(state, reply)
    assert state["plexPortStatus"]["ready"]
    state["plexPortEnabled"] = False
    await forwarding.apply(state, {})
    client.request.assert_awaited_with("PUT", "/v1/plex/shared-remote-access", {"enabled": False})


@run_async
async def test_hub_rejects_unapproved_plex_origin():
    client = SimpleNamespace(request=AsyncMock(return_value={"enabled": True, "ready": True}))
    svc = SimpleNamespace(
        shared_vpn=SimpleNamespace(target=lambda _: (None, client)),
        cloudflare_management=SimpleNamespace(
            origin=AsyncMock(return_value="http://8.8.8.8:32400")
        ),
    )
    with pytest.raises(DomainError):
        await PlexForwarding(SimpleNamespace(svc=svc)).target()
