"""Apply only a verified shared-gateway port to the owned Plex runtime."""

import hashlib
import ipaddress

from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from pydantic import Field, model_validator

from agent.install_files import read_json, save_json

KEYS = ("ManualPortMappingMode", "ManualPortMappingPort", "PublishServerOnPlexOnlineKey")


class RemoteAccessChoice(StrictModel):
    enabled: bool
    publicPort: int | None = Field(default=None, ge=1, le=65535)
    publicIp: str | None = None

    @model_validator(mode="after")
    def endpoint(self):
        if self.enabled:
            if (
                not self.publicPort
                or not self.publicIp
                or not ipaddress.IPv4Address(self.publicIp).is_global
            ):
                raise ValueError("A verified public Plex endpoint is required")
        return self


async def configure(runtime, shared, body):
    control = runtime.control
    async with control.lock:
        policy = control.policy()
        receipt = runtime.state_dir / "plex-shared-remote.json"
        saved = read_json(receipt) if receipt.exists() else {}
        if saved and saved.get("installationId") != policy.installationId:
            raise DomainError("installation_changed", "Plex remote-access ownership changed", 409)
        if body.enabled:
            status = await shared.status("plex")
            if not status.get("enabled") or not status.get("ready"):
                raise DomainError(
                    "plex_shared_vpn_required",
                    "Connect Plex to the shared VPN before enabling its separate port",
                    409,
                )
        identity = await control.plex_get(policy, "/identity")
        machine = identity.get("machineIdentifier")
        if not machine:
            raise DomainError(
                "plex_identity_unavailable", "Plex server identity is unavailable", 409
            )
        prefs = await control.plex_get(policy, "/:/prefs")
        current = {
            row.get("id"): row.get("value", "")
            for row in prefs.findall("Setting")
            if row.get("id") in KEYS
        }
        if set(current) != set(KEYS):
            raise DomainError(
                "plex_remote_settings_unavailable",
                "Plex remote-access settings are unavailable; finish Plex account setup first",
                409,
            )
        if body.enabled:
            desired = dict(zip(KEYS, ("1", str(body.publicPort), "1")))
            if saved.get("applied") and current not in [
                saved["applied"],
                desired,
                saved.get("pending"),
            ]:
                raise DomainError(
                    "plex_remote_settings_changed",
                    "Plex remote access was changed outside MediaHub; disable forwarding and review it",
                    409,
                )
            saved = {
                **saved,
                "installationId": policy.installationId,
                "original": saved.get("original", current),
                "pending": desired,
            }
            save_json(receipt, saved)
            if current != desired:
                await control.plex_get(policy, "/:/prefs", "PUT", params=desired)
            verified = await control.plex_get(policy, "/:/prefs")
            actual = {
                row.get("id"): row.get("value", "")
                for row in verified.findall("Setting")
                if row.get("id") in KEYS
            }
            if actual != desired:
                raise DomainError(
                    "plex_remote_settings_unverified",
                    "Plex did not confirm its separate public port",
                    409,
                )
            saved.update(applied=desired)
            saved.pop("pending", None)
            save_json(receipt, saved)
            await runtime.checkpoint(policy)
        elif saved:
            # Restore only our last settings; preserve later user edits.
            if current in [saved.get("applied"), saved.get("pending")]:
                await control.plex_get(policy, "/:/prefs", "PUT", params=saved["original"])
                await runtime.checkpoint(policy)
            receipt.unlink(missing_ok=True)
        return {
            "enabled": body.enabled,
            "publicPort": body.publicPort if body.enabled else None,
            "identityHash": hashlib.sha256(machine.encode()).hexdigest(),
        }
