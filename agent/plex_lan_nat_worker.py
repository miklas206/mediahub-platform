"""Translate only approved LAN traffic to the owned Plex Docker endpoint."""

import ipaddress
import json
import re
import shlex
import subprocess
import sys


def private(value):
    address = ipaddress.ip_address(value)
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    ):
        raise ValueError("Expected a private LAN address")
    return address


def command(*args):
    return subprocess.check_output(list(args), text=True, timeout=12)


def desired(value, interfaces):
    binding, target, gateway = (private(value[k]) for k in ("binding", "target", "gateway"))
    bridge = value["bridge"]
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", bridge):
        raise ValueError("Invalid Docker bridge")
    matches = [
        (row["ifname"], item)
        for row in interfaces
        for item in row.get("addr_info", [])
        if item.get("family") == "inet" and item.get("local") == str(binding)
    ]
    bridges = [
        item
        for row in interfaces
        if row.get("ifname") == bridge
        for item in row.get("addr_info", [])
        if item.get("family") == "inet" and item.get("local") == str(gateway)
    ]
    if len(matches) != 1 or len(bridges) != 1:
        raise ValueError("Host LAN or Docker gateway address changed")
    interface, lan = matches[0]
    network = ipaddress.ip_network(f"{binding}/{lan['prefixlen']}", strict=False)
    docker = ipaddress.ip_network(f"{gateway}/{bridges[0]['prefixlen']}", strict=False)
    if (
        interface == bridge
        or network.prefixlen < 16
        or not network.is_private
        or target not in docker
        or target == gateway
        or network.overlaps(docker)
    ):
        raise ValueError("LAN and Docker networks must be separate and bounded")
    return [
        "-s",
        str(network),
        "-d",
        str(target) + "/32",
        "-o",
        bridge,
        "-p",
        "tcp",
        "--dport",
        "32400",
        "-m",
        "conntrack",
        "--ctdir",
        "ORIGINAL",
        "--ctorigdst",
        str(binding),
        "--ctorigdstport",
        "32400",
        "-m",
        "comment",
        "--comment",
        "mediahub-plex-lan:" + value["installationId"],
        "-j",
        "SNAT",
        "--to-source",
        str(gateway),
    ]


def owned(rule, identity):
    """Refuse broad/unknown rules even when they carry our ownership comment."""

    def item(flag):
        if rule.count(flag) != 1:
            raise ValueError("Owned LAN rule changed")
        return rule[rule.index(flag) + 1]

    if item("--comment") != "mediahub-plex-lan:" + identity:
        return False
    network = ipaddress.ip_network(item("-s"))
    target = ipaddress.ip_network(item("-d"))
    if (
        network.version != 4
        or not network.is_private
        or network.prefixlen < 16
        or target.prefixlen != 32
        or not target.is_private
    ):
        raise ValueError("Owned LAN rule no longer has bounded addresses")
    private(item("--ctorigdst").split("/")[0])
    private(item("--to-source"))
    if (
        item("-p") != "tcp"
        or item("--dport") != "32400"
        or item("--ctorigdstport") != "32400"
        or item("--ctdir") != "ORIGINAL"
        or item("-j") != "SNAT"
    ):
        raise ValueError("Owned LAN rule scope changed")
    return True


def shape(args):
    result = {}
    allowed = {
        "-s",
        "-d",
        "-o",
        "-p",
        "--dport",
        "--ctdir",
        "--ctorigdst",
        "--ctorigdstport",
        "--comment",
        "-j",
        "--to-source",
    }
    if len(args) % 2:
        raise ValueError("Owned LAN rule syntax changed")
    for flag, value in zip(args[::2], args[1::2]):
        if flag == "-m" and value in {"tcp", "conntrack", "comment"}:
            continue
        if flag not in allowed or flag in result:
            raise ValueError("Owned LAN rule has unknown options")
        result[flag] = value.removesuffix("/32") if flag == "--ctorigdst" else value
    return result


def reconcile(value, run=command):
    identity = value["installationId"]
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,60}", identity):
        raise ValueError("Invalid Plex installation identity")
    rules = []
    for line in run("iptables", "-w", "5", "-t", "nat", "-S", "POSTROUTING").splitlines():
        rule = shlex.split(line)
        if (
            "--comment" in rule
            and rule[rule.index("--comment") + 1] == "mediahub-plex-lan:" + identity
        ):
            if not owned(rule, identity):
                raise ValueError("LAN rule ownership changed")
            shape(rule[2:])
            rules.append(rule[2:])
    args = (
        desired(value, json.loads(run("ip", "-j", "address", "show"))) if value["enabled"] else None
    )
    # iptables -C normalizes omitted masks/modules; don't compare its text output.
    exists = False
    if args:
        try:
            run("iptables", "-w", "5", "-t", "nat", "-C", "POSTROUTING", *args)
            exists = True
        except subprocess.CalledProcessError:
            pass
        if not exists:
            run("iptables", "-w", "5", "-t", "nat", "-I", "POSTROUTING", "1", *args)
    # Retain one matching rule and remove only other narrowly owned rules.
    retained = False
    for rule in rules:
        if args and shape(rule) == shape(args) and not retained:
            retained = True
            continue
        run("iptables", "-w", "5", "-t", "nat", "-D", "POSTROUTING", *rule)
    if args:
        run("iptables", "-w", "5", "-t", "nat", "-C", "POSTROUTING", *args)


if __name__ == "__main__":
    reconcile(json.loads(sys.argv[1]))
