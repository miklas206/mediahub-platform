import asyncio
import json
import shlex
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mediahub.errors import DomainError

from agent.plex_lan_nat import configure
from agent.plex_lan_nat_worker import desired, reconcile, shape

CONFIG = {
    "installationId": "plex-main",
    "enabled": True,
    "binding": "192.168.1.185",
    "target": "172.17.0.2",
    "gateway": "172.17.0.1",
    "gatewayHost": "192.168.1.185",
    "bridge": "docker0",
}
INTERFACES = [
    {
        "ifname": "eth0",
        "addr_info": [{"family": "inet", "local": "192.168.1.185", "prefixlen": 24}],
    },
    {
        "ifname": "docker0",
        "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16}],
    },
]


class Host:
    def __init__(self):
        self.rules = []
        self.writes = []

    def run(self, *args):
        if args[0] == "ip":
            return json.dumps(INTERFACES)
        action = args[5]
        if action == "-S":
            return "\n".join(shlex.join(["-A", "POSTROUTING", *r]) for r in self.rules)
        rule = list(args[8:] if action == "-I" else args[7:])
        if action == "-C":
            if not any(shape(r) == shape(rule) for r in self.rules):
                raise subprocess.CalledProcessError(1, args)
        elif action == "-I":
            self.rules.insert(0, rule)
            self.writes.append(action)
        elif action == "-D":
            self.rules.remove(rule)
            self.writes.append(action)
        else:
            raise AssertionError(args)
        return ""


def test_lan_rule_is_bounded_and_idempotent_and_never_matches_internet_clients():
    host = Host()
    reconcile(CONFIG, host.run)
    reconcile(CONFIG, host.run)
    assert host.writes == ["-I", "-I"]
    rule = next(
        shape(r) for r in host.rules if shape(r)["--comment"].startswith("mediahub-plex-lan:")
    )
    assert rule["!--ctorigsrc"] == CONFIG["gatewayHost"]
    remote = next(
        shape(r) for r in host.rules if shape(r)["--comment"].startswith("mediahub-plex-wan:")
    )
    assert remote["-s"] == "172.17.0.0/16"
    assert remote["--to-source"] == CONFIG["binding"]
    assert rule["-s"] == "192.168.1.0/24"
    assert rule["-d"] == "172.17.0.2/32"
    assert rule["--ctorigdst"] == "192.168.1.185"
    assert rule["--dport"] == rule["--ctorigdstport"] == "32400"
    assert rule["--to-source"] == "172.17.0.1"
    assert rule["--ctdir"] == "ORIGINAL"


def test_bridge_endpoint_change_and_disable_remove_only_owned_rules():
    host = Host()
    reconcile(CONFIG, host.run)
    unrelated = ["-s", "10.0.0.0/24", "-j", "MASQUERADE"]
    host.rules.append(unrelated)
    reconcile({**CONFIG, "target": "172.17.0.3"}, host.run)
    assert len(host.rules) == 3 and unrelated in host.rules
    reconcile({"installationId": "plex-main", "enabled": False}, host.run)
    assert host.rules == [unrelated]


def test_iptables_listing_option_order_and_modules_do_not_remove_matching_rule():
    host = Host()
    args = desired(CONFIG, INTERFACES)
    # iptables -S adds a module and may reorder conntrack arguments.
    host.rules = [args[0] + ["-m", "tcp"], args[1]]
    reconcile(CONFIG, host.run)
    assert host.writes == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("binding", "192.168.2.4"),
        ("binding", "8.8.8.8"),
        ("target", "192.168.1.4"),
        ("gateway", "172.17.0.8"),
        ("bridge", "docker0;bad"),
    ],
)
def test_unverified_host_addresses_and_interfaces_are_rejected_before_mutation(key, value):
    host = Host()
    with pytest.raises(ValueError):
        reconcile({**CONFIG, key: value}, host.run)
    assert host.writes == []


def test_unknown_owned_rule_is_preserved_and_blocks_reconfiguration():
    host = Host()
    host.rules = [desired(CONFIG, INTERFACES)[0] + ["--random", "yes"]]
    with pytest.raises(ValueError):
        reconcile(CONFIG, host.run)
    assert host.writes == []


@pytest.mark.parametrize("exit_code", [0, 1])
def test_helper_has_only_host_network_admin_and_no_secrets_or_mounts(tmp_path, exit_code):
    spec = {
        "Labels": {"org.mediahub.installation": "plex-main"},
        "HostConfig": {
            "PortBindings": {"32400/tcp": [{"HostIp": "192.168.1.185", "HostPort": "32400"}]}
        },
    }
    relay = {
        "Image": "sha256:" + "a" * 64,
        "NetworkSettings": {
            "Networks": {"bridge": {"IPAddress": "172.17.0.2", "Gateway": "172.17.0.1"}}
        },
    }

    async def request(method, path, body=None):
        if path == "/networks/bridge":
            return {"Driver": "bridge", "Options": {}}
        if path.startswith("/containers/create"):
            return {"Id": "helper"}
        if path.endswith("/wait"):
            return {"StatusCode": exit_code}
        return {}

    shared = SimpleNamespace(
        directory=tmp_path,
        request=AsyncMock(side_effect=request),
        state=lambda app: {"peer": {"endpointIp": "192.168.1.185"}},
    )
    if exit_code:
        with pytest.raises(DomainError):
            asyncio.run(configure(shared, spec, relay))
        assert not (tmp_path / "plex-lan-nat.json").exists()
    else:
        asyncio.run(configure(shared, spec, relay))
        asyncio.run(configure(shared, spec, relay))
    calls = [
        call
        for call in shared.request.await_args_list
        if call.args[1].startswith("/containers/create")
    ]
    assert len(calls) == 1
    host = calls[0].args[2]["HostConfig"]
    assert host["NetworkMode"] == "host" and host["CapAdd"] == ["NET_ADMIN"]
    assert host["CapDrop"] == ["ALL"] and host["ReadonlyRootfs"]
    assert not host["Privileged"] and "Mounts" not in host and "Binds" not in host
    shared.request.assert_any_await("DELETE", "/containers/helper?v=false")


def test_upgrade_old_lan_rule_and_preserve_public_proxy_classification():
    import ipaddress

    host = Host()
    old = desired(CONFIG, INTERFACES)[0].copy()
    index = old.index("!")
    del old[index : index + 3]
    host.rules = [old]
    reconcile(CONFIG, host.run)
    reconcile(CONFIG, host.run)
    assert len(host.rules) == 2
    assert host.writes == ["-I", "-I", "-D"]

    def translated(source):
        for args in host.rules:
            rule = shape(args)
            if ipaddress.ip_address(source) in ipaddress.ip_network(
                rule["-s"]
            ) and source != rule.get("!--ctorigsrc"):
                return rule["--to-source"]
        return source

    assert translated("192.168.1.144") == "172.17.0.1"
    assert translated("172.17.0.3") == "192.168.1.185"
    assert translated("172.17.0.1") == "192.168.1.185"
    assert translated("192.168.1.185") == "192.168.1.185"
    assert translated("8.8.8.8") == "8.8.8.8"
