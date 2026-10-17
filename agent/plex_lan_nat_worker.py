"""Classify LAN clients and the public proxy at the owned Plex endpoint."""

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
    binding, target, gateway, gateway_host = (
        private(value[k]) for k in ("binding", "target", "gateway", "gatewayHost")
    )
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
        or docker.prefixlen < 16
        or not docker.is_private
    ):
        raise ValueError("LAN and Docker networks must be separate and bounded")
    common = [
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
    ]
    suffix = ["-m", "comment", "--comment"]
    local = [
        "-s",
        str(network),
        *common,
        "!",
        "--ctorigsrc",
        str(gateway_host),
        *suffix,
        "mediahub-plex-lan:" + value["installationId"],
        "-j",
        "SNAT",
        "--to-source",
        str(gateway),
    ]
    # A same-host public TCP proxy arrives from Docker, not from the LAN.
    # Use the private host address as its WAN-side stand-in. This also works
    # when the proxy and Plex use different provider profiles/namespaces.
    remote = [
        "-s",
        str(docker),
        *common,
        *suffix,
        "mediahub-plex-wan:" + value["installationId"],
        "-j",
        "SNAT",
        "--to-source",
        str(binding),
    ]
    return [local, remote]


def owned(rule, identity):
    """Refuse broad/unknown rules even when they carry our ownership comment."""

    def item(flag):
        if rule.count(flag) != 1:
            raise ValueError("Owned LAN rule changed")
        return rule[rule.index(flag) + 1]

    if item("--comment") not in {"mediahub-plex-lan:" + identity, "mediahub-plex-wan:" + identity}:
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
        "--ctorigsrc",
        "--ctorigdstport",
        "--comment",
        "-j",
        "--to-source",
    }
    position = 0
    while position < len(args):
        flag = args[position]
        negative = flag == "!"
        if negative:
            position += 1
            if position >= len(args):
                raise ValueError("Owned LAN rule syntax changed")
            flag = args[position]
        if position + 1 >= len(args):
            raise ValueError("Owned LAN rule syntax changed")
        value = args[position + 1]
        position += 2
        if flag == "-m" and value in {"tcp", "conntrack", "comment"}:
            continue
        key = "!" + flag if negative else flag
        if flag not in allowed or key in result or (negative and flag != "--ctorigsrc"):
            raise ValueError("Owned LAN rule has unknown options")
        result[key] = value.removesuffix("/32") if flag in {"--ctorigdst", "--ctorigsrc"} else value
    return result


def reconcile(value, run=command):
    identity = value["installationId"]
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,60}", identity):
        raise ValueError("Invalid Plex installation identity")
    rules = []
    for line in run("iptables", "-w", "5", "-t", "nat", "-S", "POSTROUTING").splitlines():
        rule = shlex.split(line)
        if "--comment" in rule and rule[rule.index("--comment") + 1] in {
            "mediahub-plex-lan:" + identity,
            "mediahub-plex-wan:" + identity,
        }:
            if not owned(rule, identity):
                raise ValueError("LAN rule ownership changed")
            shape(rule[2:])
            rules.append(rule[2:])
    wanted = (
        desired(value, json.loads(run("ip", "-j", "address", "show"))) if value["enabled"] else []
    )
    # iptables -C normalizes omitted masks/modules; don't compare its text output.
    for args in wanted:
        exists = False
        try:
            run("iptables", "-w", "5", "-t", "nat", "-C", "POSTROUTING", *args)
            exists = True
        except subprocess.CalledProcessError:
            pass
        if not exists:
            run("iptables", "-w", "5", "-t", "nat", "-I", "POSTROUTING", "1", *args)
    # Retain one matching rule and remove only other narrowly owned rules.
    retained = set()
    for rule in rules:
        matching = next((i for i, args in enumerate(wanted) if shape(rule) == shape(args)), None)
        if matching is not None and matching not in retained:
            retained.add(matching)
            continue
        run("iptables", "-w", "5", "-t", "nat", "-D", "POSTROUTING", *rule)
    for args in wanted:
        run("iptables", "-w", "5", "-t", "nat", "-C", "POSTROUTING", *args)


if __name__ == "__main__":
    reconcile(json.loads(sys.argv[1]))
