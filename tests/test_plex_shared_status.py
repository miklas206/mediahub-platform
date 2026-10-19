import asyncio
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.plex_forwarding import PlexForwarding


def fixture():
    endpoint = {
        "ready": True,
        "publicIp": "8.8.8.8",
        "publicPort": 48522,
        "verifiedAt": time.time(),
    }
    state = {
        "profileId": "profile-a",
        "checkedAt": time.time(),
        "plexPortEnabled": True,
        "plexPortStatus": copy.deepcopy(endpoint),
    }
    relay = {"enabled": True, "ready": True}
    provider = {"ready": True, "profileId": "profile-a", "publicIp": "8.8.8.8"}
    web = {"providerReady": True, "profileId": "profile-a", "plexPort": endpoint}
    shared = SimpleNamespace(
        target=lambda _: ({"hostId": "local", "id": "plex"}, None),
        peer_id=lambda _: "peer",
        assignment_pending=lambda _: False,
        assignment=lambda _: "profile-a",
        vpn=AsyncMock(return_value=provider),
    )
    gateway = SimpleNamespace(
        svc=SimpleNamespace(shared_vpn=shared), state=lambda: state, vpn=AsyncMock(return_value=web)
    )
    service = PlexForwarding(gateway)
    client = SimpleNamespace(request=AsyncMock(return_value=relay))
    report = {"health": "healthy", "plex": {"running": True}, "vpn": {"verified": False}}
    return service, client, report, relay, provider, web, state


def test_shared_plex_uses_fresh_verified_port_instead_of_legacy_defaults():
    service, client, report, *_ = fixture()
    actual = asyncio.run(service.runtime_status("local", client, report))
    assert actual["vpn"] == {
        "mode": "shared",
        "verified": True,
        "externalIp": "8.8.8.8",
        "lastVerified": actual["vpn"]["lastVerified"],
        "provider": "Proton",
    }
    assert actual["portForwarding"]["status"] == "healthy"
    assert actual["portForwarding"]["currentPort"] == 48522
    assert actual["portForwarding"]["plexVerified"] is True
    assert report["vpn"] == {"verified": False}  # Do not alter cached input.
    service.svc.shared_vpn.vpn.assert_awaited_once_with(path="/profiles/profile-a")


@pytest.mark.parametrize(
    "condition",
    [
        "stopped",
        "provider_down",
        "stale",
        "future",
        "different_port",
        "different_ip",
        "different_profile",
        "disabled",
        "pending",
        "different_host",
        "unverified",
    ],
)
def test_shared_status_never_reuses_stale_or_mismatched_reachability(condition):
    service, client, report, relay, provider, web, state = fixture()
    if condition == "stopped":
        relay["ready"] = False
    if condition == "provider_down":
        provider["ready"] = False
    if condition == "stale":
        state["plexPortStatus"]["verifiedAt"] -= 91
    if condition == "future":
        state["plexPortStatus"]["verifiedAt"] += 10
    if condition == "different_port":
        state["plexPortStatus"]["publicPort"] += 1
    if condition == "different_ip":
        state["plexPortStatus"]["publicIp"] = "1.1.1.1"
    if condition == "different_profile":
        web["profileId"] = "profile-b"
    if condition == "disabled":
        state["plexPortEnabled"] = False
    if condition == "pending":
        service.svc.shared_vpn.assignment_pending = lambda _: True
    if condition == "different_host":
        service.svc.shared_vpn.target = lambda _: ({"hostId": "other"}, None)
    if condition == "unverified":
        state["plexPortStatus"]["ready"] = False
    actual = asyncio.run(service.runtime_status("local", client, report))
    assert actual["portForwarding"]["plexVerified"] is False
    assert actual["health"] == "healthy"  # Plex's local health remains separately observed.


def test_dedicated_legacy_vpn_is_preserved_when_shared_vpn_is_disabled():
    service, client, report, relay, *_ = fixture()
    relay["enabled"] = False
    report["vpn"] = {"verified": True, "provider": "Legacy VPN"}
    assert asyncio.run(service.runtime_status("local", client, report)) is report
    service.gateway.vpn.assert_not_awaited()


def test_provider_failure_does_not_expose_private_errors_or_old_ready():
    service, client, report, *_ = fixture()
    service.gateway.vpn.side_effect = DomainError("unavailable", "PRIVATE_SETTING", 503)
    actual = asyncio.run(service.runtime_status("local", client, report))
    assert actual["vpn"]["verified"] is False
    assert actual["portForwarding"]["plexVerified"] is False
    assert "PRIVATE_SETTING" not in str(actual)


def test_upgrade_requires_a_new_port_probe_before_showing_ready():
    service, client, report, _, _, _, state = fixture()
    state["plexPortStatus"].pop("verifiedAt")
    actual = asyncio.run(service.runtime_status("local", client, report))
    assert actual["vpn"]["verified"] is True
    assert actual["portForwarding"]["status"] == "pending"
    assert actual["portForwarding"]["plexVerified"] is False


def test_existing_plex_registration_survives_core_restart(logged_in):
    from fastapi.testclient import TestClient
    from mediahub.db import InstalledApp, Setting
    from mediahub.main import create_app

    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add(Setting(key="plex_installation", value={"hostId": "local"}))
        db.add(
            InstalledApp(
                package_id="org.mediahub.plex",
                name="Plex",
                version="test",
                state="running",
                is_mock=False,
            )
        )
    # Reopen the existing database through the actual startup/registration path.
    with TestClient(create_app(svc.config)) as restarted:
        adapters = restarted.app.state.services.apps.adapters.values()
        plex = next(
            a
            for a in adapters
            if getattr(getattr(a, "definition", None), "package_id", None) == "org.mediahub.plex"
        )
        assert plex.status_enricher is not None


def test_provider_timeout_keeps_local_plex_status_and_clears_remote_ready():
    service, client, report, *_ = fixture()
    service.gateway.vpn.side_effect = TimeoutError()
    actual = asyncio.run(service.runtime_status("local", client, report))
    assert actual["health"] == "healthy"
    assert actual["vpn"]["verified"] is False
    assert actual["portForwarding"]["plexVerified"] is False


def test_inbound_gateway_can_use_another_profile_than_plex_outbound():
    service, client, report, _, provider, _, _ = fixture()
    provider.update(profileId="profile-b", publicIp="1.1.1.1")
    actual = asyncio.run(service.runtime_status("local", client, report))
    assert actual["vpn"]["verified"] is True
    assert actual["vpn"]["externalIp"] == "1.1.1.1"
    assert actual["portForwarding"]["plexVerified"] is True
    assert actual["portForwarding"]["publicIp"] == "8.8.8.8"
