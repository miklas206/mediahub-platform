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
    control.owned_relay = AsyncMock(return_value={
        "Id": "relay", "State": {"Running": True, "Health": {"Status": "healthy"}},
    })
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
