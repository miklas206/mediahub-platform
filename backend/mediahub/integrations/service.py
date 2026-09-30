"""Optional read-only integrations, encrypted references and bounded async polling."""

import asyncio
import time
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import select

from mediahub.db import ExternalIntegration, now
from mediahub.errors import DomainError
from mediahub.integrations.fjordhub import FjordHubIntegrationProvider, validate_url
from mediahub.integrations.provider import IntegrationSnapshot
from mediahub.secret_store import SecretStore


class IntegrationService:
    def __init__(self, config, sessions, events):
        self.sessions, self.events = sessions, events
        self.store = SecretStore(config.data_dir / "private-records")
        self.provider_factory = FjordHubIntegrationProvider
        self.lock = asyncio.Lock()
        self.test_lock = asyncio.Lock()

    @staticmethod
    def public(row):
        return {
            "id": row.id,
            "provider": row.provider,
            "name": row.name,
            "baseUrl": row.base_url,
            "allowHttp": row.allow_http,
            "tokenConfigured": bool(row.secret_reference),
            "enabled": row.enabled,
            "snapshot": row.snapshot,
            "lastSuccessfulSync": row.last_success,
            "nextSync": row.next_sync,
        }

    def list(self):
        with self.sessions() as db:
            return [self.public(row) for row in db.scalars(select(ExternalIntegration))]

    @staticmethod
    def origin(value, allow_http):
        try:
            return validate_url(value, allow_http)
        except ValueError:
            raise DomainError(
                "invalid_integration_origin",
                "Use a private IP origin; HTTP requires explicit LAN-only consent",
                422,
            ) from None

    async def test(self, body):
        origin = self.origin(body.baseUrl, body.allowHttp)
        if self.test_lock.locked():
            raise DomainError("integration_busy", "A connection test is already running", 409)
        async with self.test_lock:
            client = self.provider_factory(
                origin, body.accessToken.get_secret_value(), allow_http=body.allowHttp
            )
            return asdict(await client.test())

    def save(self, body):
        origin = self.origin(body.baseUrl, body.allowHttp)
        token = body.accessToken.get_secret_value()
        if token in body.name or token in origin:
            raise DomainError(
                "invalid_integration_metadata", "Token must only be in its private field", 422
            )
        with self.sessions.begin() as db:
            if len(db.scalars(select(ExternalIntegration.id)).all()) >= 20:
                raise DomainError(
                    "integration_limit", "Maximum configured integrations reached", 409
                )
            reference = "external-" + uuid4().hex
            self.store.put(reference, token.encode())
            row = ExternalIntegration(
                provider="fjordhub",
                name=body.name,
                base_url=origin,
                allow_http=body.allowHttp,
                secret_reference=reference,
                enabled=True,
                snapshot={"status": "not_checked"},
            )
            db.add(row)
            db.flush()
            output = self.public(row)
        self.events.record("integration.configured", "FjordHub", "Read-only integration configured")
        return output

    async def refresh(self, identifier, *, automatic=False):
        if self.lock.locked():
            raise DomainError("integration_busy", "An integration refresh is already running", 409)
        async with self.lock:
            with self.sessions() as db:
                row = db.get(ExternalIntegration, identifier)
                if row is None:
                    raise DomainError("not_found", "Integration not found", 404)
                if not row.enabled or not row.secret_reference:
                    raise DomainError(
                        "integration_disconnected", "Integration is disconnected", 409
                    )
                if row.next_sync > time.time():
                    return self.public(row)
                reference, origin, allow_http = row.secret_reference, row.base_url, row.allow_http
                previous = row.snapshot
            try:
                token = self.store.get(reference).decode()
                client = self.provider_factory(origin, token, allow_http=allow_http)
                snapshot = await client.sync(cursor=previous.get("cursor"))
            except DomainError:
                snapshot = IntegrationSnapshot(status="credentials_unavailable")
            except Exception:
                snapshot = IntegrationSnapshot(status="invalid_response")
            with self.sessions.begin() as db:
                row = db.get(ExternalIntegration, identifier)
                # A disconnect during the network await must never re-enable access.
                if not row.enabled or row.secret_reference != reference:
                    return self.public(row)
                success = snapshot.status in {"online", "degraded"}
                row.snapshot = asdict(snapshot)
                if not success and row.last_success:
                    row.snapshot = {
                        **previous,
                        "status": snapshot.status,
                        "stale": True,
                        "failed_endpoint": snapshot.failed_endpoint,
                        "retry_after": snapshot.retry_after,
                    }
                row.failures = 0 if success else min(8, row.failures + 1)
                interval = 5 if "docker.resources.read" in snapshot.capabilities else 60
                delay = snapshot.retry_after or (
                    interval if success else min(3600, 30 * 2**row.failures)
                )
                row.next_sync = int(time.time() + delay)
                if success:
                    row.last_success = now()
                output = self.public(row)
            self.events.publish("integration.updated", {"id": identifier})
            if previous.get("status") != snapshot.status:
                self.events.record(
                    "integration.status",
                    "FjordHub",
                    "External integration status: " + snapshot.status,
                    "info" if success else "warning",
                )
            seen = {item.get("id") for item in previous.get("events", [])}
            for event in snapshot.events:
                if event.get("id") and event["id"] not in seen:
                    self.events.record(
                        "integration.external_event",
                        "FjordHub",
                        event.get("message", "External event"),
                        event.get("severity")
                        if event.get("severity") in {"info", "warning", "error"}
                        else "info",
                    )
            return output

    def disconnect(self, identifier):
        reference = None
        with self.sessions.begin() as db:
            row = db.get(ExternalIntegration, identifier)
            if row is None:
                raise DomainError("not_found", "Integration not found", 404)
            reference = row.secret_reference
            row.enabled, row.secret_reference = False, None
            row.snapshot = {"status": "disconnected"}
            output = self.public(row)
        if reference:
            self.store.delete(reference)
        self.events.record(
            "integration.disconnected", "FjordHub", "External integration disconnected"
        )
        return output

    async def poll(self):
        while True:
            await asyncio.sleep(1)
            for row in self.list():
                if row["enabled"] and row["nextSync"] <= time.time():
                    try:
                        await self.refresh(row["id"], automatic=True)
                    except Exception:
                        pass  # Optional provider cannot terminate Core or expose error details.
