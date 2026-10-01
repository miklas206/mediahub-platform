import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from agent.seedbox_provision import initial_qbit_config
from agent.seeding_policy import ensure_seeding_limits


def test_existing_queue_limits_removed_without_resuming_paused_or_changing_downloads():
    async def run():
        requests = []

        def handle(request):
            requests.append(request)
            if request.method == "POST":
                data = json.loads(parse_qs(request.content.decode())["json"][0])
                assert data == {"max_active_uploads": -1, "max_active_torrents": -1}
                return httpx.Response(200)
            return httpx.Response(200, json={"max_active_uploads": -1, "max_active_torrents": -1})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handle), base_url="http://test"
        ) as client:
            await ensure_seeding_limits(client, {"max_active_uploads": 2, "max_active_torrents": 2})
            assert len(requests) == 2
            await ensure_seeding_limits(
                client, {"max_active_uploads": -1, "max_active_torrents": -1}
            )
            assert len(requests) == 2

    asyncio.run(run())


def test_failed_readback_is_not_reported_as_applied():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"max_active_uploads": 2})
            ),
            base_url="http://test",
        ) as client:
            with pytest.raises(ValueError):
                await ensure_seeding_limits(client, {})

    asyncio.run(run())


def test_new_install_has_no_upload_queue_cap():
    settings = SimpleNamespace(
        incompleteDownloads=True,
        maxConnections=100,
        maxConnectionsPerTorrent=20,
        maxActiveDownloads=2,
        listenPort=45000,
    )
    config = initial_qbit_config(
        SimpleNamespace(webPort=8080),
        settings,
        SimpleNamespace(webPassword=SecretStr("test-password"), webUsername="test"),
    )
    assert "Session\\MaxActiveUploads=-1" in config
    assert "Session\\MaxActiveTorrents=-1" in config
    assert "Session\\MaxActiveDownloads=2" in config
