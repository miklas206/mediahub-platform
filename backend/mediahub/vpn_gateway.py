"""App domains through the existing Proton gateway; no Cloudflare tunnel creation.

Cloudflare writes use per-resource ownership ledgers and durable pending payloads.
Only individual owned rules are patched, never an entire existing ruleset.
"""

import asyncio
import contextlib
import copy
import hashlib
import ipaddress
import json
import re
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from cryptography import x509
from fastapi import APIRouter, Depends, Request
from pydantic import Field, SecretStr, model_validator
from sqlalchemy import select

from mediahub.api import administrator, result, services
from mediahub.app_settings import saved_address
from mediahub.cloudflare_management import API, hostname
from mediahub.contracts import StrictModel
from mediahub.db import InstalledApp, Setting
from mediahub.errors import DomainError
from mediahub.plex_forwarding import PlexForwarding

KEY = "vpn-web-gateway"
PHASE = "http_request_origin"
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
DNS_FIELDS = ("name", "type", "content", "proxied", "ttl", "comment")
RULE_FIELDS = ("ref", "description", "expression", "action", "action_parameters", "enabled")


class Credentials(StrictModel):
    accountId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    token: SecretStr = Field(min_length=20, max_length=512)


class PlexPortChoice(StrictModel):
    enabled: bool


class GatewayRoute(StrictModel):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    packageId: str = Field(min_length=1, max_length=120)
    zoneId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    label: str = Field(min_length=1, max_length=100)


class AppDomainChoice(StrictModel):
    zoneId: str = Field(pattern=r"^[a-fA-F0-9]{32}$")
    label: str = Field(min_length=1, max_length=100)


class GatewayConfig(StrictModel):
    enabled: bool
    expectedRevision: int | None = Field(default=None, ge=0)
    profileId: str | None = Field(default=None, pattern=r"^[a-f0-9]{24}$")
    routes: list[GatewayRoute] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def selected(self):
        if self.enabled and (not self.profileId or not self.routes):
            raise ValueError("Choose a Proton profile and at least one installed app")
        return self


def selected_fields(value, fields):
    return {key: copy.deepcopy(value.get(key)) for key in fields}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class VPNGateway:
    def __init__(self, svc):
        self.svc = svc
        self.lock = asyncio.Lock()
        self.store = svc.cloudflare_management.store
        self.task = None
        self.retry_at = 0.0
        self.discovery_at = 0.0
        self.runtime_at = 0.0
        self.reconcile_at = 0.0
        self.gateway = {"ready": False, "providerReady": False, "phase": "unchecked"}
        self.profiles = []
        self.zones = []
        self.discovery_issue = None
        self.plex_forwarding = PlexForwarding(self)
        # Restore approved published hub origins before any SSO/API request;
        # startup must not depend on the next external reconciliation cycle.
        state = self.state()
        if state.get("enabled"):
            for row in state.get("routes", []):
                ledger = state.get("records", {}).get(row.get("id"), {})
                if (row.get("packageId") == "mediahub" and ledger.get("id")
                        and ledger.get("applied", {}).get("name") == row.get("hostname")):
                    self.svc.cloudflare_management.allow_hub_origin(row["hostname"])

    def state(self):
        with self.svc.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                return copy.deepcopy(row.value)
        return {
            "accountId": self.svc.cloudflare_management.state().get("accountId", ""),
            "enabled": False,
            "profileId": None,
            "routes": [],
            "retired": [],
            "records": {},
            "rules": {},
            "checks": [],
            "issues": [],
            "revision": 0,
        }

    def save(self, value):
        with self.svc.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == KEY))
            if row:
                row.value = copy.deepcopy(value)
            else:
                db.add(Setting(key=KEY, value=copy.deepcopy(value)))

    def configured(self):
        return self.store.status("api_token")["configured"]

    async def cf(self, method, path, body=None, *, params=None, token=None, missing=False):
        if time.monotonic() < self.retry_at:
            raise DomainError(
                "cloudflare_backoff",
                "Cloudflare request limit reached; the gateway will retry later",
                429,
            )
        token = token if token is not None else self.store.get("api_token").decode()
        try:
            async with httpx.AsyncClient(
                timeout=20, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    API + path,
                    params=params,
                    json=body,
                    headers={"Authorization": "Bearer " + token},
                )
            if response.status_code == 429:
                delay = response.headers.get("Retry-After", "60")
                self.retry_at = time.monotonic() + min(
                    3600, max(60, int(delay) if delay.isdigit() else 60)
                )
                raise DomainError(
                    "cloudflare_backoff",
                    "Cloudflare request limit reached; the gateway will retry later",
                    429,
                )
            if missing and response.status_code == 404:
                return None
            if response.status_code in {401, 403}:
                permission = (
                    "Zone DNS Edit"
                    if "/dns_records" in path
                    else "Zone Origin Rules Edit"
                    if "/rulesets" in path
                    else "Zone Settings Read"
                    if "/settings/" in path
                    else "Zone Read"
                )
                raise DomainError(
                    "cloudflare_permissions",
                    "Check the Cloudflare token and selected-zone permission: " + permission,
                    409,
                )
            response.raise_for_status()
            if len(response.content) > 2 * 1024 * 1024:
                raise ValueError()
            payload = response.json()
            if payload.get("success") is not True:
                raise ValueError()
            return payload["result"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DomainError(
                "cloudflare_unavailable",
                "Cloudflare could not confirm the operation; saved ownership was preserved for retry",
                502,
            ) from None

    async def vpn(self, method="GET", body=None, *, diagnostics=False):
        policies = self.svc.managed_apps.policy
        management = policies.get("org.mediahub.mediavpn")
        seed = policies.get("org.mediahub.mediaseed")
        address = getattr(management, "integrationUrl", None) or getattr(
            seed, "integrationUrl", None
        )
        key = getattr(management, "managementTokenFile", None)
        if not address or not key:
            raise DomainError(
                "vpn_integration_required",
                "Install MediaVPN and finish its private integration first",
                409,
            )
        try:
            token = key.read_text().strip()
            async with httpx.AsyncClient(
                timeout=5 if diagnostics else 45, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    address + ("/api/integration/diagnostics/logs" if diagnostics else "/api/integration/web-gateway"),
                    headers={"X-MediaHub-Key": token},
                    json=body,
                )
            if not response.is_success:
                raise DomainError(
                    "vpn_gateway_rejected",
                    "MediaVPN could not apply the web gateway; check the profile, runtime and port forwarding",
                    409,
                )
            if diagnostics and len(response.content) > 1024 * 1024:
                raise ValueError()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, ValueError, httpx.HTTPError):
            raise DomainError(
                "vpn_unavailable", "The private MediaVPN gateway API could not be reached", 503
            ) from None

    @staticmethod
    def sanitized_gateway(value):
        rows = value.get("routes") or []
        prerequisites = value.get("prerequisites") or []
        if not isinstance(rows, list) or not isinstance(prerequisites, list):
            raise DomainError("vpn_invalid_status", "MediaVPN returned invalid gateway status", 502)
        output = {
            key: value.get(key)
            for key in (
                "enabled",
                "profileId",
                "ready",
                "providerReady",
                "phase",
                "publicIp",
                "publicPort",
                "checkedAt",
                "torrentPort",
                "plexPort",
            )
        }
        output["routes"] = [
            {"id": row.get("id"), "certificateReady": row.get("certificateReady") is True}
            for row in rows[:32]
            if isinstance(row, dict)
        ]
        output["architecture"] = value.get("architecture")
        output["prerequisites"] = [
            {
                "id": str(row.get("id", "runtime"))[:80],
                "state": row.get("state")
                if row.get("state") in {"ready", "blocked", "pending", "warning"}
                else "pending",
                "message": str(row.get("message", "Runtime verification is pending"))[:500],
            }
            for row in prerequisites[:20]
            if isinstance(row, dict)
        ]
        return output

    async def discover(self, force=False):
        now = time.monotonic()
        if now >= self.runtime_at:
            self.runtime_at = now + 15
            try:
                self.gateway = self.sanitized_gateway(await self.vpn())
            except DomainError as error:
                self.gateway = {
                    "ready": False,
                    "providerReady": False,
                    "phase": "unavailable",
                    "message": error.message,
                }
            try:
                report = await self.svc.shared_vpn.vpn(path="/status", shared=False)
                self.profiles = [
                    {
                        key: row.get(key)
                        for key in ("id", "name", "healthy", "publicIp", "forwardedPort")
                    }
                    for row in report.get("profiles", [])[:100]
                    if isinstance(row, dict)
                    and re.fullmatch(r"[a-f0-9]{24}", str(row.get("id", "")))
                ]
            except (DomainError, TypeError):
                self.profiles = []
        if self.configured() and (
            now >= self.discovery_at or force and now >= self.discovery_at - 270
        ):
            self.discovery_at = now + 300
            try:
                rows = []
                for page in range(1, 21):
                    batch = await self.cf(
                        "GET",
                        "/zones",
                        params={
                            "account.id": self.state()["accountId"],
                            "page": page,
                            "per_page": 50,
                        },
                    )
                    if not isinstance(batch, list):
                        raise ValueError()
                    rows.extend(batch)
                    if len(batch) < 50:
                        break
                else:
                    raise DomainError(
                        "cloudflare_zone_limit",
                        "Restrict the Cloudflare token to the zones used by MediaHub",
                        409,
                    )
                self.zones = [
                    {"id": row["id"], "name": hostname(row["name"])}
                    for row in rows
                    if row.get("account", {}).get("id") == self.state()["accountId"]
                ]
                self.discovery_issue = None
            except DomainError as error:
                self.discovery_issue = {"code": error.code, "message": error.message}
            except (KeyError, TypeError, ValueError):
                self.discovery_issue = {
                    "code": "cloudflare_invalid",
                    "message": "Cloudflare returned invalid zone metadata",
                }

    def snapshot(self):
        state = self.state()
        route_keys = (
            "id",
            "packageId",
            "zoneId",
            "label",
            "hostname",
            "status",
            "message",
            "certificateReady",
            "httpsVerified",
            "checkedAt",
        )
        issues = list(state.get("issues", []))
        if self.discovery_issue:
            issues.append(self.discovery_issue)
        routes = [{key: row.get(key) for key in route_keys} for row in state["routes"]]
        for row in routes:
            if row.get("httpsVerified") and (
                not state["enabled"]
                or self.gateway.get("ready") is not True
                or self.gateway.get("profileId") != state["profileId"]
                or time.time() - (row.get("checkedAt") or 0) > 90
            ):
                row.update(
                    httpsVerified=False,
                    status="configured",
                    message="Public HTTPS needs fresh verification",
                )
        return {
            "configured": self.configured(),
            "accountId": state["accountId"],
            "enabled": state["enabled"],
            "profileId": state["profileId"],
            "plexPort": self.plex_forwarding.public(state),
            "routes": routes,
            "apps": self.svc.cloudflare_management.public()["apps"],
            "zones": copy.deepcopy(self.zones),
            "profiles": copy.deepcopy(self.profiles),
            "gateway": copy.deepcopy(self.gateway),
            "checks": [
                *state.get("checks", []),
                *(
                    {**row, "id": "runtime-" + row["id"]}
                    for row in self.gateway.get("prerequisites", [])
                ),
            ],
            "issues": issues,
            "checkedAt": state.get("checkedAt"),
            "busy": bool(self.task and not self.task.done()),
        }

    async def public(self, force=False):
        if not self.lock.locked():
            async with self.lock:
                await self.discover(force)
        return self.snapshot()

    async def credentials(self, body):
        async with self.lock, self.svc.cloudflare_management.lock:
            state = self.state()
            account = body.accountId.lower()
            if state["enabled"]:
                raise DomainError(
                    "gateway_enabled",
                    "Disable the web gateway before replacing its Cloudflare token",
                    409,
                )
            if state.get("machineEnabled") or state["records"] or state["rules"]:
                raise DomainError(
                    "gateway_cleanup_pending",
                    "Wait for gateway shutdown and owned-record cleanup before replacing its Cloudflare token",
                    409,
                )
            legacy = self.svc.cloudflare_management.state()
            if (
                state["accountId"]
                and account != state["accountId"]
                and (state["records"] or state["rules"] or legacy.get("tunnels"))
            ):
                raise DomainError(
                    "cloudflare_account",
                    "Keep the account that owns the existing records and tunnels",
                    409,
                )
            token = body.token.get_secret_value().strip()
            if not 20 <= len(token) <= 512 or any(
                ord(char) < 33 or ord(char) > 126 for char in token
            ):
                raise DomainError("cloudflare_token", "Enter a valid Cloudflare API token", 422)
            await self.cf(
                "GET", "/zones", params={"account.id": account, "per_page": 1}, token=token
            )
            if self.configured():
                self.store.replace("api_token", token.encode())
            else:
                self.store.put("api_token", token.encode())
            state["accountId"] = account
            state["machineFingerprint"] = None
            self.save(state)
            self.discovery_at = 0
        return await self.public()

    async def disconnect(self):
        async with self.lock, self.svc.cloudflare_management.lock:
            state = self.state()
            if state["enabled"] or state["records"] or state["rules"]:
                raise DomainError(
                    "gateway_owned_resources",
                    "Disable the gateway and finish owned-record cleanup before disconnecting Cloudflare",
                    409,
                )
            if self.svc.cloudflare_management.state().get("tunnels"):
                raise DomainError(
                    "legacy_cloudflare_credentials",
                    "Existing Cloudflare tunnels still use this credential; preserve their access",
                    409,
                )
            self.store.delete("api_token")
            self.zones = []
            return self.snapshot()

    async def zone(self, identifier):
        value = await self.cf("GET", "/zones/" + identifier)
        if (
            not isinstance(value, dict)
            or value.get("account", {}).get("id") != self.state()["accountId"]
        ):
            raise DomainError(
                "cloudflare_account", "Choose a zone in the connected Cloudflare account", 409
            )
        return hostname(value["name"])

    async def upstream(self, package):
        address = await self.svc.cloudflare_management.origin(package)
        parsed = urlsplit(address)
        try:
            ip = ipaddress.IPv4Address(parsed.hostname)
        except (ValueError, TypeError):
            raise DomainError(
                "gateway_origin",
                "The app needs a private IPv4 LAN address reachable from MediaVPN",
                409,
            ) from None
        if not any(ip in network for network in PRIVATE_NETWORKS):
            raise DomainError(
                "gateway_origin",
                "The app needs a private IPv4 LAN address reachable from MediaVPN",
                409,
            )
        route = {"upstream": address}
        if parsed.scheme == "https":
            path = getattr(self.svc.config, "agent_ca_file", None) or Path("/trust/ca.pem")
            try:
                pem = path.read_text(encoding="ascii")
                if len(pem) > 16384 or "PRIVATE KEY" in pem:
                    raise ValueError()
                x509.load_pem_x509_certificate(pem.encode())
            except (OSError, ValueError, UnicodeError):
                raise DomainError(
                    "gateway_trust",
                    "The MediaHub public CA certificate is required for the app's local HTTPS address",
                    409,
                ) from None
            route.update(tlsServerName=parsed.hostname, caPem=pem)
        return route

    async def configure(self, body):
        async with self.lock:
            state = self.state()
            if body.expectedRevision is not None and body.expectedRevision != state.get("revision", 0):
                raise DomainError("revision_conflict", "Gateway settings changed; review the latest configuration and retry", 409)
            if not body.enabled:
                # Disabling must work when an app is gone, its LAN host is down,
                # or Cloudflare discovery is unavailable. Keep saved selections.
                state.update(
                    enabled=False,
                    revision=state.get("revision", 0) + 1,
                    ownerId=state.get("ownerId") or uuid4().hex,
                )
                self.save(state)
                self.schedule()
                return self.snapshot()
            if body.enabled and not self.configured():
                raise DomainError(
                    "cloudflare_credentials", "Connect Cloudflare before enabling app domains", 409
                )
            await self.check_legacy_provider()
            old = {row["id"]: row for row in state["routes"]}
            rows, names, packages = [], set(), set()
            zones = {}
            for selected in body.routes:
                zone_id = selected.zoneId.lower()
                if zone_id not in zones:
                    zones[zone_id] = await self.zone(zone_id)
                name = hostname(selected.label + "." + zones[zone_id])
                if name in names or selected.packageId in packages:
                    raise DomainError(
                        "gateway_duplicate", "Choose each installed app and hostname only once", 422
                    )
                names.add(name)
                packages.add(selected.packageId)
                await self.upstream(selected.packageId)
                previous = (
                    old.get(selected.id)
                    if selected.id
                    else next(
                        (
                            row
                            for row in old.values()
                            if row["hostname"] == name
                            and row["packageId"] == selected.packageId
                            and row["zoneId"] == zone_id
                        ),
                        None,
                    )
                )
                if selected.id and previous is None:
                    raise DomainError(
                        "gateway_route_unknown",
                        "Refresh gateway settings before editing this route",
                        409,
                    )
                if previous and (
                    previous["hostname"],
                    previous["zoneId"],
                    previous["packageId"],
                ) != (name, zone_id, selected.packageId):
                    previous = None  # New identity; retire the previous exact owned hostname.
                external = saved_address(self.svc, selected.packageId)
                replaced = next(
                    (item for item in old.values() if item["packageId"] == selected.packageId), None
                )
                if replaced and external == "https://" + replaced["hostname"]:
                    external = replaced.get("previousExternalUrl", "")
                row = (
                    copy.deepcopy(previous)
                    if previous
                    else {
                        "id": uuid4().hex,
                        "previousExternalUrl": external,
                    }
                )
                row.update(
                    packageId=selected.packageId,
                    zoneId=zone_id,
                    label=selected.label,
                    hostname=name,
                    status="pending",
                    message="Gateway configuration saved; verification is pending",
                    httpsVerified=False,
                )
                rows.append(row)
            kept = {row["id"] for row in rows}
            retired = {row["id"]: row for row in state.get("retired", [])}
            retired.update(
                {identifier: row for identifier, row in old.items() if identifier not in kept}
            )
            if len(retired) > 64:
                raise DomainError(
                    "gateway_cleanup_pending",
                    "Resolve pending domain cleanup before changing more routes",
                    409,
                )
            state.update(
                enabled=body.enabled,
                profileId=body.profileId,
                routes=rows,
                retired=list(retired.values()),
                revision=state.get("revision", 0) + 1,
                ownerId=state.get("ownerId") or uuid4().hex,
                issues=[],
            )
            self.save(state)
        self.schedule()
        return self.snapshot()

    async def configure_plex_port(self, enabled):
        async with self.lock:
            state = self.state()
            if enabled:
                if not state["enabled"]:
                    raise DomainError("gateway_required", "Enable the shared gateway before adding Plex remote access", 409)
                await self.plex_forwarding.target()
            state.update(plexPortEnabled=enabled, plexPortManaged=True, plexPortStatus={"ready": False}, revision=state.get("revision", 0) + 1)
            self.save(state)
        self.schedule()
        return self.snapshot()

    async def check_legacy_provider(self):
        for binding in self.svc.shared_vpn.bindings():
            if binding["id"] == "plex":
                _, client = self.svc.shared_vpn.target("plex")
                status = await client.request("GET", "/v1/plex/status")
                if status.get("vpn"):
                    raise DomainError(
                        "vpn_conflict",
                        "Disable the old dedicated Plex VPN before enabling the shared web gateway",
                        409,
                    )

    def schedule(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.reconcile(force=True))
            self.task.add_done_callback(
                lambda task: task.exception() if not task.cancelled() else None
            )

    def record_payload(self, state, row, address):
        return {
            "name": row["hostname"],
            "type": "A",
            "content": address,
            "proxied": True,
            "ttl": 1,
            "comment": "MediaHub VPN " + state["ownerId"] + " route " + row["id"],
        }

    async def inspect_record(self, state, row):
        prefix = "/zones/" + row["zoneId"] + "/dns_records"
        rows = await self.cf("GET", prefix, params={"name": row["hostname"], "per_page": 100})
        ledger = state["records"].get(row["id"], {})
        if not isinstance(rows, list) or len(rows) > 1:
            raise DomainError(
                "dns_conflict",
                "Multiple DNS records use this hostname; existing records were preserved",
                409,
            )
        remote = rows[0] if rows else None
        if remote:
            actual = selected_fields(remote, DNS_FIELDS)
            if (ledger.get("id") and ledger["id"] != remote.get("id")) or actual not in [
                ledger.get("applied"),
                ledger.get("pending"),
            ]:
                raise DomainError(
                    "dns_conflict",
                    "This hostname already has a DNS record or was changed outside MediaHub; use a free hostname or explicitly migrate it",
                    409,
                )
        elif ledger.get("id") and not ledger.get("deleting"):
            raise DomainError(
                "dns_conflict",
                "The owned DNS record was removed outside MediaHub; automatic recreation is paused",
                409,
            )
        return remote

    async def sync_record(self, state, row, address):
        remote = await self.inspect_record(state, row)
        ledger = state["records"].setdefault(row["id"], {})
        payload = self.record_payload(state, row, address)
        if remote and selected_fields(remote, DNS_FIELDS) == payload:
            ledger.update(id=remote["id"], applied=payload)
            ledger.pop("pending", None)
            self.save(state)
            return
        ledger["pending"] = payload
        self.save(state)
        prefix = "/zones/" + row["zoneId"] + "/dns_records"
        remote = await self.cf(
            "PATCH" if remote else "POST", prefix + ("/" + remote["id"] if remote else ""), payload
        )
        if selected_fields(remote, DNS_FIELDS) != payload or not isinstance(remote.get("id"), str):
            raise DomainError(
                "dns_unconfirmed",
                "Cloudflare did not confirm the requested DNS record; retry will verify ownership",
                502,
            )
        ledger.update(id=remote["id"], applied=payload)
        ledger.pop("pending", None)
        self.save(state)

    async def delete_record(self, state, row):
        ledger = state["records"].get(row["id"])
        if not ledger:
            return
        remote = await self.inspect_record(state, row)
        ledger["deleting"] = True
        self.save(state)
        if remote:
            await self.cf(
                "DELETE", "/zones/" + row["zoneId"] + "/dns_records/" + remote["id"], missing=True
            )
        state["records"].pop(row["id"], None)
        self.save(state)

    async def sync_rule(self, state, zone_id, names, port):
        base = "/zones/" + zone_id
        ruleset = await self.cf(
            "GET", base + "/rulesets/phases/" + PHASE + "/entrypoint", missing=True
        )
        ledger = state["rules"].get(zone_id, {})
        ref = "mediahub_vpn_" + state["ownerId"]
        matches = [rule for rule in (ruleset or {}).get("rules", []) if rule.get("ref") == ref]
        if len(matches) > 1:
            raise DomainError(
                "origin_rule_conflict",
                "Multiple Origin Rules claim this gateway; automatic changes are paused",
                409,
            )
        remote = matches[0] if matches else None
        if remote:
            if (
                (ledger.get("id") and ledger["id"] != remote.get("id"))
                or (ledger.get("rulesetId") and ledger["rulesetId"] != ruleset.get("id"))
                or selected_fields(remote, RULE_FIELDS)
                not in [ledger.get("applied"), ledger.get("pending")]
            ):
                raise DomainError(
                    "origin_rule_conflict",
                    "The gateway Origin Rule was changed outside MediaHub; unrelated rules were preserved",
                    409,
                )
        elif ledger.get("id") and not ledger.get("deleting"):
            raise DomainError(
                "origin_rule_conflict",
                "The gateway Origin Rule was removed outside MediaHub; automatic recreation is paused",
                409,
            )
        if not names:
            if ledger:
                ledger["deleting"] = True
                self.save(state)
                if remote:
                    await self.cf(
                        "DELETE",
                        base + "/rulesets/" + ruleset["id"] + "/rules/" + remote["id"],
                        missing=True,
                    )
                state["rules"].pop(zone_id, None)
                self.save(state)
            return
        payload = {
            "ref": ref,
            "description": "MediaHub VPN gateway " + state["ownerId"],
            "expression": "http.host in {"
            + " ".join(json.dumps(name) for name in sorted(names))
            + "}",
            "action": "route",
            "action_parameters": {"origin": {"port": port}},
            "enabled": True,
        }
        ledger = state["rules"].setdefault(zone_id, ledger)
        if not remote or selected_fields(remote, RULE_FIELDS) != payload:
            ledger["pending"] = payload
            self.save(state)
            if ruleset is None:
                updated = await self.cf(
                    "POST",
                    base + "/rulesets",
                    {
                        "name": "MediaHub VPN origins",
                        "kind": "zone",
                        "phase": PHASE,
                        "rules": [payload],
                    },
                )
            else:
                path = base + "/rulesets/" + ruleset["id"] + "/rules"
                updated = await self.cf(
                    "PATCH" if remote else "POST",
                    path + ("/" + remote["id"] if remote else ""),
                    payload,
                )
            matches = [rule for rule in updated.get("rules", []) if rule.get("ref") == ref]
            if len(matches) != 1 or selected_fields(matches[0], RULE_FIELDS) != payload:
                raise DomainError(
                    "origin_rule_unconfirmed",
                    "Cloudflare did not confirm the Origin Rule; retry will verify ownership",
                    502,
                )
            ruleset, remote = updated, matches[0]
        ledger.update(id=remote["id"], rulesetId=ruleset["id"], applied=payload)
        ledger.pop("pending", None)
        self.save(state)

    @staticmethod
    def observed(gateway, profile):
        try:
            address = ipaddress.IPv4Address(gateway.get("publicIp"))
            port = gateway.get("publicPort")
            checked = gateway.get("checkedAt")
            if (
                gateway.get("providerReady") is not True
                or gateway.get("profileId") != profile
                or gateway.get("enabled") is not True
                or not address.is_global
                or type(port) is not int
                or not 1 <= port <= 65535
                or not isinstance(checked, (int, float))
                or not -30 <= time.time() - checked <= 90
            ):
                raise ValueError()
            return str(address), port
        except (ValueError, TypeError, ipaddress.AddressValueError):
            raise DomainError(
                "gateway_endpoint_pending",
                "Waiting for a fresh verified Proton public IPv4 address and forwarded port",
                409,
            ) from None

    @staticmethod
    def machine_matches(reply, payload):
        if (
            reply.get("enabled") is not payload["enabled"]
            or reply.get("profileId") != payload["profileId"]
        ):
            return False
        if "plex" in payload and reply.get("plex") != payload["plex"]:
            return False
        actual = reply.get("routes")
        if not isinstance(actual, list) or any(not isinstance(row, dict) for row in actual):
            return False
        fields = ("id", "hostname", "upstream")
        same_routes = sorted(
            (tuple(row.get(key) for key in fields) for row in actual), key=str
        ) == sorted((tuple(row.get(key) for key in fields) for row in payload["routes"]), key=str)
        if not same_routes:
            return False
        indexed = {row["id"]: row for row in actual}
        for expected in payload["routes"]:
            if expected["upstream"].startswith("https:"):
                pem = (expected.get("caPem") or "").replace("\r\n", "\n").strip()
                digest = hashlib.sha256(pem.encode()).hexdigest() if pem else None
                observed = indexed[expected["id"]]
                if (
                    observed.get("tlsServerName")
                    != expected.get("tlsServerName", urlsplit(expected["upstream"]).hostname)
                    or observed.get("caFingerprint") != digest
                ):
                    return False
        return True

    async def probe(self, name, route_id):
        """Pin a public DNS answer, validate TLS/SNI, and require our gateway route marker."""
        writer = None
        try:
            async with asyncio.timeout(8):
                answers = await asyncio.get_running_loop().getaddrinfo(
                    name, 443, type=socket.SOCK_STREAM
                )
                addresses = list(dict.fromkeys(row[4][0] for row in answers))
                if not addresses or any(
                    not ipaddress.ip_address(value).is_global for value in addresses
                ):
                    raise ValueError()
                reader, writer = await asyncio.open_connection(
                    addresses[0],
                    443,
                    ssl=ssl.create_default_context(),
                    server_hostname=name,
                    limit=16384,
                )
                writer.write(
                    (
                        "GET / HTTP/1.1\r\nHost: "
                        + name
                        + "\r\nUser-Agent: MediaHub-Gateway-Monitor/1\r\nConnection: close\r\n\r\n"
                    ).encode("ascii")
                )
                await writer.drain()
                header = (await reader.readuntil(b"\r\n\r\n")).decode("iso-8859-1")
                lines = header.split("\r\n")
                code = int(lines[0].split()[1])
                fields = {
                    key.lower(): value.strip()
                    for key, value in (line.split(":", 1) for line in lines[1:] if ":" in line)
                }
                return {
                    "reachable": (200 <= code < 400 or code in {401, 403}) and fields.get("x-mediavpn-route") == route_id,
                    "statusCode": code,
                    "checkedAt": int(time.time()),
                }
        except (
            OSError,
            ValueError,
            IndexError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            return {"reachable": False, "statusCode": None, "checkedAt": int(time.time())}
        finally:
            if writer:
                writer.close()

    def app_address(self, row, restore=False):
        if row["packageId"] == "mediahub":
            if not restore:
                self.svc.cloudflare_management.allow_hub_origin(row["hostname"])
            return
        address = "https://" + row["hostname"]
        key = "app_address:" + row["packageId"]
        with self.svc.sessions.begin() as db:
            setting = db.scalar(select(Setting).where(Setting.key == key))
            current = setting.value.get("externalUrl", "") if setting else ""
            if restore:
                if current == address and setting:
                    setting.value = {"externalUrl": row.get("previousExternalUrl", "")}
            elif current in {"", row.get("previousExternalUrl", ""), address}:
                if setting:
                    setting.value = {"externalUrl": address}
                else:
                    db.add(Setting(key=key, value={"externalUrl": address}))

    async def reconcile(self, force=False):
        async with self.lock:
            if time.monotonic() < self.reconcile_at and not force:
                return self.snapshot()
            self.reconcile_at = time.monotonic() + 60
            state = self.state()
            if not state.get("ownerId"):
                return self.snapshot()
            state.update(issues=[], checks=[], checkedAt=int(time.time()))
            try:
                with self.svc.sessions() as db:
                    removed_packages = set(db.scalars(select(InstalledApp.package_id).where(
                        InstalledApp.state == "uninstalled", InstalledApp.is_mock.is_(False)
                    )))
                removed_ids = {row["id"] for row in state["routes"] if row["packageId"] in removed_packages}
                active, machine_routes = [], []
                for row in state["routes"]:
                    if not state["enabled"]:
                        continue
                    try:
                        origin = await self.upstream(row["packageId"])
                        machine_routes.append(
                            {"id": row["id"], "hostname": row["hostname"], **origin}
                        )
                        active.append(row)
                    except DomainError as error:
                        row.update(status="blocked", message=error.message, httpsVerified=False)
                # An app restart is not a request to remove its hostname. If
                # every selected app is unavailable, preserve the last machine
                # configuration and all owned DNS until inspection can recover.
                if (state["enabled"] and not active
                        and not removed_ids and not state.get("retired")
                        and any(row["id"] not in removed_ids for row in state["routes"])):
                    self.gateway = self.sanitized_gateway(await self.vpn())
                    self.save(state)
                    return self.snapshot()
                payload = {
                    "enabled": bool(state["enabled"] and active),
                    "profileId": state["profileId"],
                    "routes": machine_routes,
                }
                if state.get("plexPortManaged"):
                    payload["plex"] = None
                    if state.get("plexPortEnabled") and payload["enabled"]:
                        try:
                            payload["plex"] = await self.plex_forwarding.target()
                        except DomainError as error:
                            state["plexPortStatus"] = {"ready": False, "message": error.message}
                desired = fingerprint(payload)
                reply = await self.vpn()
                self.gateway = self.sanitized_gateway(reply)
                if payload["enabled"] and any(
                    row["state"] == "blocked" for row in self.gateway["prerequisites"]
                ):
                    raise DomainError(
                        "gateway_prerequisites",
                        "Complete the blocked MediaVPN runtime requirements before enabling app domains",
                        409,
                    )
                if state.get("machineFingerprint") != desired or not self.machine_matches(
                    reply, payload
                ):
                    if payload["enabled"]:
                        await self.check_legacy_provider()
                        payload["cloudflareToken"] = self.store.get("api_token").decode()
                    await self.vpn("PUT", payload)
                    # The write acknowledgement intentionally reports applying,
                    # without a verified provider endpoint. Read the accepted
                    # configuration and current provider observation separately.
                    reply = await self.vpn()
                    state["machineFingerprint"] = desired
                    self.save(state)
                if not self.machine_matches(reply, payload):
                    state["machineFingerprint"] = None
                    raise DomainError(
                        "gateway_configuration_pending",
                        "MediaVPN has not confirmed the selected profile and exact app routes yet",
                        409,
                    )
                state["machineEnabled"] = payload["enabled"]
                self.gateway = self.sanitized_gateway(reply)
                self.runtime_at = time.monotonic() + 15
                active_ids = {row["id"] for row in active}
                cleanup = [
                    *state.get("retired", []),
                    *(row for row in state["routes"] if not state["enabled"] or row["id"] in removed_ids),
                ]
                for row in cleanup:
                    try:
                        await self.delete_record(state, row)
                        self.app_address(row, restore=True)
                    except DomainError as error:
                        state["issues"].append(
                            {"id": row["id"], "code": error.code, "message": error.message}
                        )
                state["retired"] = [
                    row for row in state.get("retired", []) if row["id"] in state["records"]
                ]
                selected_routes = [row for row in state["routes"] if row["id"] not in removed_ids] if state["enabled"] else []
                zones = {row["zoneId"] for row in selected_routes}
                for zone_id in set(state["rules"]) - zones:
                    try:
                        await self.sync_rule(state, zone_id, [], None)
                    except DomainError as error:
                        state["issues"].append(
                            {"id": zone_id, "code": error.code, "message": error.message}
                        )
                if not active:
                    if state.get("plexPortManaged"):
                        try:
                            await self.plex_forwarding.apply(state, {"plexPort": {"ready": False}})
                        except DomainError as error:
                            state["plexPortStatus"] = {"ready": False, "message": error.message}
                    for row in state["routes"]:
                        if not state["enabled"]:
                            row.update(
                                status="disabled",
                                message="Web forwarding is disabled",
                                httpsVerified=False,
                            )
                    self.save(state)
                    return self.snapshot()
                address, port = self.observed(self.gateway, state["profileId"])
                certificates = {
                    row["id"]: row.get("certificateReady") is True
                    for row in self.gateway.get("routes", [])
                }
                for zone_id in zones:
                    rows = [row for row in selected_routes if row["zoneId"] == zone_id]
                    try:
                        await self.zone(zone_id)
                        mode = await self.cf("GET", "/zones/" + zone_id + "/settings/ssl")
                        if mode.get("value") != "strict":
                            raise DomainError(
                                "cloudflare_ssl_required",
                                "Set this Cloudflare zone to Full (strict) SSL/TLS before enabling its app domains; MediaHub will not change the zone-wide mode",
                                409,
                            )
                        for row in rows:
                            await self.inspect_record(state, row)
                        await self.sync_rule(
                            state, zone_id, [row["hostname"] for row in rows], port
                        )
                        for row in rows:
                            await self.sync_record(state, row, address)
                            if row["id"] not in active_ids:
                                continue  # Keep DNS while the app is temporarily unavailable.
                            self.app_address(row)
                            certificate = certificates.get(row["id"], False)
                            probe = (
                                await self.probe(row["hostname"], row["id"])
                                if certificate and self.gateway.get("ready") is True
                                else {"reachable": False}
                            )
                            row.update(
                                certificateReady=certificate,
                                httpsVerified=probe["reachable"],
                                checkedAt=int(time.time()),
                                status="healthy"
                                if probe["reachable"]
                                else "configured"
                                if certificate
                                else "pending-certificate",
                                message="Public HTTPS reached this app through the Proton gateway"
                                if probe["reachable"]
                                else "DNS and Origin Rule configured; public HTTPS is not verified yet"
                                if certificate
                                else "DNS and Origin Rule configured; waiting for the gateway certificate",
                            )
                    except DomainError as error:
                        for row in rows:
                            row.update(
                                status="conflict" if "conflict" in error.code else "blocked",
                                message=error.message,
                                httpsVerified=False,
                            )
                        state["issues"].append(
                            {"id": zone_id, "code": error.code, "message": error.message}
                        )
                if state.get("plexPortManaged"):
                    try:
                        await self.plex_forwarding.apply(state, reply)
                    except DomainError as error:
                        state["plexPortStatus"] = {"ready": False, "message": error.message}
                state["checks"] = [
                    {
                        "id": "provider",
                        "state": "ready",
                        "message": "Fresh Proton public address and forwarded port verified",
                    },
                    {
                        "id": "https",
                        "state": "ready"
                        if all(row.get("httpsVerified") for row in active)
                        else "pending",
                        "message": "Public HTTPS is checked separately from DNS and gateway configuration",
                    },
                ]
            except DomainError as error:
                if error.code in {
                    "vpn_unavailable",
                    "vpn_gateway_rejected",
                    "vpn_integration_required",
                    "gateway_endpoint_pending",
                }:
                    self.gateway = {
                        **self.gateway,
                        "ready": False,
                        "providerReady": False,
                        "publicIp": None,
                        "publicPort": None,
                    }
                if state.get("plexPortEnabled"):
                    state["plexPortStatus"] = {"ready": False, "message": error.message}
                state["issues"].append({"code": error.code, "message": error.message})
                for row in state["routes"]:
                    if row.get("status") not in {"blocked", "conflict"}:
                        row.update(
                            status="pending-port"
                            if error.code == "gateway_endpoint_pending"
                            else "blocked",
                            message=error.message,
                            httpsVerified=False,
                        )
            except asyncio.CancelledError:
                state["issues"].append(
                    {
                        "code": "gateway_interrupted",
                        "message": "Gateway synchronization was interrupted; saved ownership will be checked on retry",
                    }
                )
                self.save(state)
                raise
            except Exception:
                state["issues"].append(
                    {
                        "code": "gateway_sync_failed",
                        "message": "Gateway synchronization could not finish; saved ownership was preserved for retry",
                    }
                )
                for row in state["routes"]:
                    row.update(
                        status="blocked",
                        httpsVerified=False,
                        message="Gateway synchronization could not be verified; retry after checking its status",
                    )
            self.save(state)
            return self.snapshot()

    async def poll(self):
        while True:
            await self.reconcile()
            await asyncio.sleep(30)

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task


def secure(request: Request, user=Depends(administrator)):
    if request.url.scheme != "https" and not services(request).config.dev_mode:
        raise DomainError("https_required", "Use HTTPS to configure VPN app domains", 403)
    return services(request).vpn_gateway


router = APIRouter(prefix="/vpn-gateway", dependencies=[Depends(secure)])


@router.get("")
async def status(request: Request):
    return result(await services(request).vpn_gateway.public())


@router.put("/credentials")
async def credentials(body: Credentials, request: Request):
    return result(await services(request).vpn_gateway.credentials(body))


@router.delete("/credentials")
async def disconnect(request: Request):
    return result(await services(request).vpn_gateway.disconnect())


@router.put("/config", status_code=202)
async def configure(body: GatewayConfig, request: Request):
    return result(await services(request).vpn_gateway.configure(body))


@router.put("/plex-port", status_code=202)
async def plex_port(body: PlexPortChoice, request: Request):
    return result(await services(request).vpn_gateway.configure_plex_port(body.enabled))


@router.post("/reconcile", status_code=202)
async def reconcile(request: Request):
    service = services(request).vpn_gateway
    service.schedule()
    return result(service.snapshot())


@router.put("/apps/{app_id}/domain")
async def app_domain(app_id: str, body: AppDomainChoice, request: Request):
    svc = services(request)
    app = svc.apps.get(app_id)
    if app["packageId"] != "org.mediahub.plex" or app["isMock"] or app["state"] in {"removing", "uninstalled"}:
        raise DomainError("app_unavailable", "Choose an installed Plex server", 409)
    service = svc.vpn_gateway
    state = service.state()
    if not state["enabled"] or not state.get("profileId"):
        raise DomainError("gateway_required", "Enable the shared gateway in MediaVPN before choosing an app domain", 409)
    routes = [{key: row[key] for key in ("id", "packageId", "zoneId", "label")} for row in state["routes"]]
    previous = next((row for row in routes if row["packageId"] == app["packageId"]), None)
    selected = {"packageId": app["packageId"], "zoneId": body.zoneId, "label": body.label}
    if previous:
        previous.update(selected)
    else:
        routes.append(selected)
    return result(await service.configure(GatewayConfig(enabled=True, profileId=state["profileId"], routes=routes, expectedRevision=state.get("revision", 0))))
