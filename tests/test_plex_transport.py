import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.agent_client import AgentClient
from mediahub.container_apps_api import target as container_target
from mediahub.errors import DomainError
from mediahub.plex_api import target
from mediahub.update_queue import UpdateQueue


def client_for(url, embedded):
    return AgentClient(SimpleNamespace(agent_url=url), local_app=object() if embedded else None)


@pytest.mark.parametrize("target_function", [target, container_target])
@pytest.mark.parametrize("url,embedded,trusted", [
    ("http://127.0.0.1:18767", True, True),
    ("https://192.0.2.10:18767", False, True),
    ("http://192.0.2.10:18767", False, False),
    ("http://127.0.0.1:18767", False, False),
])
def test_plex_target_accepts_embedded_or_https_only(url, embedded, trusted, target_function):
    client = client_for(url, embedded)
    request = SimpleNamespace(
        url=SimpleNamespace(scheme="https"),
        app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(
            hosts=SimpleNamespace(client=lambda host: client)
        ))),
    )
    assert client.trusted_transport is trusted
    if trusted:
        assert target_function(request, "local") is client
    else:
        with pytest.raises(DomainError, match="trusted HTTPS Agent"):
            target_function(request, "local")
    request.url.scheme = "http"
    with pytest.raises(DomainError, match="Use HTTPS"):
        target_function(request, "local")


@pytest.mark.parametrize("embedded", [True, False])
def test_plex_update_queue_applies_same_transport_boundary(embedded):
    client = client_for("http://127.0.0.1:18767", embedded)
    client.request = AsyncMock(return_value={"state": "starting"})
    adapter = SimpleNamespace(host_id="local", client_factory=lambda host: client)
    queue = UpdateQueue(SimpleNamespace(apps=SimpleNamespace(adapter=lambda identifier: adapter)))
    if embedded:
        assert asyncio.run(queue.launch({"kind": "plex", "id": "plex"}, {})) == {"state": "starting"}
        client.request.assert_awaited_once_with("POST", "/v1/plex/update")
    else:
        with pytest.raises(DomainError, match="trusted HTTPS Agent"):
            asyncio.run(queue.launch({"kind": "plex", "id": "plex"}, {}))
        client.request.assert_not_awaited()


def test_embedded_install_plan_passes_real_agent_https_guard(tmp_path):
    from agent.main import AgentConfig, create_agent
    from agent.plex_install import PlexInstallPolicy

    token = "x" * 48
    token_file = tmp_path / "token"
    token_file.write_text(token)
    policy_file = tmp_path / "plex-install.json"
    policy = PlexInstallPolicy(
        hostId="local", bindAddress="192.0.2.10",
        image="lscr.io/linuxserver/plex@sha256:" + "a" * 64,
        initImage="sha256:" + "b" * 64,
        hostMountSnapshot=str(tmp_path / "snapshot.json"),
        storage={kind: {"label": kind, "kind": kind, "path": str(tmp_path / kind)}
                 for kind in ("movies", "tv", "appdata")},
        requiredFilesystemUuids={}, requiredMounts={str(tmp_path): "mediahub-main"},
        storageMarkers={str(tmp_path / "marker"): "verified-media"},
    )
    policy_file.write_text(policy.model_dump_json())
    app = create_agent(AgentConfig(
        state_dir=tmp_path, token_file=token_file, dev_mode=True,
        plex_install_policy_file=policy_file, _env_file=None,
    ))
    client = AgentClient(SimpleNamespace(agent_url="http://127.0.0.1:18767"),
                         token=token, local_app=app)
    result = asyncio.run(client.request("POST", "/v1/plex/install-plan", {
        "moviesStorageIds": ["movies"], "tvStorageIds": ["tv"],
        "appdataStorageId": "appdata",
    }))
    assert result["mediaReadOnly"] is True
    assert len(result["planDigest"]) == 64
