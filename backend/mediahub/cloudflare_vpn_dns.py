"""DNS-only records bound to verified MediaVPN profile egress, never arbitrary browser IPs."""

import re
import time
from ipaddress import ip_address
from uuid import uuid4

from pydantic import Field

from mediahub.contracts import StrictModel
from mediahub.errors import DomainError


class VPNRecord(StrictModel):
    zoneId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    label: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
    profileId: str = Field(pattern=r"^[a-f0-9]{24}$")


def public_address(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        address = ip_address(value or "")
        if not address.is_global:
            raise ValueError()
        return str(address), "A" if address.version == 4 else "AAAA"
    except ValueError:
        raise DomainError(
            "vpn_ip_unverified", "MediaVPN has no verified public IP for this profile", 409
        ) from None


async def refresh_profiles(manager, force=False):
    if not force and time.monotonic() < getattr(manager, "vpn_deadline", 0):
        return
    manager.vpn_deadline = time.monotonic() + 30
    manager.vpn_snapshot = {"profiles": [], "message": None}
    try:
        report = await manager.svc.shared_vpn.vpn(path="/status", shared=False)
        profiles = report.get("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError()
        for row in profiles[:100]:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or not re.fullmatch(r"[a-f0-9]{24}", row["id"])
                or not isinstance(row.get("name"), str)
            ):
                raise ValueError()
            address, kind = None, None
            if row.get("healthy") is True:
                try:
                    address, kind = public_address(row.get("publicIp"))
                except DomainError:
                    pass
            manager.vpn_snapshot["profiles"].append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "publicIp": address,
                    "type": kind,
                    "ready": bool(address),
                    "forwardedPort": row.get("forwardedPort"),
                }
            )
    except DomainError as error:
        manager.vpn_snapshot["message"] = error.message
    except (ValueError, TypeError, KeyError):
        manager.vpn_snapshot = {
            "profiles": [],
            "message": "MediaVPN profile status could not be verified",
        }


def selected_profile(manager, identifier):
    profile = next(
        (row for row in manager.vpn_snapshot["profiles"] if row["id"] == identifier), None
    )
    if not profile or not profile["ready"]:
        raise DomainError(
            "vpn_ip_unverified",
            "Start and verify the selected MediaVPN profile before publishing DNS",
            409,
        )
    return profile


async def reconcile(manager, row, force=False):
    try:
        profile = selected_profile(manager, row["profileId"])
        address, kind = public_address(profile["publicIp"])
        row["forwardedPort"] = profile.get("forwardedPort")
        if (
            row.get("recordId")
            and row.get("content") == address
            and row.get("type") == kind
            and row.get("status") == "synced"
            and not force
        ):
            return
        prefix = "/zones/" + row["zoneId"] + "/dns_records"
        tag = "MediaHub VPN DNS " + row["id"]
        values = {
            "name": row["hostname"],
            "type": kind,
            "content": address,
            "proxied": False,
            "ttl": 1,
            "comment": tag,
        }
        if not row.get("recordId"):
            existing = await manager.call(
                "GET", prefix, params={"name": row["hostname"], "per_page": 100}
            )
            # Recover a successful POST whose response was lost, only with our exact ownership tag.
            if existing:
                if (
                    len(existing) != 1
                    or existing[0].get("comment") != tag
                    or existing[0].get("proxied") is not False
                    or existing[0].get("type") not in {"A", "AAAA"}
                ):
                    raise DomainError(
                        "dns_conflict",
                        "An existing DNS record uses this hostname; it was not overwritten",
                        409,
                    )
                remote = existing[0]
                row.update(recordId=remote["id"], content=remote["content"], type=remote["type"])
            else:
                remote = await manager.call("POST", prefix, values)
                row.update(recordId=remote["id"], content=address, type=kind)
        actual = await manager.call("GET", prefix + "/" + row["recordId"])
        if (
            actual.get("name") != row["hostname"]
            or actual.get("comment") != tag
            or actual.get("proxied") is not False
            or actual.get("type") != row["type"]
            or actual.get("content") != row["content"]
        ):
            raise DomainError(
                "dns_conflict",
                "This VPN DNS record was changed outside MediaHub; automatic changes are paused",
                409,
            )
        if row["content"] != address or row["type"] != kind:
            await manager.call("PATCH", prefix + "/" + row["recordId"], values)
            row.update(content=address, type=kind)
        row.update(
            status="synced", message="VPN DNS record is up to date", checkedAt=int(time.time())
        )
    except DomainError as error:
        row.update(
            status="blocked" if error.code == "vpn_ip_unverified" else "error",
            message=error.message,
        )


async def create(manager, body):
    from mediahub.cloudflare_management import hostname

    async with manager.lock:
        await refresh_profiles(manager, force=True)
        selected_profile(manager, body.profileId)
        zone = await manager.call("GET", "/zones/" + body.zoneId)
        # Only the subdomain label is entered; domain and target IP come from trusted APIs.
        name = hostname(body.label + "." + zone["name"])
        state = manager.state()
        rows = state.setdefault("vpnRecords", [])
        if len(rows) >= 32 or any(row["hostname"] == name for row in rows):
            raise DomainError(
                "dns_exists",
                "This VPN hostname is already linked or the record limit was reached",
                409,
            )
        row = {
            "id": uuid4().hex,
            "zoneId": body.zoneId,
            "hostname": name,
            "profileId": body.profileId,
            "recordId": None,
            "content": None,
            "type": None,
            "autoSync": True,
            "status": "pending",
            "message": "Publishing VPN DNS record",
        }
        rows.append(row)
        manager.save(state)  # Journal intent before remote writes for safe retries.
        await reconcile(manager, row)
        manager.save(state)
        manager.discovery_at = 0
        return manager.public()
