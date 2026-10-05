"""Optional read-only integrations, encrypted references and bounded async polling."""

import asyncio
import threading
import time
from dataclasses import asdict
from uuid import uuid4

import httpx
from sqlalchemy import select

from mediahub.db import ExternalIntegration, Setting, now
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
        self.default_origin = config.fjordhub_url
        self.persistence_lock = threading.RLock()
        if config.fjordhub_base_url and config.fjordhub_access_token:
            from types import SimpleNamespace

            origin = config.fjordhub_base_url
            with self.sessions() as db:
                existing = db.scalar(
                    select(ExternalIntegration).where(
                        ExternalIntegration.provider == "fjordhub",
                        ExternalIntegration.base_url == origin,
                    )
                )
            unchanged = False
            if existing and existing.secret_reference:
                try:
                    unchanged = self.store.get(existing.secret_reference).decode() == (
                        config.fjordhub_access_token.get_secret_value()
                    )
                except (DomainError, UnicodeError):
                    pass
            # Preserve snapshots and deliberate disconnects across restarts.
            if (existing is None or existing.enabled) and not unchanged:
                self.save(
                    SimpleNamespace(
                        name="FjordHub",
                        baseUrl=origin,
                        accessToken=config.fjordhub_access_token,
                        allowHttp=origin.startswith("http://"),
                    )
                )

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
        with self.persistence_lock, self.sessions.begin() as db:
            row = db.scalar(
                select(ExternalIntegration).where(
                    ExternalIntegration.provider == "fjordhub",
                    ExternalIntegration.base_url == origin,
                )
            )
            if row is None and len(db.scalars(select(ExternalIntegration.id)).all()) >= 20:
                raise DomainError(
                    "integration_limit", "Maximum configured integrations reached", 409
                )
            reference = "external-" + uuid4().hex
            self.store.put(reference, token.encode())
            old_reference = row.secret_reference if row else None
            if row is None:
                row = ExternalIntegration(
                    provider="fjordhub",
                    name=body.name,
                    base_url=origin,
                    allow_http=body.allowHttp,
                    secret_reference=reference,
                    enabled=True,
                    snapshot={"status": "not_checked"},
                )
            else:
                row.name, row.allow_http, row.secret_reference = (
                    body.name,
                    body.allowHttp,
                    reference,
                )
                row.enabled, row.snapshot, row.next_sync = True, {"status": "not_checked"}, 0
            db.add(row)
            db.flush()
            output = self.public(row)
        self.events.record("integration.configured", "FjordHub", "Read-only integration configured")
        if old_reference:
            self.store.delete(old_reference)
        return output

    def register_detected(self, origin, allow_http, name="FjordHub", *, reconnect=False):
        with self.persistence_lock, self.sessions.begin() as db:
            row = db.scalar(
                select(ExternalIntegration).where(
                    ExternalIntegration.provider == "fjordhub",
                    ExternalIntegration.base_url == origin,
                )
            )
            if row is None:
                if len(db.scalars(select(ExternalIntegration.id)).all()) >= 20:
                    raise DomainError(
                        "integration_limit", "Maximum configured integrations reached", 409
                    )
                row = ExternalIntegration(
                    provider="fjordhub",
                    name=name,
                    base_url=origin,
                    allow_http=allow_http,
                    enabled=True,
                    snapshot={"status": "detected"},
                )
                db.add(row)
                db.flush()
            elif reconnect and not row.enabled:
                row.enabled, row.allow_http, row.name = True, allow_http, name
                row.snapshot, row.next_sync = {"status": "detected"}, 0
            # Background discovery must not undo an explicit disconnect or replace credentials.
            return self.public(row)

    async def detect(self, body, *, reconnect=False):
        origin = self.origin(body.baseUrl, body.allowHttp)
        try:
            async with (
                asyncio.timeout(15),
                httpx.AsyncClient(
                    base_url=origin, timeout=5, trust_env=False, follow_redirects=False
                ) as client,
            ):
                try:
                    # This combination identifies FjordHub, rather than an arbitrary healthy HTTP service.
                    async with client.stream("GET", "/api/health") as response:
                        if response.status_code != 200:
                            raise ValueError()
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 4096:
                                raise ValueError()
                        import json

                        health = json.loads(data)
                        if health.get("status") != "ok" or type(health.get("docker")) is not bool:
                            raise ValueError()
                    async with client.stream("GET", "/api/integrations/v1/resources") as response:
                        if (
                            response.status_code != 401
                            or response.headers.get("www-authenticate", "").lower() != "bearer"
                        ):
                            raise ValueError()
                except (httpx.HTTPError, ValueError, AttributeError):
                    raise DomainError(
                        "fjordhub_not_detected",
                        "FjordHub could not be verified at this LAN address",
                        422,
                    ) from None
        except TimeoutError:
            raise DomainError(
                "fjordhub_not_detected", "FjordHub could not be verified at this LAN address", 422
            ) from None
        return self.register_detected(
            origin, body.allowHttp, getattr(body, "name", "FjordHub"), reconnect=reconnect
        )

    async def discover_known(self):
        origins = [self.default_origin] if self.default_origin else []
        with self.sessions() as db:
            job = db.scalar(
                select(Setting)
                .where(Setting.key.startswith("fjordhub.deployment."))
                .order_by(Setting.created_at.desc())
                .limit(1)
            )
            if job and job.value.get("uninstall", {}).get("state") != "removed":
                origins += [
                    line.split("=", 1)[1]
                    for line in job.value.get("logs", [])
                    if line.startswith("MEDIAHUB_FJORDHUB_URL=")
                ][-1:]
        known = {row["baseUrl"] for row in self.list()}
        from types import SimpleNamespace

        for origin in origins:
            if origin not in known:
                try:
                    await self.detect(
                        SimpleNamespace(baseUrl=origin, allowHttp=origin.startswith("http://"))
                    )
                except Exception:
                    pass

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
                if (
                    previous.get("pairingPending")
                    and time.time() < previous.get("pairingDeadline", 0)
                    and snapshot.status == "authentication_failed"
                ):
                    snapshot.status = "pending_setup"
                success = snapshot.status in {"online", "degraded"}
                row.snapshot = asdict(snapshot)
                if snapshot.status == "pending_setup":
                    row.snapshot["pairingPending"] = True
                    row.snapshot["pairingDeadline"] = previous["pairingDeadline"]
                if not success and row.last_success:
                    row.snapshot = {
                        **previous,
                        "status": snapshot.status,
                        "stale": True,
                        "failed_endpoint": snapshot.failed_endpoint,
                        "retry_after": snapshot.retry_after,
                    }
                app = snapshot.fjordflix
                old_app = previous.get("fjordflix")
                if app is None and not success and old_app and old_app.get("ok"):
                    row.snapshot["fjordflix"] = {
                        **old_app,
                        "stale": True,
                        "error": "FjordHub connection interrupted.",
                    }
                elif app and not app.get("ok") and old_app and old_app.get("ok"):
                    row.snapshot["fjordflix"] = {
                        **old_app,
                        "stale": True,
                        "error": app["error"],
                        "status": app["status"],
                    }
                else:
                    row.snapshot["fjordflix"] = app
                row.failures = 0 if success else min(8, row.failures + 1)
                interval = 10 if "docker.resources.read" in snapshot.capabilities else 60
                delay = snapshot.retry_after or (
                    interval if success else min(3600, 30 * 2**row.failures)
                )
                if snapshot.status == "pending_setup":
                    delay = 60
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

    async def poster(self, identifier, movie_id):
        from mediahub.integrations.fjordflix import fetch_poster
        from mediahub.integrations.fjordhub import ProviderFailure

        with self.sessions() as db:
            row = db.get(ExternalIntegration, identifier)
            if row is None or not row.enabled or not row.secret_reference:
                raise DomainError("not_found", "Poster unavailable", 404)
            reference, origin, allow_http = row.secret_reference, row.base_url, row.allow_http
        try:
            token = self.store.get(reference).decode()
            client = self.provider_factory(origin, token, allow_http=allow_http)
            async with asyncio.timeout(8):
                data = await fetch_poster(client, movie_id)
            with self.sessions() as db:
                row = db.get(ExternalIntegration, identifier)
                if row is None or not row.enabled or row.secret_reference != reference:
                    raise DomainError("not_found", "Poster unavailable", 404)
            return data
        except (ProviderFailure, httpx.HTTPError, TimeoutError, DomainError, ValueError):
            raise DomainError("poster_unavailable", "Poster unavailable", 404) from None

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
        discovery = 0
        while True:
            await asyncio.sleep(1)
            if time.monotonic() >= discovery:
                await self.discover_known()
                discovery = time.monotonic() + 60
            for row in self.list():
                if row["enabled"] and row["tokenConfigured"] and row["nextSync"] <= time.time():
                    try:
                        await self.refresh(row["id"], automatic=True)
                    except Exception:
                        pass  # Optional provider cannot terminate Core or expose error details.
