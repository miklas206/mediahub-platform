import asyncio

import httpx
import pytest
from mediahub.apps.seedbox_credentials import SeedboxCredentials

from agent.seedbox_rotation import authenticated_client


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
