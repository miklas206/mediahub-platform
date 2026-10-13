import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from mediahub.apps.seedbox_credentials import QBitInitialSettings
from test_seedbox_plan import spec

from agent.install_files import read_json, save_json
from agent.seedbox_install_driver import ProductionInstallDriver


def test_new_install_pulls_both_publishers_before_storage_probe(tmp_path, monkeypatch):
    item = driver(tmp_path)
    item.runtime.binding = lambda: (SimpleNamespace(workRoot=str(tmp_path)), spec(provider="protonvpn"))
    item.runtime.socket = "test-socket"
    item.runtime.storage_guard = AsyncMock()
    item.runtime.device_guard = AsyncMock()
    item.runtime.container.side_effect = httpx.HTTPStatusError(
        "missing", request=httpx.Request("GET", "http://docker/container"),
        response=httpx.Response(404),
    )
    item.runtime.request.return_value = httpx.Response(200, json={"MemTotal": 8 * 1024**3})
    item.review = lambda: {"digest": "reviewed"}
    item.credentials = lambda: SimpleNamespace(vpnConfig="synthetic-wireguard")
    monkeypatch.setattr("agent.seedbox_install_driver.verify_ram_directory", lambda _: None)
    monkeypatch.setattr("agent.seedbox_install_driver.VPNProfileRegistry", lambda: SimpleNamespace(
        get=lambda _: SimpleNamespace(validate=lambda _: None),
    ))
    pulled = []

    async def pull(socket, repository):
        pulled.append(repository)
        return {"Id": "sha256:" + "a" * 64, "RepoDigests": [repository + "@sha256:" + "c" * 64]}

    async def probe(**kwargs):
        assert pulled == ["qmcgaw/gluetun", "lscr.io/linuxserver/qbittorrent"]
        assert item.runtime.resolved_images["vpnImage"] == "qmcgaw/gluetun@sha256:" + "c" * 64

    item.runtime.write_probe = probe
    monkeypatch.setattr("agent.seedbox_install_driver.pull_latest", pull)
    # Avoid binding a real host port in this synthetic preflight.
    monkeypatch.setattr("agent.seedbox_install_driver.socket", SimpleNamespace(
        socket=lambda *args: SimpleNamespaceContext(), AF_INET=2, SOCK_STREAM=1,
    ))
    assert asyncio.run(item.preflight("reviewed"))["state"] == "passed"


class SimpleNamespaceContext:
    def __enter__(self):
        return SimpleNamespace(bind=lambda _: None)

    def __exit__(self, *args):
        return False


def driver(tmp_path):
    runtime = SimpleNamespace(
        binding=lambda: (SimpleNamespace(workRoot=str(tmp_path)), spec()),
        container=AsyncMock(),
        request=AsyncMock(),
    )
    return ProductionInstallDriver(runtime, QBitInitialSettings(), lambda: None, AsyncMock())


def test_rollback_never_removes_foreign_transaction(tmp_path):
    async def run():
        item = driver(tmp_path)
        item.transaction_id = "new"
        save_json(
            item.journal,
            {"installationId": spec().installationId, "transactionId": "old", "status": "healthy"},
        )
        with pytest.raises(ValueError, match="Ownership"):
            await item.rollback_owned_runtime()
        item.runtime.container.assert_not_awaited()
        item.runtime.request.assert_not_awaited()

    asyncio.run(run())


def test_rollback_checks_labels_before_stop_and_preserves_all_files(tmp_path, monkeypatch):
    async def run():
        item = driver(tmp_path)
        item.transaction_id = "owned"
        save_json(
            item.journal,
            {
                "installationId": spec().installationId,
                "transactionId": "owned",
                "status": "installing",
            },
        )
        item.runtime.container.return_value = {
            "Id": "foreign",
            "State": {"Running": True},
            "Config": {"Labels": {"mediahub.install.transaction": "foreign"}},
        }
        with pytest.raises(ValueError, match="not created"):
            await item.rollback_owned_runtime()
        item.runtime.request.assert_not_awaited()
        preserved = tmp_path / "qbit-state"
        preserved.write_bytes(b"test-state")
        item.runtime.container.side_effect = lambda service: {
            "Id": service,
            "State": {"Running": True},
            "Config": {"Labels": {"mediahub.install.transaction": "owned"}},
        }
        monkeypatch.setattr(
            "agent.seedbox_install_driver.RuntimeSecrets",
            lambda _: SimpleNamespace(clear=lambda: None),
        )
        await item.rollback_owned_runtime()
        calls = item.runtime.request.await_args_list
        assert [(call.args[0], call.args[1]) for call in calls] == [
            ("POST", "/containers/torrent/stop"),
            ("DELETE", "/containers/torrent"),
            ("POST", "/containers/vpn/stop"),
            ("DELETE", "/containers/vpn"),
        ]
        assert all(
            call.kwargs["params"]["v"] == "false" for call in calls if call.args[0] == "DELETE"
        )
        assert preserved.read_bytes() == b"test-state"
        assert read_json(item.journal)["status"] == "rolled_back"

    asyncio.run(run())


def test_rollback_handles_missing_owned_container(tmp_path, monkeypatch):
    async def run():
        item = driver(tmp_path)
        item.transaction_id = "owned"
        save_json(item.journal, {"installationId": spec().installationId, "transactionId": "owned"})
        response = httpx.Response(
            404, request=httpx.Request("GET", "http://docker/containers/test")
        )
        item.runtime.container.side_effect = httpx.HTTPStatusError(
            "missing", request=response.request, response=response
        )
        monkeypatch.setattr(
            "agent.seedbox_install_driver.RuntimeSecrets",
            lambda _: SimpleNamespace(clear=lambda: None),
        )
        await item.rollback_owned_runtime()
        item.runtime.request.assert_not_awaited()
        assert read_json(item.journal)["status"] == "rolled_back"

    asyncio.run(run())


def test_failure_before_claim_has_no_cleanup_authority(tmp_path):
    async def run():
        item = driver(tmp_path)
        await item.rollback_owned_runtime()
        item.runtime.container.assert_not_awaited()

    asyncio.run(run())
