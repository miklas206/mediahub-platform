"""Recognize only this application's exact tunnel-ingress rule shape."""

import shlex


def owned_ports(output):
    ports = set()
    for line in output.splitlines():
        try:
            fields = shlex.split(line)
        except ValueError:
            continue
        # iptables -S may insert an explicit transport match module.
        for protocol in ("tcp", "udp"):
            prefix = ["-A", "INPUT", "-i", "tun0", "-p", protocol]
            if fields[:6] != prefix:
                continue
            tail = fields[6:]
            if tail[:2] == ["-m", protocol]:
                tail = tail[2:]
            if (
                len(tail) != 8
                or tail[0] != "--dport"
                or tail[2:] != ["-m", "comment", "--comment", "mediahub-torrent-pf", "-j", "ACCEPT"]
            ):
                continue
            if tail[1].isdigit() and 1024 <= int(tail[1]) <= 65535:
                ports.add((protocol, int(tail[1])))
    return ports
