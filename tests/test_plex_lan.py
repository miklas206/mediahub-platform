import asyncio
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError

from agent.install_files import read_json
from agent.plex_lan import configure

CERTIFICATE = "a" * 32


@pytest.fixture
def runtime(tmp_path):
    values = {"customConnections": "https://my.example:443", "allowedNetworks": ""}

    async def plex_get(policy, path, method="GET", params=None):
        if method == "PUT" and params:
            values.update(params)
        root = ET.Element("MediaContainer")
        for key, value in values.items():
            ET.SubElement(root, "Setting", id=key, value=value)
        return root

    return SimpleNamespace(
        policy=lambda: SimpleNamespace(bindAddress="192.168.40.5"),
        preferences=AsyncMock(return_value=f'<Preferences CertificateUUID="{CERTIFICATE}"/>'.encode()),
        checkpoint=AsyncMock(), state_dir=tmp_path,
        control=SimpleNamespace(plex_get=AsyncMock(side_effect=plex_get)),
        values=values,
    )


@pytest.mark.parametrize("existing_fix", [False, True])
def test_fresh_install_and_existing_manual_fix_are_idempotent(runtime, existing_fix):
    endpoint = f"https://192-168-40-5.{CERTIFICATE}.plex.direct:32400"
    if existing_fix:
        runtime.values["customConnections"] += "," + endpoint
    policy = SimpleNamespace(installationId="plex-main")
    asyncio.run(configure(runtime, policy))
    calls = runtime.control.plex_get.await_count
    asyncio.run(configure(runtime, policy))
    assert runtime.values["customConnections"] == "https://my.example:443," + endpoint
    assert runtime.values["allowedNetworks"] == ""
    assert runtime.control.plex_get.await_count == calls + 1
    runtime.checkpoint.assert_awaited_once()


def test_address_migration_removes_only_previously_managed_url(runtime):
    policy = SimpleNamespace(installationId="plex-main")
    asyncio.run(configure(runtime, policy))
    runtime.policy = lambda: SimpleNamespace(bindAddress="10.22.3.9")
    asyncio.run(configure(runtime, policy))
    assert runtime.values["customConnections"] == (
        f"https://my.example:443,https://10-22-3-9.{CERTIFICATE}.plex.direct:32400"
    )


def test_certificate_not_ready_is_retryable_without_insecure_fallback(runtime):
    runtime.preferences.return_value = b"<Preferences/>"
    asyncio.run(configure(runtime, SimpleNamespace(installationId="plex-main")))
    runtime.control.plex_get.assert_not_awaited()
    assert not (runtime.state_dir / "plex-lan.json").exists()


def test_failed_publication_is_retried_and_not_acknowledged(runtime):
    original = runtime.control.plex_get.side_effect

    async def fail_refresh(policy, path, method="GET", params=None):
        if path == "/myplex/refreshReachability":
            raise DomainError("plex_api_unavailable", "Unavailable", 503)
        return await original(policy, path, method, params)

    runtime.control.plex_get.side_effect = fail_refresh
    policy = SimpleNamespace(installationId="plex-main")
    with pytest.raises(DomainError):
        asyncio.run(configure(runtime, policy))
    assert not (runtime.state_dir / "plex-lan.json").exists()
    runtime.control.plex_get.side_effect = original
    asyncio.run(configure(runtime, policy))
    assert read_json(runtime.state_dir / "plex-lan.json")["installationId"] == "plex-main"


def test_receipt_cannot_be_reused_for_another_installation(runtime):
    asyncio.run(configure(runtime, SimpleNamespace(installationId="plex-main")))
    with pytest.raises(DomainError):
        asyncio.run(configure(runtime, SimpleNamespace(installationId="replacement")))


def test_verified_public_url_rotates_without_removing_lan_or_user_urls(runtime):
    from agent.plex_lan import remove_public

    policy = SimpleNamespace(installationId="plex-main")
    asyncio.run(configure(runtime, policy))
    local = runtime.values["customConnections"]
    asyncio.run(configure(runtime, policy, public_endpoint=("8.8.8.8", 50001)))
    assert f"https://8-8-8-8.{CERTIFICATE}.plex.direct:50001" in runtime.values["customConnections"]
    asyncio.run(configure(runtime, policy, public_endpoint=("1.1.1.1", 50002)))
    assert "8-8-8-8" not in runtime.values["customConnections"]
    assert runtime.values["customConnections"].startswith(local + ",")
    asyncio.run(remove_public(runtime, policy))
    assert runtime.values["customConnections"] == local


def test_publication_waits_for_the_servers_certificate(runtime):
    runtime.preferences.return_value = b"<Preferences/>"
    with pytest.raises(DomainError) as error:
        asyncio.run(configure(runtime, SimpleNamespace(installationId="plex-main"),
                              public_endpoint=("8.8.8.8", 50001)))
    assert error.value.code == "plex_certificate_pending"
    runtime.control.plex_get.assert_not_awaited()
