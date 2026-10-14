import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from xml.etree.ElementTree import Element

import pytest
from mediahub.apps.plex import PlexAccountClaim
from mediahub.errors import DomainError

from agent.install_files import save_json
from agent.plex_account import queue, run

TOKEN = "claim-synthetic-private-token"


def runtime(tmp_path):
    policy = SimpleNamespace(
        installationId="plex-main", container="mediahub-plex-main", vpnEnabled=False
    )
    save_json(tmp_path / "plex-plan.json", {"name": policy.container})
    return SimpleNamespace(
        control=SimpleNamespace(
            lock=asyncio.Lock(),
            policy=lambda: policy,
            inspect=AsyncMock(return_value={"State": {"Running": True}}),
            storage_verified=AsyncMock(return_value=True),
            plex_get=AsyncMock(
                side_effect=[
                    Element("MediaContainer", claimed="0"),
                    Element("MediaContainer", claimed="1"),
                ]
            ),
        ),
        policy=lambda: SimpleNamespace(uid=1000, gid=1000),
        state_dir=tmp_path,
        stop=AsyncMock(),
        helper=AsyncMock(return_value="owned-helper"),
        archive_write=AsyncMock(),
        request=AsyncMock(),
        checkpoint=AsyncMock(),
        remove_helper=AsyncMock(),
        vault=SimpleNamespace(get=Mock(return_value=b"<Preferences/>")),
        shared_vpn=SimpleNamespace(ready=AsyncMock(return_value=True)),
        account_operation={"state": "idle"},
        account_task=None,
        install_task=None,
        update_task=None,
    )


def test_claim_preserves_identity_and_clears_ram_token_after_verification(tmp_path):
    r = runtime(tmp_path)
    asyncio.run(run(r, PlexAccountClaim(claimToken=TOKEN)))
    assert r.account_operation["state"] == "succeeded"
    assert TOKEN not in str(r.account_operation)
    assert r.archive_write.await_args_list[0].args[1][".claim"] == TOKEN.encode()
    assert r.archive_write.await_args_list[-1].args[1] == {".claim": b""}
    r.checkpoint.assert_awaited_once()
    r.remove_helper.assert_awaited_once_with("owned-helper")
    r.request.assert_awaited_once_with("POST", "/containers/mediahub-plex-main/start")


def test_invalid_or_expired_claim_can_retry_without_resetting_server(tmp_path, monkeypatch):
    r = runtime(tmp_path)
    r.control.plex_get.side_effect = None
    r.control.plex_get.return_value = Element("MediaContainer", claimed="0")
    monkeypatch.setattr("agent.plex_account.asyncio.sleep", AsyncMock())
    asyncio.run(run(r, PlexAccountClaim(claimToken=TOKEN)))
    assert r.account_operation["state"] == "failed"
    assert TOKEN not in str(r.account_operation)
    assert r.archive_write.await_args_list[-1].args[1] == {".claim": b""}
    r.remove_helper.assert_awaited_once()
    r.control.plex_get.side_effect = [
        Element("MediaContainer", claimed="0"),
        Element("MediaContainer", claimed="1"),
    ]
    asyncio.run(run(r, PlexAccountClaim(claimToken=TOKEN)))
    assert r.account_operation["state"] == "succeeded"


@pytest.mark.parametrize("guard", ["storage", "vpn", "claimed"])
def test_claim_does_not_restart_unsafe_or_already_claimed_server(tmp_path, guard):
    r = runtime(tmp_path)
    if guard == "storage":
        r.control.storage_verified.return_value = False
    if guard == "vpn":
        r.shared_vpn.ready.return_value = False
    if guard == "claimed":
        r.control.plex_get.side_effect = [Element("MediaContainer", claimed="1")]
    asyncio.run(run(r, PlexAccountClaim(claimToken=TOKEN)))
    r.stop.assert_not_awaited()
    r.archive_write.assert_not_awaited()


def test_failed_start_still_clears_claim_file(tmp_path):
    r = runtime(tmp_path)
    r.request.side_effect = DomainError("failed", "Plex start failed", 409)
    asyncio.run(run(r, PlexAccountClaim(claimToken=TOKEN)))
    assert r.account_operation["state"] == "failed"
    assert r.archive_write.await_args_list[-1].args[1] == {".claim": b""}
    r.remove_helper.assert_awaited_once()


def test_duplicate_account_claim_is_not_admitted_after_inspection_yields(tmp_path):
    async def scenario():
        r = runtime(tmp_path)
        release = asyncio.Event()

        async def inspect(_):
            await release.wait()
            return {"State": {"Running": True}}

        r.control.inspect.side_effect = inspect
        tasks = [
            asyncio.create_task(queue(r, PlexAccountClaim(claimToken=TOKEN))) for _ in range(2)
        ]
        await asyncio.sleep(0)
        release.set()
        result = await asyncio.gather(*tasks, return_exceptions=True)
        assert sum(isinstance(value, dict) for value in result) == 1
        assert sum(isinstance(value, DomainError) for value in result) == 1
        await r.account_task

    asyncio.run(scenario())


def test_account_endpoint_requires_https_csrf_and_never_echoes_token(logged_in, monkeypatch):
    from mediahub.db import InstalledApp, Setting

    svc = logged_in.app.state.services
    with svc.sessions.begin() as db:
        db.add(
            InstalledApp(
                package_id="org.mediahub.plex",
                name="Plex",
                version="1",
                state="running",
                is_mock=False,
            )
        )
        db.add(
            Setting(
                key="plex_installation", value={"hostId": "local", "installationId": "plex-main"}
            )
        )
    agent = SimpleNamespace(
        trusted_transport=True,
        request=AsyncMock(
            return_value={"state": "accepted", "message": "Linking Plex to your account"}
        ),
    )
    monkeypatch.setattr(svc.hosts, "client", lambda host: agent)
    path = "/api/v1/plex/account"
    assert logged_in.post(path, json={"claimToken": TOKEN}).status_code == 403
    response = logged_in.post("https://127.0.0.1:18765" + path, json={"claimToken": TOKEN})
    assert response.status_code == 202, response.text
    assert TOKEN not in response.text
    agent.request.assert_awaited_once_with("POST", "/v1/plex/account", {"claimToken": TOKEN})
    logged_in.headers.pop("X-MediaHub-CSRF")
    assert (
        logged_in.post("https://127.0.0.1:18765" + path, json={"claimToken": TOKEN}).status_code
        == 403
    )
