from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.agent_client import AgentClient
from mediahub.errors import DomainError
from mediahub.plex_api import target
from mediahub.update_queue import UpdateQueue


def client_for(url, embedded):
    return AgentClient(SimpleNamespace(agent_url=url), local_app=object() if embedded else None)


@pytest.mark.parametrize("url,embedded,trusted", [
    ("http://127.0.0.1:18767", True, True),
    ("https://192.0.2.10:18767", False, True),
    ("http://192.0.2.10:18767", False, False),
    ("http://127.0.0.1:18767", False, False),
])
def test_plex_target_accepts_embedded_or_https_only(url, embedded, trusted):
    client = client_for(url, embedded)
    request = SimpleNamespace(
        url=SimpleNamespace(scheme="https"),
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(
            hosts=SimpleNamespace(client=lambda host: client)
        ))),
    )
    assert client.trusted_transport is trusted
    if trusted:
        assert target(request) is client
    else:
        with pytest.raises(DomainError, match="trusted HTTPS Agent"):
            target(request)
    request.url.scheme = "http"
    with pytest.raises(DomainError, match="Use HTTPS"):
        target(request)


@pytest.mark.parametrize("embedded", [True, False])
def test_plex_update_queue_applies_same_transport_boundary(embedded):
    client = client_for("http://127.0.0.1:18767", embedded)
    client.request = AsyncMock(return_value={"state": "starting"})
    adapter = SimpleNamespace(host_id="local", client_factory=lambda host: client)
    queue = UpdateQueue(SimpleNamespace(apps=SimpleNamespace(adapter=lambda identifier: adapter)))
    import asyncio
    if embedded:
        assert asyncio.run(queue.launch({"kind": "plex", "id": "plex"}, {})) == {"state": "starting"}
        client.request.assert_awaited_once_with("POST", "/v1/plex/update")
    else:
        with pytest.raises(DomainError, match="trusted HTTPS Agent"):
            asyncio.run(queue.launch({"kind": "plex", "id": "plex"}, {}))
        client.request.assert_not_awaited()
