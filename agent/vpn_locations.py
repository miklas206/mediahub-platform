"""Provider adapter: public catalog + private in-memory profile transformation."""

import asyncio
import base64
import configparser
import io
import ipaddress
import json
import secrets
import time
from pathlib import Path
from typing import Protocol

from mediahub.apps.seedbox_credentials import SeedboxCredentials, VPNProfileRegistry
from mediahub.errors import DomainError

from agent.install_files import read_json, save_json
from agent.ram_secrets import RuntimeSecrets
from agent.seedbox_provision import private_record
from agent.seedbox_secret_store import SeedboxSecretStore
from agent.vpn_optimizer import VPNOptimizer


class LocationProvider(Protocol):
    async def servers(self, driver): ...
    def profile(self, original: str, server: dict) -> str: ...


class ProtonLocations:
    def __init__(self):
        self.cached = []
        self.loaded = 0

    async def servers(self, driver):
        if self.cached and time.monotonic() - self.loaded < 600:
            return self.cached
        vpn = await driver.container("vpn")
        output = await driver.execute(
            vpn,
            ["/gluetun-entrypoint", "format-servers", "-protonvpn", "-format", "json"],
            max_output=8 * 1024 * 1024,
        )
        rows = json.loads(output)
        safe = []
        for row in rows:
            if (
                row.get("vpn") != "wireguard"
                or not row.get("port_forward")
                or row.get("secure_core")
                or row.get("tor")
            ):
                continue
            try:
                key = row["wgpubkey"]
                assert len(base64.b64decode(key, validate=True)) == 32
                ips = [
                    str(ipaddress.IPv4Address(ip))
                    for ip in row["ips"]
                    if ipaddress.ip_address(ip).is_global
                ]
                if not ips:
                    continue
                safe.append(
                    {
                        "id": row["hostname"],
                        "country": row["country"],
                        "name": row.get("server_name", row["hostname"]),
                        "publicKey": key,
                        "ips": ips,
                    }
                )
            except (ValueError, KeyError, AssertionError):
                continue
        if not safe:
            raise ValueError("No supported P2P servers")
        self.cached = safe
        self.loaded = time.monotonic()
        return safe

    def profile(self, original, server):
        config = configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config.read_string(original)
        # Proton keys are account credentials valid across its servers. Preserve all
        # private key/NAT-PMP address settings, replace only vetted peer parameters.
        port = config["Peer"]["Endpoint"].rsplit(":", 1)[1]
        if port != "51820":
            raise ValueError("Unsupported Proton WireGuard endpoint port")
        config["Peer"]["PublicKey"] = server["publicKey"]
        config["Peer"]["Endpoint"] = server["ips"][0] + ":51820"
        output = io.StringIO()
        config.write(output)
        return output.getvalue()


class LocationService:
    def __init__(self, control):
        self.control = control
        self.optimizer = VPNOptimizer(self)
        self.providers: dict[str, LocationProvider] = {"protonvpn": ProtonLocations()}

    def context(self):
        self.control.initialize()
        policy, spec = self.control.driver.binding()
        provider = self.providers.get(spec.provider)
        if provider is None:
            raise DomainError(
                "location_unsupported", "This provider has no location adapter yet", 409
            )
        return Path(policy.workRoot), spec, provider

    async def public(self):
        root, spec, provider = self.context()
        saved = (
            read_json(root / "vpn-location.json") if (root / "vpn-location.json").exists() else {}
        )
        try:
            rows = await provider.servers(self.control.driver)
            available = True
        except Exception:
            rows = getattr(provider, "cached", [])
            available = False
        current = saved.get("verified")
        if current is None and rows:
            store = SeedboxSecretStore(root / "vault")
            credentials = store.load("seedbox-runtime")
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read_string(credentials.vpnConfig.get_secret_value())
            endpoint = cfg.get("Peer", "Endpoint").rsplit(":", 1)[0]
            found = next((row for row in rows if endpoint in row["ips"]), None)
            if found:
                current = {
                    "country": found["country"],
                    "server": found["id"],
                    "countryEvidence": "provider catalog; geolocation not independently checked",
                }
        return {
            "provider": spec.provider,
            "available": available,
            "current": current,
            "operation": self.optimizer.operation(
                saved.get("operation", {"state": "idle", "step": None})
            ),
            "countries": sorted({r["country"] for r in rows}),
            "servers": [{k: r[k] for k in ("id", "country", "name")} for r in rows],
            "automaticDescription": "Compares download and upload through up to 3 P2P servers. Keeps the current server unless the combined measured speed improves by 25%. Tests interrupt torrent connections and use up to 30 MiB. Measurements include current network load; torrent speeds may differ.",
            "automation": self.optimizer.state(),
        }

    async def change(self, body):
        root, spec, provider = self.context()
        control = self.control
        if control.job and not control.job.done():
            raise DomainError("operation_busy", "Another operation is running", 409)
        try:
            rows = await provider.servers(control.driver)
            matches = [
                r
                for r in rows
                if r["country"] == body.country
                and (body.server == "automatic" or r["id"] == body.server)
            ]
            if not matches:
                raise ValueError("Server unavailable")
            previous = (
                read_json(root / "vpn-location.json")
                if (root / "vpn-location.json").exists()
                else {}
            )
            failed_id = (
                previous.get("requested", {}).get("server")
                if previous.get("operation", {}).get("state") == "failed"
                else None
            )
            if body.server == "automatic" and len(matches) > 1:
                matches = [row for row in matches if row["id"] != failed_id]
            candidates = secrets.SystemRandom().sample(
                matches, min(3 if body.server == "automatic" else 1, len(matches))
            )
        except Exception:
            raise DomainError(
                "location_unavailable", "No supported P2P server matches the selection", 409
            ) from None
        if control.job and not control.job.done():
            raise DomainError("operation_busy", "Another operation is running", 409)
        self.optimizer.save(
            {
                "enabled": body.server == "automatic",
                "country": body.country,
                "intervalHours": body.intervalHours,
                "nextCheck": time.time() + body.intervalHours * 3600,
            }
        )
        control.operation = {"state": "running", "action": "vpn-location"}
        control.job = asyncio.create_task(
            self.optimizer.run(matches)
            if body.server == "automatic"
            else self.apply_candidates(candidates)
        )
        return {"state": "accepted"}

    async def apply_candidates(self, candidates):
        for index, server in enumerate(candidates):
            if await self.apply(server, final_attempt=index == len(candidates) - 1):
                return

    async def apply(self, server, final_attempt=True):
        root, spec, provider = self.context()
        control = self.control
        driver = control.driver
        path = root / "vpn-location.json"
        previous = read_json(path) if path.exists() else {}
        state = {
            "verified": previous.get("verified"),
            "requested": {"country": server["country"], "server": server["id"]},
        }

        def progress(step, status="running"):
            phases = {
                "Block qBittorrent": 5,
                "Apply encrypted provider profile": 15,
                "Restart and verify tunnel": 35,
                "Verify external IP and country": 50,
                "Restore port forwarding": 65,
                "Start qBittorrent in verified VPN namespace": 80,
                "Verify qBittorrent connection and port": 90,
                "All safety checks passed": 100,
            }
            percent = phases.get(step, state.get("operation", {}).get("progress", 0))
            state["operation"] = {
                "state": status,
                "step": step,
                "progress": percent,
                "server": server["id"],
            }
            save_json(path, state)
            control.operation = {"state": status, "action": "vpn-location", "message": step}

        async with control.lifecycle.lock:
            control.lifecycle.state["desiredRunning"] = False
            control.lifecycle.persist()
            try:
                progress("Block qBittorrent")
                await driver.stop_torrent()
                await driver.storage_guard()
                await driver.device_guard()
                progress("Apply encrypted provider profile")
                store = SeedboxSecretStore(root / "vault")
                old = store.load("seedbox-runtime")
                new = SeedboxCredentials(
                    vpnConfig=provider.profile(old.vpnConfig.get_secret_value(), server),
                    webUsername=old.webUsername,
                    webPassword=old.webPassword,
                )
                new.vpnConfig = VPNProfileRegistry().get(spec.protocol).validate(new.vpnConfig)
                await driver.stop_vpn()
                store.replace("seedbox-runtime", private_record(new))
                RuntimeSecrets(root).materialize()
                progress("Restart and verify tunnel")
                await driver.start_vpn()
                ip = await driver.verify_vpn()
                vpn = await driver.container("vpn")
                # Independent GeoIP is optional: fail on a definite mismatch; mark
                # unsupported/unavailable evidence honestly rather than claiming verification.
                evidence = "provider catalog; geolocation unavailable"
                progress("Verify external IP and country")
                try:
                    geo = json.loads(
                        await driver.execute(vpn, ["wget", "-qO-", "-T", "8", "https://ipwho.is/"])
                    )
                except Exception:
                    geo = {}
                if geo.get("success") is True and geo.get("ip") == ip and geo.get("country"):
                    if geo["country"] != server["country"]:
                        raise ValueError("Country mismatch")
                    evidence = "independent GeoIP and provider catalog"
                progress("Restore port forwarding")
                driver.forwarding.invalidate()
                await driver.forwarding.renew(apply=False)
                # Configure the port on disk while qBittorrent is stopped, so no
                # torrent runs even briefly with the previous advertised port.
                port = driver.forwarding.public().get("currentPort")
                await self.set_stopped_port(driver, port, spec)
                await driver.storage_guard()
                await driver.device_guard()
                progress("Start qBittorrent in verified VPN namespace")
                await driver.start_torrent()
                progress("Verify qBittorrent connection and port")
                await driver.verify_torrent(ip)
                if (await driver.forwarding.apply_current())["status"] != "healthy":
                    raise ValueError("Forwarded port not verified")
                await driver.storage_guard()
                state["verified"] = {
                    "country": server["country"],
                    "server": server["id"],
                    "externalIp": ip,
                    "countryEvidence": evidence,
                }
                progress("All safety checks passed", "healthy")
                control.lifecycle.state["desiredRunning"] = True
                control.lifecycle.persist()
                control.emit("vpn.location_changed", "info")
                return True
            except BaseException as error:
                control.lifecycle.state["desiredRunning"] = False
                control.lifecycle.persist()
                try:
                    await driver.stop_torrent()
                finally:
                    progress(
                        "Location change blocked; qBittorrent remains stopped"
                        if final_attempt
                        else "P2P server unavailable; trying another server with torrent traffic blocked",
                        "failed" if final_attempt else "running",
                    )
                if isinstance(error, asyncio.CancelledError):
                    raise
                return False

    async def set_stopped_port(self, driver, port, spec):
        from agent.torrent_port import configure_stopped_port

        await configure_stopped_port(driver, port, spec)
