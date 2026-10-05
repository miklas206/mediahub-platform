import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs

import httpx
import pytest
from mediahub.apps.seedbox_credentials import SeedboxCredentials

from agent.seedbox_rotation import authenticated_client, rotate


@pytest.mark.parametrize(
    "failure", [None, "new_login", "old_still_accepted", "old_probe_network", "forwarding"]
)
def test_client_rotation_verifies_before_persisting_and_reports_failure(
    tmp_path, monkeypatch, failure
):
    previous = SeedboxCredentials(
        vpnConfig="test-profile", webUsername="old-user", webPassword="old-test-password-123"
    )
    updated = SeedboxCredentials(
        vpnConfig="test-profile", webUsername="new-user", webPassword="new-test-password-123"
    )
    store = SimpleNamespace(load=Mock(return_value=previous), stage=Mock(), replace=Mock())
    driver = SimpleNamespace(
        binding=lambda: (SimpleNamespace(workRoot=str(tmp_path)), SimpleNamespace(webPort=18080)),
        storage_guard=AsyncMock(),
        device_guard=AsyncMock(),
        verify_vpn=AsyncMock(return_value="203.0.113.1"),
        verify_torrent=AsyncMock(),
        stop_torrent=AsyncMock(),
        forwarding=SimpleNamespace(
            renew=AsyncMock(
                return_value={"status": "failed" if failure == "forwarding" else "healthy"}
            )
        ),
    )
    control = SimpleNamespace(
        driver=driver,
        lifecycle=SimpleNamespace(state={"desiredRunning": True}, persist=Mock()),
    )
    materialize = Mock()
    monkeypatch.setattr(
        "agent.seedbox_rotation.RuntimeSecrets",
        lambda root: SimpleNamespace(materialize=materialize),
    )
    requests = []

    def respond(request):
        fields = parse_qs(request.content.decode())
        requests.append((request.url.path, fields))
        if request.url.path.endswith("setPreferences"):
            assert request.headers["cookie"] == "SID=current-session"
            assert len(requests) == 2
            assert not store.replace.called
            assert json.loads(fields["json"][0]) == {
                "web_ui_username": "new-user",
                "web_ui_password": "new-test-password-123",
            }
            return httpx.Response(200)
        assert "cookie" not in request.headers
        login = (fields["username"][0], fields["password"][0])
        if len(requests) == 1:
            assert login == ("old-user", "old-test-password-123")
            return httpx.Response(
                200, text="Ok.", headers={"set-cookie": "SID=current-session; Path=/"}
            )
        assert not store.replace.called
        if login == ("new-user", "new-test-password-123"):
            return httpx.Response(
                200,
                text="Fails." if failure == "new_login" else "Ok.",
                headers={"set-cookie": "SID=new-session; Path=/"},
            )
        assert login == ("old-user", "old-test-password-123")
        if failure == "old_probe_network":
            raise httpx.ConnectError("synthetic-network-error", request=request)
        return httpx.Response(200, text="Ok." if failure == "old_still_accepted" else "Fails.")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "agent.seedbox_rotation.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )

    async def run():
        if failure:
            with pytest.raises((ValueError, httpx.ConnectError)):
                await rotate(control, store, updated, "client")
        else:
            await rotate(control, store, updated, "client")

    asyncio.run(run())
    record = json.loads((tmp_path / "credential-rotation.json").read_text())
    assert control.lifecycle.state["desiredRunning"] is (failure is None)
    if failure:
        assert record["state"] == "ManualIntervention"
        assert (
            record["failedStep"]
            == {
                "new_login": "verify_new_client_credential",
                "old_still_accepted": "verify_previous_credential_rejected",
                "old_probe_network": "verify_previous_credential_rejected",
                "forwarding": "verify_forwarding_after_rotation",
            }[failure]
        )
        driver.stop_torrent.assert_awaited_once()
    else:
        assert record["state"] == "Healthy" and record["previousCredentialRejected"]
        driver.stop_torrent.assert_not_awaited()
    assert store.replace.call_count == (1 if failure in {None, "forwarding"} else 0)
    assert materialize.call_count == store.replace.call_count
    assert updated.webPassword.get_secret_value() not in json.dumps(record)


@pytest.mark.parametrize(
    "status,body,accepted",
    [
        (200, "Ok.", True),
        (204, "", True),
        (200, "Fails.", False),
        (403, "Forbidden", False),
        (500, "Error", False),
    ],
)
def test_current_qbit_auth_responses(monkeypatch, status, body, accepted):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    monkeypatch.setattr(
        "agent.seedbox_rotation.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    credentials = SeedboxCredentials(
        vpnConfig="test-profile", webUsername="tester", webPassword="test-only-password-123"
    )

    async def run():
        if accepted:
            client = await authenticated_client("http://127.0.0.1:18080", credentials)
            await client.aclose()
        else:
            with pytest.raises(ValueError):
                await authenticated_client("http://127.0.0.1:18080", credentials)

    asyncio.run(run())
