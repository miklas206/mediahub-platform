import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError

from agent.natpmp import PROTON_INTERNAL_PORT
from agent.plex_vpn import (
    INPUT_COMMENT,
    PLEX_PORT,
    REDIRECT_COMMENT,
    PlexVPN,
    validate_wireguard_profile,
)


def test_stopped_vpn_missing_bridge_is_reconnected_and_rechecked():
    item = {
        "Id": "owned-vpn",
        "State": {"Running": False},
        "NetworkSettings": {"Networks": {"control": {}}},
    }
    repaired = {**item, "NetworkSettings": {"Networks": {"control": {}, "bridge": {}}}}
    request = AsyncMock(side_effect=[{"Driver": "bridge", "Internal": False}, {}])
    fake = SimpleNamespace(
        runtime=SimpleNamespace(request=request), _container=AsyncMock(return_value=repaired)
    )
    assert asyncio.run(PlexVPN._ensure_bridge(fake, item)) == repaired
    request.assert_any_await("POST", "/networks/bridge/connect", body={"Container": "owned-vpn"})
    fake._container.assert_awaited_once()


def test_vpn_with_bridge_needs_no_network_change():
    item = {"NetworkSettings": {"Networks": {"bridge": {}, "control": {}}}}
    request = AsyncMock()
    fake = SimpleNamespace(runtime=SimpleNamespace(request=request))
    assert asyncio.run(PlexVPN._ensure_bridge(fake, item)) is item
    request.assert_not_awaited()


@pytest.mark.parametrize(
    "running,network",
    [
        (True, {"Driver": "bridge", "Internal": False}),
        (False, {"Driver": "bridge", "Internal": True}),
        (False, {"Driver": "overlay", "Internal": False}),
    ],
)
def test_vpn_repair_rejects_running_container_or_non_egress_network(running, network):
    request = AsyncMock(return_value=network)
    fake = SimpleNamespace(runtime=SimpleNamespace(request=request))
    with pytest.raises(DomainError):
        asyncio.run(PlexVPN._ensure_bridge(fake, {"State": {"Running": running}}))
    assert all(call.args[0] == "GET" for call in request.await_args_list)


def profile(allowed="0.0.0.0/0"):
    private = base64.b64encode(b"p" * 32).decode()
    public = base64.b64encode(b"u" * 32).decode()
    return f"""[Interface]
PrivateKey = {private}
Address = 10.2.0.2/32
DNS = 10.2.0.1

[Peer]
PublicKey = {public}
AllowedIPs = {allowed}
Endpoint = 149.88.109.34:51820
""".encode()


def test_full_tunnel_profile_is_accepted_without_changing_payload():
    payload = profile()
    assert validate_wireguard_profile(payload) is payload


@pytest.mark.parametrize(
    "payload",
    [b"not-wireguard", profile("10.0.0.0/8"), profile().replace(b"51820", b"0")],
)
def test_profile_rejects_incomplete_or_non_full_tunnel_configuration(payload):
    with pytest.raises(DomainError) as error:
        validate_wireguard_profile(payload)
    assert error.value.code == "plex_vpn_profile_invalid"


def test_forwarded_port_is_redirected_and_allowed_only_on_vpn_interface():
    calls = []

    async def execute(_vpn, command):
        calls.append(command)
        if command in (
            ["iptables", "-t", "nat", "-S", "PREROUTING"],
            ["iptables", "-S", "INPUT"],
        ):
            return ""
        if "-C" in command:
            raise ValueError("rule missing")
        return ""

    fake = SimpleNamespace(_exec=execute)
    asyncio.run(PlexVPN._apply_redirect(fake, {"Id": "vpn"}, 42264))

    redirect = next(command for command in calls if REDIRECT_COMMENT in command and "-I" in command)
    assert redirect[redirect.index("--dport") + 1] == str(PROTON_INTERNAL_PORT)
    assert redirect[redirect.index("--to-ports") + 1] == str(PLEX_PORT)

    allowed = next(command for command in calls if INPUT_COMMENT in command and "-I" in command)
    assert allowed[allowed.index("-i") + 1] == "tun0"
    assert allowed[allowed.index("--dport") + 1] == str(PLEX_PORT)
    assert allowed[-1] == "ACCEPT"


def test_public_probe_uses_isolated_secretless_bridge_helper():
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET" and path.startswith("/containers/") and path.endswith("/json"):
            return {"Image": "sha256:" + "a" * 64}
        if method == "POST" and path.startswith("/containers/create?"):
            return {"Id": "probe"}
        if method == "POST" and path == "/containers/probe/wait":
            return {"StatusCode": 0}
        if method == "GET" and path.endswith("/logs?stdout=true&stderr=false"):
            return b"reachable\n"
        return {}

    fake = SimpleNamespace(runtime=SimpleNamespace(request=request))
    assert asyncio.run(PlexVPN._probe_public(fake, "1.1.1.1", 42264)) is True

    create = next(item for item in calls if item[1].startswith("/containers/create?"))
    body = create[2]["body"]
    host = body["HostConfig"]
    assert host["NetworkMode"] == "bridge"
    assert host["ReadonlyRootfs"] is True
    assert host["CapDrop"] == ["ALL"]
    assert "Mounts" not in host
    assert body["Entrypoint"][-2:] == ["1.1.1.1", "42264"]
    assert any(
        method == "DELETE" and path.startswith("/containers/probe?") for method, path, _ in calls
    )
