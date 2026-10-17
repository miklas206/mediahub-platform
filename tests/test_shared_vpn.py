import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.relay_image.runtime import firewall
from agent.shared_vpn import SharedVPN


def controller(tmp_path):
    spec = {
        "Image": "sha256:" + "a" * 64,
        "Labels": {"org.mediahub.package": "org.mediahub.jellyfin"},
        "HostConfig": {
            "NetworkMode": "mediahub-apps",
            "PortBindings": {"8096/tcp": [{"HostIp": "192.168.1.50", "HostPort": "8096"}]},
            "Mounts": [{"Source": "/media/library", "Target": "/media", "ReadOnly": True}],
        },
    }
    path = tmp_path / "container-app-jellyfin.json"
    save_json(path, {"container": spec, "name": "mediahub-jellyfin", "desiredRunning": True})
    current = {"Id": "old-app", "State": {"Running": True}, "Config": {"Labels": spec["Labels"]}}
    events = []

    async def request(method, url, body=None, missing=False):
        events.append((method, url, copy.deepcopy(body)))
        if method == "GET" and url == "/containers/mediahub-jellyfin/json":
            return copy.deepcopy(current) if current else None
        if method == "DELETE" and url.startswith("/containers/old-app"):
            current.clear()
        return {}

    apps = SimpleNamespace(
        request=request,
        locks={"jellyfin": asyncio.Lock()},
        record_path=lambda app: path,
        record=lambda app: read_json(path),
        verify=lambda row, record: None,
        prepare_storage=AsyncMock(),
    )
    control = SharedVPN(SimpleNamespace(state_dir=tmp_path, docker_socket=None), apps, None)
    private = X25519PrivateKey.generate()
    import base64

    peer = {
        "address": "10.250.87.2/24",
        "gatewayKey": base64.b64encode(private.public_key().public_bytes_raw()).decode(),
        "endpointIp": "192.168.1.50",
        "endpointPort": 18804,
    }
    return control, peer, events, path


def test_assignment_stops_before_recreate_and_preserves_mounts(tmp_path):
    control, peer, events, path = controller(tmp_path)
    control.relay = AsyncMock(return_value={"Id": "relay", "State": {"StartedAt": "generation"}})
    control.status = AsyncMock(return_value={"enabled": True})
    asyncio.run(control.configuration("jellyfin", peer, True))
    saved = read_json(path)
    assert saved["container"]["HostConfig"]["NetworkMode"] == "container:relay"
    assert saved["container"]["HostConfig"]["PortBindings"] == {}
    assert saved["container"]["HostConfig"]["Mounts"][0]["Source"] == "/media/library"
    writes = [(method, url) for method, url, body in events if method != "GET"]
    assert writes[0] == ("POST", "/containers/old-app/stop?t=30")
    assert writes[1] == ("DELETE", "/containers/old-app?v=false")
    assert writes[-1] == ("POST", "/containers/mediahub-jellyfin/start")
    assert not any("v=true" in url for _, url in writes)
    assert "privateKey" not in str(saved)


def test_failed_assignment_stays_blocked_and_retry_uses_saved_intent(tmp_path):
    control, peer, events, path = controller(tmp_path)
    control.relay = AsyncMock(
        side_effect=DomainError("unverified", "Synthetic unavailable gateway", 409)
    )
    with pytest.raises(DomainError):
        asyncio.run(control.configuration("jellyfin", peer, True))
    assert control.state("jellyfin")["enabled"] is True
    assert control.state("jellyfin")["phase"] == "blocked"
    assert not any(url.endswith("/start") for _, url, _ in events)
    control.relay = AsyncMock(return_value={"Id": "relay", "State": {"StartedAt": "generation"}})
    control.status = AsyncMock(return_value={"enabled": True})
    asyncio.run(control.configuration("jellyfin", peer, True))
    assert control.state("jellyfin")["phase"] == "ready"
    assert any(url.endswith("/start") for _, url, _ in events)


def test_unmarked_established_internet_cannot_escape_when_interface_disappears():
    # Removing WireGuard can make policy routing fall through to the physical
    # table. Established VPN flows must still be blocked there.
    rules = firewall({"mode": "client", "endpointIp": "192.168.1.50", "endpointPort": 18804})
    related = [row for row in rules if "ESTABLISHED,RELATED" in row]
    assert len(related) == 1 and "--mark" in related[0] and "51879" in related[0]
    physical = [row for row in rules if "eth0" in row and "ACCEPT" in row]
    assert len(physical) == 1 and "192.168.1.50" in physical[0] and "udp" in physical[0]


def test_namespace_restart_invalidates_app_readiness(tmp_path):
    control, peer, _, _ = controller(tmp_path)
    save_json(control.path("jellyfin"), {"enabled": True})
    row = {
        "Id": "relay",
        "State": {"Running": True, "StartedAt": "new", "Health": {"Status": "healthy"}},
    }
    control.owned_relay = AsyncMock(return_value=row)
    current = {
        "Config": {
            "Labels": {"org.mediahub.vpn.namespace": "relay", "org.mediahub.vpn.generation": "old"}
        },
        "HostConfig": {"NetworkMode": "container:relay"},
    }
    assert asyncio.run(control.ready("jellyfin", current)) is False
    current["Config"]["Labels"]["org.mediahub.vpn.generation"] = "new"
    assert asyncio.run(control.ready("jellyfin", current)) is True


def test_healthy_relay_does_not_report_missing_app_ready(tmp_path):
    control, _, _, _ = controller(tmp_path)
    save_json(control.path("jellyfin"), {"enabled": True, "phase": "blocked"})
    control.owned_relay = AsyncMock(
        return_value={
            "Id": "relay",
            "State": {"Running": True, "Health": {"Status": "healthy"}},
        }
    )
    control.request = AsyncMock(return_value=None)
    status = asyncio.run(control.status("jellyfin"))
    assert status["handshakeVerified"] is True
    assert status["ready"] is False
    assert status["message"]


def test_storage_is_prepared_before_stopping_app_and_error_is_reported(tmp_path):
    control, peer, events, _ = controller(tmp_path)
    control.apps.prepare_storage.side_effect = DomainError(
        "storage_unverified", "Storage is not verified mounted", 409
    )
    with pytest.raises(DomainError, match="Storage is not verified"):
        asyncio.run(control.configuration("jellyfin", peer, True))
    assert not any(method != "GET" for method, _, _ in events)
    assert control.state("jellyfin")["errorCode"] == "storage_unverified"


def test_shared_vpn_management_requires_login(client):
    assert client.get("/api/v1/shared-vpn").status_code == 401


def test_shared_vpn_changes_require_csrf_and_reject_extra_fields(logged_in, monkeypatch):
    service = logged_in.app.state.services.shared_vpn
    machine = AsyncMock(return_value={})
    monkeypatch.setattr(service, "vpn", machine)
    csrf = logged_in.headers.pop("X-MediaHub-CSRF")
    assert logged_in.put("/api/v1/shared-vpn/gateway", json={"enabled": False}).status_code == 403
    machine.assert_not_awaited()

    logged_in.headers["X-MediaHub-CSRF"] = csrf
    response = logged_in.put(
        "/api/v1/shared-vpn/gateway",
        json={"enabled": False, "privateKey": "synthetic-private-value"},
    )
    assert response.status_code == 422
    assert "synthetic-private-value" not in response.text
    machine.assert_not_awaited()


@pytest.mark.parametrize(
    "case", ["stopped", "running", "foreign-relay", "foreign-app", "stale", "other-consumer"]
)
def test_obsolete_cleanup_verifies_snapshot_ownership_and_preserves_data(tmp_path, case):
    control, _, _, path = controller(tmp_path)
    current = {"Id": "owned-app", "State": {"Running": case == "running"}}
    relay = {
        "Id": "owned-relay",
        "Config": {
            "Labels": {"org.mediahub.vpn.relay": "other" if case == "foreign-relay" else "jellyfin"}
        },
        "HostConfig": {"Privileged": False, "NetworkMode": "bridge"},
        "State": {"Running": True},
    }
    mutations = []
    data = tmp_path / "preserved-data"
    data.write_bytes(b"media and profile data")
    save_json(
        control.path("jellyfin"), {"enabled": True, "requestedEnabled": True, "phase": "ready"}
    )

    async def request(method, url, body=None, missing=False):
        if method == "GET":
            if url == "/containers/mediahub-jellyfin/json":
                return copy.deepcopy(current) if current else None
            if url == "/containers/mediahub-vpn-jellyfin/json":
                return copy.deepcopy(relay) if relay else None
            if url == "/containers/json?all=1":
                return (
                    [{"Id": "unrelated", "HostConfig": {"NetworkMode": "container:owned-relay"}}]
                    if case == "other-consumer"
                    else []
                )
        mutations.append((method, url))
        if method == "DELETE" and "owned-app" in url:
            current.clear()
        if method == "DELETE" and "owned-relay" in url:
            relay.clear()
        return {}

    control.request = request
    if case == "foreign-app":
        control.apps.verify = lambda *args: (_ for _ in ()).throw(
            DomainError("ownership_mismatch", "Ownership mismatch", 409)
        )

    async def run():
        if case == "foreign-relay":
            with pytest.raises(DomainError):
                await control.removal_preview("jellyfin")
            return
        preview = await control.removal_preview("jellyfin")
        if case == "stale":
            current["Id"] = "replacement"
        if case != "stopped":
            with pytest.raises(DomainError):
                await control.remove_connection("jellyfin", preview["installationId"])
            assert control.state("jellyfin")["enabled"] is True
        else:
            report = await control.remove_connection("jellyfin", preview["installationId"])
            assert report["dataPreserved"] is True
            assert not current and not relay
            assert control.state("jellyfin")["enabled"] is False
            assert control.state("jellyfin")["requestedEnabled"] is False
            assert read_json(path)["desiredRunning"] is False
            assert (await control.cleanup_removed("jellyfin"))["state"] == "succeeded"

    asyncio.run(run())
    if case != "stopped":
        assert mutations == []
    assert not any("v=true" in url or "/volumes/" in url for _, url in mutations)
    assert data.read_bytes() == b"media and profile data"


def test_uninstall_fence_prevents_reconciliation_without_recreating_app(tmp_path):
    control, _, events, path = controller(tmp_path)
    control.owned_relay = AsyncMock(return_value=None)
    save_json(
        control.path("jellyfin"), {"enabled": True, "requestedEnabled": True, "phase": "blocked"}
    )
    asyncio.run(control.remove_connection("jellyfin", "mediahub-jellyfin", fence_only=True))
    assert control.state("jellyfin")["enabled"] is False
    assert control.state("jellyfin")["requestedEnabled"] is False
    assert read_json(path)["desiredRunning"] is False
    assert not any(method != "GET" for method, _, _ in events)


@pytest.mark.parametrize(
    "state,binding,peer_matches",
    [
        ("uninstalled", False, True),
        ("running", False, True),
        ("uninstalled", True, True),
        ("uninstalled", False, False),
    ],
)
def test_core_orphan_cleanup_requires_uninstalled_app_and_exact_owned_peer(
    logged_in, monkeypatch, state, binding, peer_matches
):
    import hashlib

    from mediahub.db import InstalledApp, Setting

    svc = logged_in.app.state.services
    service = svc.shared_vpn
    identifier = hashlib.sha256(b"local:jellyfin").hexdigest()[:40]
    gateway = {
        "peers": [{"id": identifier if peer_matches else "unknown-peer", "name": "Jellyfin"}]
    }
    with svc.sessions.begin() as db:
        db.add(
            InstalledApp(
                package_id="org.mediahub.jellyfin",
                name="Jellyfin",
                state=state,
                version="unknown",
                is_mock=False,
            )
        )
        if binding:
            db.add(Setting(key="container_installation_jellyfin", value={"hostId": "local"}))
    svc.managed_apps.policy["org.mediahub.mediavpn"] = SimpleNamespace(
        managementTokenFile="configured"
    )
    service.vpn = AsyncMock(return_value=gateway)
    agent = SimpleNamespace(
        trusted_transport=True,
        request=AsyncMock(
            side_effect=[
                {"installationId": "f" * 64},
                {"state": "succeeded", "dataPreserved": True},
            ]
        ),
    )
    monkeypatch.setattr(svc.hosts, "client", lambda host: agent)

    async def run():
        if state == "uninstalled" and not binding and peer_matches:
            assert (await service.cleanup_orphan(identifier))["dataPreserved"]
            agent.request.assert_any_await(
                "POST", "/v1/shared-vpn/jellyfin/cleanup", {"confirmedInstallationId": "f" * 64}
            )
            service.vpn.assert_any_await("DELETE", "/peers/" + identifier)
        else:
            with pytest.raises(DomainError):
                await service.cleanup_orphan(identifier)
            agent.request.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("desired", [True, False])
def test_plex_recovery_uses_saved_running_intent(tmp_path, desired):
    control, peer, events, path = controller(tmp_path)
    record = read_json(path)
    record["name"] = "mediahub-plex-main"
    save_json(tmp_path / "plex-plan.json", record)
    policy = SimpleNamespace(vpnEnabled=False)
    current = {"Id": "plex-created", "State": {"Running": False}}
    from unittest.mock import Mock
    control.plex = SimpleNamespace(
        control=SimpleNamespace(lock=asyncio.Lock(), policy=lambda: policy,
                                inspect=AsyncMock(return_value=current), intent=Mock(return_value=desired)),
        start=AsyncMock(), stop=AsyncMock(),
    )
    original_request = control.request
    async def request(method, url, body=None, missing=False):
        if method == "GET" and url == "/containers/mediahub-plex-main/json":
            return current
        return await original_request(method, url, body, missing)
    control.request = request
    control.prepare = AsyncMock(return_value=record["container"])
    control.status = AsyncMock(return_value={"enabled": True})
    save_json(control.path("plex"), {"enabled": True, "requestedEnabled": True,
                                    "phase": "starting", "peer": peer, "desiredRunning": True})
    async def starting(_):
        assert control.state("plex")["phase"] == "starting"
    control.plex.start.side_effect = starting
    asyncio.run(control.configuration("plex", peer, True))
    assert control.plex.start.await_count == int(desired)
    assert control.state("plex")["phase"] == "ready"
    assert control.state("plex")["desiredRunning"] is desired


def test_plex_status_checks_installed_container_name(tmp_path):
    control, peer, events, path = controller(tmp_path)
    save_json(tmp_path / "plex-plan.json", {"name": "mediahub-plex-main"})
    save_json(control.path("plex"), {"enabled": True, "phase": "ready"})
    control.owned_relay = AsyncMock(return_value={"State":{"Running":True,"Health":{"Status":"healthy"}}})
    control.request = AsyncMock(return_value={"State":{"Running":True}})
    control.ready = AsyncMock(return_value=True)
    result = asyncio.run(control.status("plex"))
    assert result["ready"] is True
    control.request.assert_awaited_once_with("GET", "/containers/mediahub-plex-main/json", missing=True)


@pytest.mark.parametrize("age,expected", [(0, True), (89, True), (120, True), (165, True), (179, True), (180, False), (181, False), (-1, False)])
def test_relay_health_respects_wireguard_session_window(monkeypatch, age, expected):
    from agent.relay_image import runtime as relay
    monkeypatch.setattr(relay, "CONFIG", SimpleNamespace(read_text=lambda: "{}"))
    monkeypatch.setattr(relay, "validate", lambda value: {"mode": "client"})
    monkeypatch.setattr(relay.time, "time", lambda: 1000)
    monkeypatch.setattr(relay, "command", lambda *args: "synthetic-key " + str(1000 - age) if args[0] == "wg" else "")
    assert relay.health() is expected


def test_reapplying_vpn_preserves_new_mounts_environment_and_migration_labels(tmp_path):
    control, _, _, path = controller(tmp_path)
    original = read_json(path)["container"]
    save_json(control.path("jellyfin"), {"enabled": True, "original": original})
    control.relay = AsyncMock(return_value={"Id": "relay", "State": {"StartedAt": "new"}})
    updated = copy.deepcopy(original)
    updated["HostConfig"]["NetworkMode"] = "container:previous-relay"
    updated["HostConfig"]["PortBindings"] = {}
    updated["HostConfig"]["Mounts"].append(
        {"Source": "/appdata/Temp/work", "Target": "/transcode", "ReadOnly": False}
    )
    updated["Env"] = ["TMPDIR=/transcode"]
    updated["Labels"].update(
        {
            "org.mediahub.vpn.namespace": "previous-relay",
            "org.mediahub.vpn.generation": "old",
            "org.mediahub.plex.temp-migration": "nonce",
        }
    )
    result = asyncio.run(control.prepare("jellyfin", updated))
    assert result["HostConfig"]["Mounts"] == updated["HostConfig"]["Mounts"]
    assert result["Env"] == ["TMPDIR=/transcode"]
    assert result["Labels"]["org.mediahub.plex.temp-migration"] == "nonce"
    saved = control.state("jellyfin")["original"]
    assert saved["HostConfig"]["NetworkMode"] == original["HostConfig"]["NetworkMode"]
    assert saved["HostConfig"]["PortBindings"] == original["HostConfig"]["PortBindings"]
    assert "org.mediahub.vpn.namespace" not in saved["Labels"]
