import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError
from mediahub.shared_vpn import SharedVPN


@pytest.mark.parametrize("previous", [None, "a" * 24])
def test_assignment_persists_scoped_profile_and_detaches_only_previous(logged_in, monkeypatch, previous):
    service = logged_in.app.state.services.shared_vpn
    binding = {"id": "plex", "name": "Plex", "hostId": "host"}
    client = SimpleNamespace(request=AsyncMock(return_value={"publicKey": "synthetic"}))
    monkeypatch.setattr(service, "target", lambda app: (binding, client))
    monkeypatch.setattr(service, "public", AsyncMock(return_value={"apps": []}))
    identifier = service.peer_id(binding)
    if previous:
        service.assignment(identifier, previous, write=True)
    new = "b" * 24
    calls = []
    async def vpn(method="GET", path="", body=None, **kwargs):
        calls.append((method, path, body))
        if path.endswith("/peers"):
            return dict(address="10.250.87.2/24", endpointIp="192.168.1.50", endpointPort=18805, gatewayKey="synthetic")
        return {"profileId": new if path else "a" * 24, "ready": True}
    monkeypatch.setattr(service, "vpn", vpn)
    asyncio.run(service.assign("plex", True, new))
    assert SharedVPN(service.svc).assignment(identifier) == new
    assert ("PUT", "/profiles/" + new, None) in calls
    expected = ("/profiles/" + previous if previous else "") + "/peers/" + identifier
    assert ("DELETE", expected, None) in calls
    calls.clear()
    asyncio.run(service.assign("plex", False, new))
    assert service.assignment(identifier) is None
    assert ("DELETE", "/profiles/" + new + "/peers/" + identifier, None) in calls


def test_selecting_same_legacy_profile_does_not_remove_new_peer(logged_in, monkeypatch):
    service = logged_in.app.state.services.shared_vpn
    binding = {"id": "plex", "name": "Plex", "hostId": "host"}
    monkeypatch.setattr(service, "target", lambda app: (binding, SimpleNamespace(request=AsyncMock(return_value={"publicKey": "key"}))))
    monkeypatch.setattr(service, "public", AsyncMock(return_value={}))
    machine = AsyncMock(return_value={"profileId": "a" * 24, "ready": True, "address": "10.250.87.2/24", "endpointIp": "192.168.1.50", "endpointPort": 18804, "gatewayKey": "key"})
    monkeypatch.setattr(service, "vpn", machine)
    asyncio.run(service.assign("plex", True, "a" * 24))
    assert not any(call.args[0] == "DELETE" for call in machine.await_args_list if call.args)


def test_agent_timeout_keeps_retryable_intent_without_claiming_success(logged_in, monkeypatch):
    service = logged_in.app.state.services.shared_vpn
    binding = {"id": "plex", "name": "Plex", "hostId": "host"}
    agent = AsyncMock(side_effect=[{"publicKey": "key"}, DomainError("timeout", "Agent unavailable", 503)])
    monkeypatch.setattr(service, "target", lambda app: (binding, SimpleNamespace(request=agent)))
    machine = AsyncMock(return_value={"profileId": "a" * 24, "ready": True, "address": "10.250.87.2/24", "endpointIp": "192.168.1.50", "endpointPort": 18804, "gatewayKey": "key"})
    monkeypatch.setattr(service, "vpn", machine)
    with pytest.raises(DomainError):
        asyncio.run(service.assign("plex", True, "a" * 24))
    reopened = SharedVPN(service.svc)
    assert reopened.assignment(service.peer_id(binding)) == "a" * 24
    assert reopened.assignment_pending(service.peer_id(binding))
