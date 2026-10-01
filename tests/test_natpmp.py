import socket
import struct

import pytest

from agent.natpmp import parse_response, proton_lease, request_packet


@pytest.fixture(autouse=True)
def linux_constant_for_fake_socket(monkeypatch):
    # Unit-test fake transport only; production must fail on unsupported platforms.
    monkeypatch.setattr(socket, "SO_BINDTODEVICE", 25, raising=False)


def reply(opcode=1, port=45000, result=0, internal=0, lifetime=60):
    return struct.pack("!BBHIHHI", 0, 128 + opcode, result, 10, internal, port, lifetime)


def test_packet_and_response_contract():
    assert request_packet(1) == struct.pack("!BBHHHI", 0, 1, 0, 0, 1, 60)
    assert parse_response(reply(), 1) == {"port": 45000, "lifetime": 60, "epoch": 10}


@pytest.mark.parametrize(
    "packet",
    [b"", reply(result=2), reply(port=22), reply(lifetime=0), reply(internal=2), reply(opcode=2)],
)
def test_refuse_invalid_or_unsafe_allocation(packet):
    with pytest.raises(ValueError):
        parse_response(packet, 1)


class Socket:
    def __init__(self, mismatch=False, denied=False, timeout=False):
        self.opcode = 0
        self.bound = False
        self.mismatch = mismatch
        self.denied = denied
        self.timeout = timeout
        self.sends = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def setsockopt(self, *args):
        if self.denied:
            raise PermissionError()
        assert args[-1] == b"tun0\0"
        self.bound = True

    def settimeout(self, value):
        assert value == 2

    def connect(self, address):
        assert self.bound and address == ("10.2.0.1", 5351)

    def send(self, packet):
        self.opcode = packet[1]
        self.sends += 1

    def recv(self, size):
        if self.timeout:
            raise TimeoutError()
        return reply(self.opcode, 45001 if self.mismatch and self.opcode == 2 else 45000)


def test_tunnel_bound_both_protocols():
    sock = Socket()
    assert proton_lease(lambda *_: sock)["port"] == 45000
    assert sock.sends == 2


def test_no_wan_fallback_if_interface_binding_fails():
    sock = Socket(denied=True)
    with pytest.raises(PermissionError):
        proton_lease(lambda *_: sock)
    assert sock.sends == 0


def test_retries_bounded_and_tcp_udp_mismatch_rejected():
    sock = Socket(timeout=True)
    with pytest.raises(TimeoutError):
        proton_lease(lambda *_: sock)
    assert sock.sends == 2
    with pytest.raises(ValueError):
        proton_lease(lambda *_: Socket(mismatch=True))
