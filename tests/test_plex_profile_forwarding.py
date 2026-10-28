import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.plex_forwarding import PlexForwarding


def fixture():
    client = SimpleNamespace(request=AsyncMock(return_value={
        "enabled": True, "publicPort": 50186, "identityHash": hashlib.sha256(b"owned").hexdigest()}))
    binding = {"id": "plex", "hostId": "local"}
    shared = SimpleNamespace(bindings=lambda: [binding], target=lambda _: (binding, client),
        peer_id=lambda _: "owned-peer", assignment=lambda _: "plex-profile",
        assignment_pending=lambda _: False, vpn=AsyncMock(return_value={
            "enabled": True, "ready": True, "profileId": "plex-profile", "publicIp": "8.8.8.8",
            "forwardedPort": 50186, "plexPort": {"ready": True, "publicIp": "8.8.8.8", "publicPort": 50186}}))
    state = {"profileId": "web-profile", "plexPortEnabled": True}
    gateway = SimpleNamespace(svc=SimpleNamespace(shared_vpn=shared), gateway={"providerReady": False},
        state=lambda: state, vpn=AsyncMock(return_value={"profileId": "web-profile"}))
    service = PlexForwarding(gateway)
    service.probe = AsyncMock(return_value=True)
    return service, shared, client, state


def test_upgrade_migrates_inbound_to_assigned_profile_and_rechecks_port():
    service, shared, client, state = fixture()
    old = {"plexPort": {"ready": True, "publicIp": "1.1.1.1", "publicPort": 40324}}
    asyncio.run(service.apply(state, old))
    shared.vpn.assert_awaited_with("PUT", "/profiles/plex-profile/plex", {"peerId": "owned-peer"})
    client.request.assert_awaited_with("PUT", "/v1/plex/shared-remote-access", {
        "enabled": True, "publicIp": "8.8.8.8", "publicPort": 50186})
    assert state["plexPortStatus"]["publicPort"] == 50186
    assert service.public(state)["ready"]
    assert state["plexForwardingProfile"] == "plex-profile"
    state["plexPortEnabled"] = False
    asyncio.run(service.apply(state, {}))
    shared.vpn.assert_awaited_with("DELETE", "/profiles/plex-profile/plex")
    assert not state["plexPortStatus"]["ready"]


def test_pending_assignment_does_not_open_a_port():
    service, shared, _, state = fixture()
    shared.assignment_pending = lambda _: True
    with pytest.raises(DomainError):
        asyncio.run(service.apply(state, {}))
    shared.vpn.assert_not_awaited()


def test_unreachable_public_endpoint_is_never_reported_ready():
    service, _, _, state = fixture()
    service.probe.return_value = False
    asyncio.run(service.apply(state, {}))
    assert not service.public(state)["ready"]


def test_status_uses_assigned_port_without_web_gateway_readiness():
    service, _, client, state = fixture()
    asyncio.run(service.apply(state, {}))
    client.request.return_value = {"enabled": True, "ready": True}
    report = asyncio.run(service.runtime_status("local", client, {}))
    assert report["portForwarding"]["plexVerified"]
    assert report["portForwarding"]["currentPort"] == 50186


def test_fresh_dedicated_plex_does_not_require_a_default_or_web_profile(logged_in, monkeypatch):
    service = logged_in.app.state.services.vpn_gateway
    profile = "a" * 24
    monkeypatch.setattr(service.plex_forwarding, "target", AsyncMock())
    monkeypatch.setattr(service.plex_forwarding, "dedicated_profile", lambda _: profile)
    monkeypatch.setattr(service.svc.shared_vpn, "vpn", AsyncMock(return_value={
        "enabled": True, "ready": True, "profileId": profile}))
    monkeypatch.setattr(service, "check_legacy_provider", AsyncMock())
    monkeypatch.setattr(service, "schedule", lambda: None)
    logged_in.portal.call(service.configure_plex_port, True)
    assert service.state()["plexPortEnabled"]
    assert service.state()["profileId"] is None
    assert not service.state()["enabled"]
    service.svc.shared_vpn.vpn.assert_awaited_with(path="/profiles/" + profile)
