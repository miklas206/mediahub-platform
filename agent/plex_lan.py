"""Advertise the approved LAN listener without changing Plex authentication."""

import ipaddress
import re
import xml.etree.ElementTree as ET

from mediahub.errors import DomainError

from agent.install_files import read_json, save_json


async def configure(runtime, policy, *, public_endpoint=None, refresh=True):
    # Called under the existing Plex lifecycle lock. The IP comes exclusively
    # from the operator's installation policy, never from a browser request.
    address = ipaddress.ip_address(public_endpoint[0] if public_endpoint else runtime.policy().bindAddress)
    port = public_endpoint[1] if public_endpoint else 32400
    valid = address.is_global if public_endpoint else address.is_private
    if address.version != 4 or not valid or address.is_unspecified or not 1 <= port <= 65535:
        raise DomainError("plex_lan_address_invalid", "Plex requires an approved LAN address", 409)
    preferences = ET.fromstring(await runtime.preferences(policy))
    certificate = preferences.get("CertificateUUID", "")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", certificate):
        # A claimed server provisions its own certificate asynchronously.
        # Retry on the next monitor pass; never invent a TLS identity.
        if public_endpoint:
            raise DomainError("plex_certificate_pending", "Wait for Plex to provision its HTTPS certificate", 409)
        return
    endpoint = f"https://{str(address).replace('.', '-')}.{certificate}.plex.direct:{port}"
    receipt = runtime.state_dir / ("plex-public-url.json" if public_endpoint else "plex-lan.json")
    saved = read_json(receipt) if receipt.exists() else {}
    if saved and saved.get("installationId") != policy.installationId:
        raise DomainError("installation_changed", "Plex LAN ownership changed", 409)
    prefs = await runtime.control.plex_get(policy, "/:/prefs")
    setting = next((row for row in prefs if row.get("id") == "customConnections"), None)
    if setting is None:
        raise DomainError("plex_lan_settings_unavailable", "Finish Plex account setup for LAN discovery", 409)
    current = [part.strip() for part in setting.get("value", "").split(",") if part.strip()]
    desired = [url for url in current if url != saved.get("endpoint") or url == endpoint]
    if endpoint not in desired:
        desired.append(endpoint)
    value = ",".join(desired)
    if desired != current:
        await runtime.control.plex_get(policy, "/:/prefs", "PUT", params={"customConnections": value})
        verified = await runtime.control.plex_get(policy, "/:/prefs")
        if not any(row.get("id") == "customConnections" and row.get("value") == value for row in verified):
            raise DomainError("plex_lan_settings_unverified", "Plex did not confirm its LAN address", 409)
    # Persist the encrypted preference checkpoint before acknowledging migration.
    if desired != current or saved.get("endpoint") != endpoint:
        await runtime.checkpoint(policy)
        if refresh:
            await runtime.control.plex_get(policy, "/myplex/refreshReachability", "PUT")
        save_json(receipt, {"installationId": policy.installationId, "endpoint": endpoint})


async def remove_public(runtime, policy):
    receipt = runtime.state_dir / "plex-public-url.json"
    if not receipt.exists():
        return
    saved = read_json(receipt)
    if saved.get("installationId") != policy.installationId:
        raise DomainError("installation_changed", "Plex publication ownership changed", 409)
    prefs = await runtime.control.plex_get(policy, "/:/prefs")
    setting = next((row for row in prefs if row.get("id") == "customConnections"), None)
    if setting is None:
        raise DomainError("plex_remote_settings_unavailable", "Plex publication settings unavailable", 409)
    current = [part.strip() for part in setting.get("value", "").split(",") if part.strip()]
    value = ",".join(url for url in current if url != saved.get("endpoint"))
    if value != ",".join(current):
        await runtime.control.plex_get(policy, "/:/prefs", "PUT", params={"customConnections": value})
        verified = await runtime.control.plex_get(policy, "/:/prefs")
        if not any(row.get("id") == "customConnections" and row.get("value") == value for row in verified):
            raise DomainError("plex_remote_settings_unverified", "Plex publication cleanup unverified", 409)
        await runtime.checkpoint(policy)
        await runtime.control.plex_get(policy, "/myplex/refreshReachability", "PUT")
    receipt.unlink()
