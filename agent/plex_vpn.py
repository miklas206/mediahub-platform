"""Dedicated fail-closed VPN runtime for Plex remote access.

The WireGuard profile is encrypted at rest.  A decrypted copy is written only
to a Docker tmpfs volume, and Plex shares Gluetun's network namespace.  Proton
NAT-PMP leases are requested from inside that namespace and translated to
Plex's fixed local listener without changing Gluetun's kill-switch policy.
"""

from __future__ import annotations

import asyncio
import base64
import configparser
import contextlib
import io
import ipaddress
import json
import shlex
import socket
import tarfile
import time
import uuid
from pathlib import Path

import httpx
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

from agent.install_files import save_json
from agent.natpmp import PROTON_INTERNAL_PORT

PLEX_PORT = 32400
REDIRECT_COMMENT = "mediahub-plex-pf"
INPUT_COMMENT = "mediahub-plex-vpn-input"


def validate_wireguard_profile(payload: bytes) -> bytes:
    """Validate a bounded full-tunnel WireGuard profile without exposing it."""

    if not isinstance(payload, bytes) or not 100 <= len(payload) <= 65536 or b"\x00" in payload:
        raise DomainError("plex_vpn_profile_invalid", "VPN profile is invalid", 422)
    try:
        text = payload.decode("utf-8")
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        parser.read_string(text)
        private_key = parser["Interface"]["PrivateKey"].strip()
        address = parser["Interface"]["Address"].split(",", 1)[0].strip()
        public_key = parser["Peer"]["PublicKey"].strip()
        endpoint = parser["Peer"]["Endpoint"].strip()
        allowed = {part.strip() for part in parser["Peer"]["AllowedIPs"].split(",")}
        host, separator, port = endpoint.rpartition(":")
        if not separator or not host or not 1 <= int(port) <= 65535:
            raise ValueError()
        ipaddress.ip_interface(address)
        if "0.0.0.0/0" not in allowed:
            raise ValueError()
        for key in (private_key, public_key):
            if len(base64.b64decode(key, validate=True)) != 32:
                raise ValueError()
    except (KeyError, ValueError, configparser.Error, UnicodeError):
        raise DomainError("plex_vpn_profile_invalid", "VPN profile is invalid", 422) from None
    return payload


class PlexVPN:
    def __init__(self, runtime):
        self.runtime = runtime
        self.control = runtime.control
        self.store = SecretStore(runtime.state_dir / "plex-vpn-secrets")
        self.state_file = runtime.state_dir / "plex-vpn-status.json"
        self.current = {
            "verified": False,
            "externalIp": None,
            "countryCode": None,
            "lastVerified": None,
            "vpnIdentity": None,
            "port": None,
            "lastRenewed": None,
            "expiresAt": None,
            "lastAppliedPort": None,
            "publicReachable": False,
            "lastReachabilityCheck": None,
            "lastErrorCode": None,
        }

    def policy(self):
        policy = self.runtime.policy().vpn
        if policy is None or policy.provider != "protonvpn":
            raise DomainError("plex_vpn_disabled", "An approved Proton VPN policy is required", 409)
        return policy

    def store_profile(self, payload: bytes):
        policy = self.policy()
        profile = validate_wireguard_profile(payload)
        if self.store.status(policy.secretReference)["configured"]:
            self.store.replace(policy.secretReference, profile)
        else:
            self.store.put(policy.secretReference, profile)

    async def _container(self, required=True):
        policy = self.policy()
        rows = await self.runtime.request("GET", "/containers/json?all=1")
        matches = [row for row in rows if "/" + policy.container in row.get("Names", [])]
        if not matches:
            if required:
                raise DomainError("plex_vpn_missing", "Plex VPN runtime is missing", 503)
            return None
        if len(matches) != 1:
            raise DomainError("plex_vpn_ownership", "Plex VPN identity is ambiguous", 409)
        item = await self.runtime.request("GET", f"/containers/{matches[0]['Id']}/json")
        labels = item.get("Config", {}).get("Labels", {})
        ports = item.get("HostConfig", {}).get("PortBindings") or {}
        mounts = item.get("Mounts", [])
        capabilities = set(item.get("HostConfig", {}).get("CapAdd") or [])
        devices = item.get("HostConfig", {}).get("Devices") or []
        control_network = self.runtime.policy().controlNetwork
        networks = item.get("NetworkSettings", {}).get("Networks", {})
        if (
            labels.get("org.mediahub.package") != "org.mediahub.plex"
            or labels.get("org.mediahub.component") != "vpn"
            or item.get("Config", {}).get("Image") != policy.image
            or item.get("HostConfig", {}).get("Privileged")
            or item.get("HostConfig", {}).get("PidMode") == "host"
            or not ({"NET_ADMIN", "CAP_NET_ADMIN"} & capabilities)
            or not any(d.get("PathOnHost") == "/dev/net/tun" for d in devices)
            or (control_network and control_network not in networks)
            or ports.get(f"{PLEX_PORT}/tcp")
            != [{"HostIp": self.runtime.policy().bindAddress, "HostPort": str(PLEX_PORT)}]
            or not any(
                m.get("Type") == "volume"
                and m.get("Name") == policy.configVolume
                and m.get("Destination") == "/gluetun/wireguard"
                and m.get("RW") is False
                for m in mounts
            )
        ):
            raise DomainError("plex_vpn_ownership", "Plex VPN runtime violates policy", 409)
        return item

    async def _ensure_volume(self):
        policy = self.policy()
        result = await self.runtime.request("GET", "/volumes")
        matches = [v for v in result.get("Volumes") or [] if v.get("Name") == policy.configVolume]
        if matches:
            volume = matches[0]
            if (
                volume.get("Driver") != "local"
                or volume.get("Labels", {}).get("org.mediahub.component") != "plex-vpn-config"
                or volume.get("Options", {}).get("type") != "tmpfs"
            ):
                raise DomainError("plex_vpn_volume_ownership", "VPN RAM volume is unsafe", 409)
            return
        options = "size=1m,nodev,nosuid,noexec,mode=0700,uid=0,gid=0"
        await self.runtime.request(
            "POST",
            "/volumes/create",
            body={
                "Name": policy.configVolume,
                "Driver": "local",
                "Labels": {
                    "org.mediahub.package": "org.mediahub.plex",
                    "org.mediahub.component": "plex-vpn-config",
                },
                "DriverOpts": {"type": "tmpfs", "device": "tmpfs", "o": options},
            },
        )

    async def _stage_volume(self):
        policy = self.policy()
        await self._ensure_volume()
        profile = self.store.get(policy.secretReference)
        validate_wireguard_profile(profile)
        name = "mediahub-plex-vpn-prepare-" + uuid.uuid4().hex[:12]
        body = {
            "Image": self.runtime.policy().initImage,
            "User": "0:0",
            "Entrypoint": [
                "python",
                "-c",
                "import pathlib,time; pathlib.Path('/runtime').chmod(0o700); time.sleep(180)",
            ],
            "Labels": {
                "org.mediahub.package": "org.mediahub.plex",
                "org.mediahub.component": "vpn-config-helper",
            },
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": policy.configVolume,
                        "Target": "/runtime",
                        "ReadOnly": False,
                    }
                ],
                "Memory": 64 * 1024**2,
                "MemorySwap": 64 * 1024**2,
                "PidsLimit": 16,
                "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                "LogConfig": {"Type": "none", "Config": {}},
            },
        }
        identifier = (
            await self.runtime.request("POST", f"/containers/create?name={name}", body=body)
        )["Id"]
        try:
            await self.runtime.request("POST", f"/containers/{identifier}/start")
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode="w") as archive:
                entry = tarfile.TarInfo("wg0.conf")
                entry.size, entry.mode, entry.uid, entry.gid = len(profile), 0o600, 0, 0
                archive.addfile(entry, io.BytesIO(profile))
            await self.runtime.request(
                "PUT", f"/containers/{identifier}/archive?path=/runtime", payload=stream.getvalue()
            )
            await self._exec(
                {"Id": identifier},
                [
                    "python",
                    "-c",
                    "import os,pathlib; p=pathlib.Path('/runtime/wg0.conf'); "
                    "assert p.is_file() and not p.is_symlink() and p.stat().st_mode & 0o777 == 0o600 "
                    "and p.stat().st_size >= 100",
                ],
            )
            profile = b""
            return identifier
        except Exception:
            with contextlib.suppress(DomainError):
                await self.runtime.request("POST", f"/containers/{identifier}/stop?t=2")
            with contextlib.suppress(DomainError):
                await self.runtime.request("DELETE", f"/containers/{identifier}?v=false")
            profile = b""
            raise

    async def _remove_config_helper(self, identifier):
        with contextlib.suppress(DomainError):
            await self.runtime.request("POST", f"/containers/{identifier}/stop?t=2")
        with contextlib.suppress(DomainError):
            await self.runtime.request("DELETE", f"/containers/{identifier}?v=false")

    async def _create_container(self):
        policy = self.policy()
        existing = await self._container(required=False)
        if existing:
            return existing
        await self._ensure_volume()
        outbound_subnets = [policy.lanSubnet]
        control_network = self.runtime.policy().controlNetwork
        if control_network:
            network = await self.runtime.request("GET", f"/networks/{control_network}")
            candidates = []
            for row in network.get("IPAM", {}).get("Config") or []:
                try:
                    subnet = ipaddress.ip_network(row.get("Subnet", ""), strict=True)
                except ValueError:
                    continue
                if subnet.version == 4 and subnet.is_private and subnet.prefixlen >= 16:
                    candidates.append(str(subnet))
            if len(candidates) != 1:
                raise DomainError(
                    "plex_vpn_control_network_invalid",
                    "MediaHub control network is not a bounded private subnet",
                    409,
                )
            outbound_subnets.append(candidates[0])
        body = {
            "Image": policy.image,
            "Labels": {
                "org.mediahub.package": "org.mediahub.plex",
                "org.mediahub.component": "vpn",
            },
            "Env": [
                "VPN_SERVICE_PROVIDER=custom",
                "VPN_TYPE=wireguard",
                "VPN_INTERFACE=tun0",
                f"FIREWALL_INPUT_PORTS={PLEX_PORT}",
                f"FIREWALL_VPN_INPUT_PORTS={PLEX_PORT}",
                f"FIREWALL_OUTBOUND_SUBNETS={','.join(outbound_subnets)}",
                "LOG_LEVEL=warn",
                "HEALTH_SERVER_ADDRESS=127.0.0.1:9999",
            ],
            "ExposedPorts": {f"{PLEX_PORT}/tcp": {}},
            "Healthcheck": {
                "Test": ["CMD-SHELL", "/gluetun-entrypoint healthcheck"],
                "Interval": 5_000_000_000,
                "Timeout": 5_000_000_000,
                "StartPeriod": 10_000_000_000,
                "Retries": 3,
            },
            "HostConfig": {
                "NetworkMode": "bridge",
                "Privileged": False,
                "CapAdd": ["NET_ADMIN"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Devices": [
                    {
                        "PathOnHost": "/dev/net/tun",
                        "PathInContainer": "/dev/net/tun",
                        "CgroupPermissions": "rwm",
                    }
                ],
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": policy.configVolume,
                        "Target": "/gluetun/wireguard",
                        "ReadOnly": True,
                    }
                ],
                "PortBindings": {
                    f"{PLEX_PORT}/tcp": [
                        {
                            "HostIp": self.runtime.policy().bindAddress,
                            "HostPort": str(PLEX_PORT),
                        }
                    ]
                },
                "Memory": policy.memoryBytes,
                "MemorySwap": policy.memoryBytes,
                "PidsLimit": 256,
                "RestartPolicy": {"Name": "no"},
                "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                "LogConfig": {
                    "Type": "json-file",
                    "Config": {"max-size": "1m", "max-file": "1"},
                },
            },
        }
        created = await self.runtime.request(
            "POST", f"/containers/create?name={policy.container}", body=body
        )
        try:
            if control_network:
                await self.runtime.request(
                    "POST",
                    f"/networks/{control_network}/connect",
                    body={"Container": created["Id"]},
                )
        except Exception:
            with contextlib.suppress(DomainError):
                await self.runtime.request(
                    "DELETE", f"/containers/{created['Id']}?force=false&v=false"
                )
            raise
        return await self._container()

    async def _exec(self, container, command, max_output=16384):
        execution = await self.runtime.request(
            "POST",
            f"/containers/{container['Id']}/exec",
            body={"AttachStdout": True, "AttachStderr": False, "Tty": True, "Cmd": command},
        )
        output = await self.runtime.request(
            "POST",
            f"/exec/{execution['Id']}/start",
            body={"Detach": False, "Tty": True},
            binary=True,
        )
        status = await self.runtime.request("GET", f"/exec/{execution['Id']}/json")
        if status.get("ExitCode") != 0 or len(output) > max_output:
            raise ValueError("Plex VPN component verification failed")
        return output.decode("utf-8", "strict").strip()

    async def _verify(self, container):
        route = await self._exec(container, ["ip", "route", "get", "1.1.1.1"])
        if "dev tun0" not in route:
            raise ValueError("VPN route not established")
        details = json.loads(
            await self._exec(container, ["wget", "-qO-", "-T", "8", "https://ipwho.is/"])
        )
        address = details.get("ip")
        country = str(details.get("country_code") or "").upper()
        if not details.get("success") or not ipaddress.ip_address(address).is_global:
            raise ValueError("VPN external address unavailable")
        if country != self.policy().expectedCountryCode:
            raise ValueError("VPN country does not match policy")
        self.current.update(
            verified=True,
            externalIp=address,
            countryCode=country,
            lastVerified=time.time(),
            vpnIdentity=(container["Id"], container["State"].get("StartedAt"), address),
        )
        return address

    async def _request_port(self, vpn):
        self_container = await self.runtime.request(
            "GET", f"/containers/{socket.gethostname()}/json"
        )
        name = "mediahub-plex-pmp-" + uuid.uuid4().hex
        script = Path(__file__).with_name("natpmp.py").read_text()
        body = {
            "Image": self_container["Image"],
            "User": "0:0",
            "Tty": True,
            "Entrypoint": ["python3", "-c", script],
            "Labels": {
                "org.mediahub.package": "org.mediahub.plex",
                "org.mediahub.component": "vpn-port-probe",
            },
            "HostConfig": {
                "NetworkMode": "container:" + vpn["Id"],
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "CapAdd": ["NET_RAW"],
                "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 64 * 1024**2,
                "MemorySwap": 64 * 1024**2,
                "PidsLimit": 16,
                "Ulimits": [{"Name": "core", "Soft": 0, "Hard": 0}],
                "LogConfig": {
                    "Type": "json-file",
                    "Config": {"max-size": "1m", "max-file": "1"},
                },
            },
        }
        identifier = (
            await self.runtime.request("POST", f"/containers/create?name={name}", body=body)
        )["Id"]
        try:
            await self.runtime.request("POST", f"/containers/{identifier}/start")
            waited = await self.runtime.request("POST", f"/containers/{identifier}/wait")
            if waited.get("StatusCode") != 0:
                raise ValueError("Port allocation unavailable")
            output = await self.runtime.request(
                "GET",
                f"/containers/{identifier}/logs?stdout=true&stderr=false",
                binary=True,
            )
            if len(output) > 1024:
                raise ValueError("Invalid port allocation response")
            lease = json.loads(output)
            if (
                type(lease.get("port")) is not int
                or not 1024 <= lease["port"] <= 65535
                or lease.get("remainingSeconds", 0) < 20
            ):
                raise ValueError("Unsafe port allocation response")
            return lease
        finally:
            with contextlib.suppress(DomainError):
                await self.runtime.request("DELETE", f"/containers/{identifier}?force=true&v=false")

    async def _apply_redirect(self, vpn, port):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("Invalid Plex forwarding port")
        listing = await self._exec(vpn, ["iptables", "-t", "nat", "-S", "PREROUTING"])
        owned = []
        for line in listing.splitlines():
            if REDIRECT_COMMENT in line:
                tokens = shlex.split(line)
                if not tokens or tokens[0] != "-A" or tokens[1] != "PREROUTING":
                    raise ValueError("Unexpected Plex redirect ownership")
                owned.append(tokens)
        # Proton translates the allocated public port to the private port sent
        # in the NAT-PMP request. natpmp.py deliberately requests private port
        # 1 so the provider can choose any public port. Packets therefore
        # arrive on tun0 with destination port 1, not with the public port.
        rule = [
            "PREROUTING",
            "-i",
            "tun0",
            "-p",
            "tcp",
            "--dport",
            str(PROTON_INTERNAL_PORT),
            "-m",
            "comment",
            "--comment",
            REDIRECT_COMMENT,
            "-j",
            "REDIRECT",
            "--to-ports",
            str(PLEX_PORT),
        ]
        try:
            await self._exec(vpn, ["iptables", "-t", "nat", "-C", *rule])
        except ValueError:
            await self._exec(vpn, ["iptables", "-t", "nat", "-I", *rule])
        for tokens in owned:
            if "--dport" in tokens and tokens[tokens.index("--dport") + 1] == str(
                PROTON_INTERNAL_PORT
            ):
                continue
            tokens[0] = "-D"
            await self._exec(vpn, ["iptables", "-t", "nat", *tokens])

        # FIREWALL_INPUT_PORTS only covers Gluetun's default Docker interface.
        # The Proton mapping arrives on tun0 and is translated above before the
        # filter INPUT chain, so narrowly allow Plex's fixed listener on tun0.
        listing = await self._exec(vpn, ["iptables", "-S", "INPUT"])
        owned = []
        for line in listing.splitlines():
            if INPUT_COMMENT in line:
                tokens = shlex.split(line)
                if not tokens or tokens[0] != "-A" or tokens[1] != "INPUT":
                    raise ValueError("Unexpected Plex VPN input-rule ownership")
                owned.append(tokens)
        input_rule = [
            "INPUT",
            "-i",
            "tun0",
            "-p",
            "tcp",
            "--dport",
            str(PLEX_PORT),
            "-m",
            "comment",
            "--comment",
            INPUT_COMMENT,
            "-j",
            "ACCEPT",
        ]
        try:
            await self._exec(vpn, ["iptables", "-C", *input_rule])
        except ValueError:
            await self._exec(vpn, ["iptables", "-I", *input_rule])
        for tokens in owned:
            if "--dport" in tokens and tokens[tokens.index("--dport") + 1] == str(PLEX_PORT):
                continue
            tokens[0] = "-D"
            await self._exec(vpn, ["iptables", *tokens])

    async def _probe_public(self, address, port):
        try:
            if not ipaddress.ip_address(address).is_global or not 1024 <= int(port) <= 65535:
                raise ValueError()
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(6, connect=4),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.get(f"http://{address}:{port}/identity")
            if len(response.content) > 64 * 1024 or response.status_code != 200:
                raise ValueError()
            return b"MediaContainer" in response.content
        except (httpx.HTTPError, ValueError, TypeError):
            return False

    async def prepare(self, plex_policy):
        vpn = await self._create_container()
        if not vpn["State"].get("Running"):
            helper = await self._stage_volume()
            try:
                await self.runtime.request("POST", f"/containers/{vpn['Id']}/start")
            finally:
                # Keep the tmpfs volume mounted until Gluetun has taken its own
                # reference; otherwise Docker unmounts it and its data vanishes.
                await self._remove_config_helper(helper)
            deadline = time.monotonic() + 45
            while True:
                vpn = await self._container()
                try:
                    await self._verify(vpn)
                    break
                except (DomainError, ValueError, KeyError, json.JSONDecodeError):
                    if time.monotonic() >= deadline:
                        raise DomainError(
                            "plex_vpn_unavailable", "Plex VPN verification timed out", 503
                        ) from None
                    await asyncio.sleep(2)
        elif (
            not self.current["verified"]
            or not self.current["lastVerified"]
            or time.time() - self.current["lastVerified"] > 20
        ):
            await self._verify(vpn)
        identity = (vpn["Id"], vpn["State"].get("StartedAt"), self.current["externalIp"])
        renew = (
            self.current["vpnIdentity"] != identity
            or not self.current["expiresAt"]
            or self.current["expiresAt"] - time.time() < 25
        )
        if renew:
            lease = await self._request_port(vpn)
            now = time.time()
            self.current.update(
                vpnIdentity=identity,
                port=lease["port"],
                lastRenewed=now,
                expiresAt=now + float(lease["remainingSeconds"]),
            )
            save_json(
                self.state_file,
                {
                    "provider": self.policy().provider,
                    "countryCode": self.current["countryCode"],
                    "externalIp": self.current["externalIp"],
                    "port": self.current["port"],
                    "lastRenewed": self.current["lastRenewed"],
                },
            )
        # Gluetun may rebuild its firewall during an internal tunnel reconnect
        # without restarting the container. Reconcile both owned rules on every
        # pass so a valid lease can never outlive its narrow tun0 input path.
        await self._apply_redirect(vpn, self.current["port"])
        return self.current["port"]

    async def activate(self, plex_policy, port=None):
        port = port or self.current["port"]
        if type(port) is not int:
            raise DomainError("plex_vpn_port_unavailable", "Plex VPN port is unavailable", 503)
        vpn = await self._container()
        plex = await self.control.inspect(plex_policy)
        if plex.get("HostConfig", {}).get("NetworkMode") != "container:" + vpn["Id"]:
            raise DomainError(
                "plex_vpn_namespace_mismatch",
                "Plex is not attached to the verified VPN namespace",
                409,
            )
        deadline = time.monotonic() + 45
        while True:
            try:
                await self.control.plex_get(plex_policy, "/identity")
                break
            except DomainError:
                if time.monotonic() >= deadline:
                    raise DomainError(
                        "plex_vpn_plex_unavailable", "Plex did not become ready", 503
                    ) from None
                await asyncio.sleep(1)
        if self.current["lastAppliedPort"] != port:
            await self.control.plex_get(
                plex_policy,
                "/:/prefs",
                "PUT",
                params={
                    "ManualPortMappingMode": "1",
                    "ManualPortMappingPort": str(port),
                    "PublishServerOnPlexOnlineKey": "1",
                },
            )
            self.current["lastAppliedPort"] = port
            self.current["publicReachable"] = False
            self.current["lastReachabilityCheck"] = None
        now = time.time()
        if (
            not self.current["lastReachabilityCheck"]
            or now - self.current["lastReachabilityCheck"] > 30
        ):
            self.current["publicReachable"] = await self._probe_public(
                self.current["externalIp"], port
            )
            self.current["lastReachabilityCheck"] = now
        self.current["lastErrorCode"] = None

    async def reconcile(self, plex_policy, plex_running):
        try:
            port = await self.prepare(plex_policy)
            if plex_running:
                await self.activate(plex_policy, port)
            return True
        except DomainError as error:
            # Keep diagnostics deliberately bounded.  The public status may expose
            # this fixed application error code, never raw exceptions, payloads,
            # commands, credentials or provider responses.
            self.current["lastErrorCode"] = error.code
            self.current.update(verified=False, externalIp=None, countryCode=None)
            return False
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            self.current["lastErrorCode"] = "plex_vpn_" + type(error).__name__.lower()
            self.current.update(verified=False, externalIp=None, countryCode=None)
            return False

    async def stop(self):
        with contextlib.suppress(DomainError):
            vpn = await self._container()
            if vpn["State"].get("Running"):
                await self.runtime.request("POST", f"/containers/{vpn['Id']}/stop?t=10")
        self.current.update(
            verified=False,
            externalIp=None,
            countryCode=None,
            vpnIdentity=None,
            port=None,
            expiresAt=None,
            lastAppliedPort=None,
            publicReachable=False,
            lastReachabilityCheck=None,
        )

    async def status(self, plex_policy):
        verified = False
        with contextlib.suppress(DomainError, ValueError, KeyError):
            vpn = await self._container()
            verified = bool(vpn["State"].get("Running") and self.current["verified"])
        return {
            "vpn": {
                "verified": verified,
                "externalIp": self.current["externalIp"] if verified else None,
                "provider": self.policy().provider,
                "protocol": "wireguard",
                "countryCode": self.current["countryCode"] if verified else None,
                "connectedSince": vpn["State"].get("StartedAt") if verified else None,
                "lastVerified": self.current["lastVerified"] if verified else None,
                "errorCode": self.current["lastErrorCode"],
            },
            "portForwarding": {
                "status": (
                    "healthy"
                    if verified and self.current["port"] and self.current["publicReachable"]
                    else "degraded"
                    if verified and self.current["port"]
                    else "not_ready"
                ),
                "currentPort": self.current["port"] if verified else None,
                "lastRenewed": self.current["lastRenewed"] if verified else None,
                "expiresAt": self.current["expiresAt"] if verified else None,
                "plexVerified": bool(
                    verified
                    and self.current["lastAppliedPort"] == self.current["port"]
                    and self.current["publicReachable"]
                ),
            },
        }
