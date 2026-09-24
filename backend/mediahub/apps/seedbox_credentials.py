"""Secret-safe first-install contracts and protocol adapters.

No persistence or network I/O. Explicit provisioning consumes SecretStr only on
the destination Agent; ordinary model serialization never returns secret fields.
"""

import base64
import configparser
import io
import ipaddress
import re
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, SecretStr, field_validator

from mediahub.contracts import StrictModel
from mediahub.errors import DomainError


class SeedboxCredentials(StrictModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    vpnConfig: SecretStr = Field(exclude=True)
    webUsername: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    webPassword: SecretStr = Field(exclude=True)

    @field_validator("vpnConfig")
    @classmethod
    def bounded_profile(cls, value):
        if not 1 <= len(value.get_secret_value().encode()) <= 65536:
            raise ValueError("VPN profile must contain 1–65536 bytes")
        return value

    @field_validator("webPassword")
    @classmethod
    def password_policy(cls, value):
        raw = value.get_secret_value()
        if not 16 <= len(raw) <= 256 or any(ord(char) < 32 for char in raw):
            raise ValueError("Use a password of 16–256 characters without control characters")
        return value

    def public(self):
        return {"vpn": {"configured": True}, "qBittorrent": {"configured": True}}


class QBitInitialSettings(StrictModel):
    incompleteDownloads: bool = True
    maxConnections: int = Field(default=100, ge=10, le=500)
    maxConnectionsPerTorrent: int = Field(default=40, ge=1, le=100)
    maxActiveDownloads: int = Field(default=1, ge=1, le=5)
    listenPort: int = Field(default=6881, ge=1024, le=65535)
    networkInterface: Literal["tun0"] = "tun0"
    # Paths are generated from approved logical storage, never accepted from UI.


class VPNProfileAdapter(Protocol):
    protocol: str

    def schema(self) -> dict: ...

    def validate(self, profile: SecretStr) -> SecretStr: ...


def _key(value):
    return len(base64.b64decode(value, validate=True)) == 32


class WireGuardProfileAdapter:
    protocol = "wireguard"

    def schema(self):
        return {
            "protocol": self.protocol,
            "supported": True,
            "fields": [
                {
                    "name": "vpnConfig",
                    "type": "secret-file",
                    "accept": ".conf",
                    "required": True,
                    "maxBytes": 65536,
                    "label": "WireGuard configuration",
                },
            ],
        }

    def validate(self, profile):
        # Import is data only: never invoke wg-quick or execute profile directives.
        try:
            raw = profile.get_secret_value()
            if not 1 <= len(raw.encode()) <= 65536 or "\x00" in raw:
                raise ValueError
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.optionxform = str
            parser.read_file(io.StringIO(raw))
            if parser.defaults() or set(parser.sections()) != {"Interface", "Peer"}:
                raise ValueError
            interface, peer = parser["Interface"], parser["Peer"]
            if set(interface) - {"PrivateKey", "Address", "DNS", "MTU"}:
                raise ValueError
            if set(peer) - {
                "PublicKey",
                "PresharedKey",
                "AllowedIPs",
                "Endpoint",
                "PersistentKeepalive",
            }:
                raise ValueError
            if not _key(interface["PrivateKey"]) or not _key(peer["PublicKey"]):
                raise ValueError
            if "PresharedKey" in peer and not _key(peer["PresharedKey"]):
                raise ValueError
            addresses = [
                ipaddress.ip_interface(part.strip()) for part in interface["Address"].split(",")
            ]
            if not addresses or any(
                addr.ip.is_unspecified or addr.ip.is_multicast or addr.ip.is_loopback
                for addr in addresses
            ):
                raise ValueError
            if "DNS" in interface:
                for part in interface["DNS"].split(","):
                    addr = ipaddress.ip_address(part.strip())
                    if addr.is_unspecified or addr.is_loopback or addr.is_multicast:
                        raise ValueError
            if "MTU" in interface and not 1280 <= int(interface["MTU"]) <= 1500:
                raise ValueError
            routes = {
                str(ipaddress.ip_network(part.strip(), strict=True))
                for part in peer["AllowedIPs"].split(",")
            }
            if "0.0.0.0/0" not in routes or routes - {"0.0.0.0/0", "::/0"}:
                raise ValueError
            endpoint = peer["Endpoint"]
            match = re.fullmatch(r"(?:\[([0-9A-Fa-f:]+)\]|([A-Za-z0-9.-]+)):(\d{1,5})", endpoint)
            if not match or not 1 <= int(match[3]) <= 65535:
                raise ValueError
            host = match[1] or match[2]
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if (
                    len(host) > 253
                    or "." not in host
                    or host.lower().endswith((".local", ".localhost", ".internal", ".arpa"))
                    or any(
                        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                        for label in host.split(".")
                    )
                ):
                    raise ValueError from None
            else:
                if not address.is_global:
                    raise ValueError
            if "PersistentKeepalive" in peer and not 0 <= int(peer["PersistentKeepalive"]) <= 65535:
                raise ValueError
            # Canonicalize: discard comments, duplicate case variants are rejected above.
            output = io.StringIO()
            parser.write(output)
            return SecretStr(output.getvalue())
        except (ValueError, KeyError, configparser.Error, UnicodeError):
            # No profile fragments, key values or original exception details.
            raise DomainError(
                "invalid_vpn_profile", "Invalid or unsupported WireGuard profile", 422
            ) from None


class VPNProfileRegistry:
    """Protocol boundary allows later provider/OpenVPN adapters without Core rewrites."""

    def __init__(self, adapters=None):
        self.adapters = {
            item.protocol: item
            for item in (adapters if adapters is not None else [WireGuardProfileAdapter()])
        }

    def get(self, protocol):
        if protocol not in self.adapters:
            raise DomainError(
                "vpn_protocol_unavailable",
                "This VPN protocol has no approved provisioning adapter",
                422,
            )
        return self.adapters[protocol]

    def schemas(self):
        return [adapter.schema() for adapter in self.adapters.values()]
