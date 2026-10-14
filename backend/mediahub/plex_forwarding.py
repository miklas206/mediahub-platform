"""Separate Proton TCP forwarding for the installed, VPN-attached Plex server."""

import hashlib
import ipaddress
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import httpx

from mediahub.errors import DomainError


class PlexForwarding:
    def __init__(self, gateway):
        self.gateway, self.svc = gateway, gateway.svc

    def installed(self):
        shared = getattr(self.svc, "shared_vpn", None)
        return bool(shared and any(row["id"] == "plex" for row in shared.bindings()))

    async def target(self):
        _, client = self.svc.shared_vpn.target("plex")
        state = await client.request("GET", "/v1/shared-vpn/plex")
        if not state.get("enabled") or not state.get("ready"):
            raise DomainError(
                "plex_shared_vpn_required",
                "Connect Plex to the shared VPN before enabling its separate port",
                409,
            )
        address = urlsplit(await self.svc.cloudflare_management.origin("org.mediahub.plex"))
        try:
            ip = ipaddress.IPv4Address(address.hostname)
            port = address.port
        except (ValueError, TypeError):
            raise DomainError(
                "plex_origin_unavailable",
                "Plex needs its approved private address and TCP port 32400",
                409,
            ) from None
        if port != 32400 or not any(
            ip in ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        ):
            raise DomainError(
                "plex_origin_unavailable",
                "Plex needs its approved private address and TCP port 32400",
                409,
            )
        return {"address": str(ip), "port": 32400}

    def public(self, state):
        result = {
            **state.get("plexPortStatus", {}),
            "enabled": bool(state.get("plexPortEnabled")),
            "available": self.installed(),
        }
        result.setdefault("ready", False)
        if (
            not state.get("enabled")
            or not self.gateway.gateway.get("providerReady")
            or time.time() - (state.get("checkedAt") or 0) > 90
        ):
            result.update(ready=False)
        if not result["available"]:
            result.update(
                ready=False,
                message="Install Plex through MediaHub before enabling its separate port",
            )
        return result

    async def apply(self, state, reply):
        enabled = bool(state.get("plexPortEnabled") and state.get("enabled"))
        if not enabled:
            if state.get("plexPortApplied") and self.installed():
                _, client = self.svc.shared_vpn.target("plex")
                await client.request("PUT", "/v1/plex/shared-remote-access", {"enabled": False})
            state.update(plexPortApplied=False, plexPortStatus={"ready": False})
            return
        lease = reply.get("plexPort") or {}
        if not lease.get("ready"):
            state["plexPortStatus"] = {
                "ready": False,
                "message": lease.get("message") or "Waiting for a separate verified Plex TCP port",
            }
            return
        port, address = lease.get("publicPort"), lease.get("publicIp")
        if (
            type(port) is not int
            or not 1 <= port <= 65535
            or port in {reply.get("publicPort"), reply.get("torrentPort")}
            or not ipaddress.IPv4Address(address).is_global
        ):
            raise DomainError(
                "plex_port_conflict",
                "Plex needs a verified port separate from the web and torrent ports",
                409,
            )
        _, client = self.svc.shared_vpn.target("plex")
        response = await client.request(
            "PUT",
            "/v1/plex/shared-remote-access",
            {"enabled": True, "publicIp": address, "publicPort": port},
        )
        if response.get("enabled") is not True or response.get("publicPort") != port:
            raise DomainError(
                "plex_remote_settings_unverified",
                "Plex did not confirm its separate public port",
                409,
            )
        state["plexPortApplied"] = True
        verified = await self.probe(address, port, response.get("identityHash"))
        state["plexPortStatus"] = {
            "ready": verified,
            "publicPort": port,
            "publicIp": address,
            "message": "Plex remote access verified through Proton"
            if verified
            else "Plex port configured; public reachability is not verified yet",
        }

    @staticmethod
    async def probe(address, port, identity):
        if not identity:
            return False
        try:
            async with httpx.AsyncClient(
                timeout=8, trust_env=False, follow_redirects=False
            ) as client:
                async with client.stream("GET", f"http://{address}:{port}/identity") as response:
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 32768:
                            return False
            observed = ET.fromstring(content).get("machineIdentifier", "")
            return bool(observed and hashlib.sha256(observed.encode()).hexdigest() == identity)
        except (httpx.HTTPError, ValueError, ET.ParseError):
            return False
