"""Bounded NAT-PMP exchange, executed ONLY inside the verified VPN namespace.

No router discovery, arbitrary gateway, credentials, persistence or log output.
Proton mapping convention: internal port1, preferred external port0,60s lease.
"""

import json
import socket
import struct
import time

PROTON_INTERNAL_PORT = 1


def request_packet(opcode, lifetime=60):
    if opcode not in (1, 2) or not 30 <= lifetime <= 120:
        raise ValueError("Invalid mapping request")
    return struct.pack("!BBHHHI", 0, opcode, 0, PROTON_INTERNAL_PORT, 0, lifetime)


def parse_response(packet, opcode):
    if len(packet) != 16:
        raise ValueError("Invalid NAT-PMP response")
    version, operation, result, epoch, internal, external, lifetime = struct.unpack(
        "!BBHIHHI", packet
    )
    if version != 0 or operation != opcode + 128 or result or internal != PROTON_INTERNAL_PORT:
        raise ValueError("NAT-PMP mapping refused")
    if not 1024 <= external <= 65535 or not 30 <= lifetime <= 120:
        raise ValueError("Unsafe NAT-PMP allocation")
    return {"port": external, "lifetime": lifetime, "epoch": epoch}


def proton_lease(socket_factory=socket.socket, clock=time.monotonic):
    results = []
    started = clock()
    # SO_BINDTODEVICE cannot silently fall back to eth0. Failure aborts before send.
    with socket_factory(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"tun0\0")
        connection.settimeout(2)
        connection.connect(("10.2.0.1", 5351))
        for opcode in (1, 2):
            response = None
            for _ in range(2):
                connection.send(request_packet(opcode))
                try:
                    response = parse_response(connection.recv(64), opcode)
                    break
                except TimeoutError:
                    continue
            if response is None:
                raise ValueError("NAT-PMP exchange timed out")
            results.append(response)
    if results[0]["port"] != results[1]["port"]:
        raise ValueError("TCP/UDP allocation mismatch")
    remaining = min(item["lifetime"] for item in results) - (clock() - started)
    if remaining < 20:
        raise ValueError("Insufficient remaining lease")
    return {"port": results[0]["port"], "remainingSeconds": remaining}


if __name__ == "__main__":
    try:
        print(json.dumps(proton_lease()))
    except Exception:
        # Fixed message only; never serialize command/environment/exception details.
        print(json.dumps({"status": "degraded", "reason": "natpmp_unavailable"}))
        raise SystemExit(1) from None
