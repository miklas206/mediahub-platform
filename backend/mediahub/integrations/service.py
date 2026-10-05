"""Optional read-only integrations, encrypted references and bounded async polling."""

import asyncio
import threading
import time
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

import httpx
from sqlalchemy import select

from mediahub.db import ExternalIntegration, Setting, now
from mediahub.errors import DomainError
from mediahub.integrations.fjordhub import FjordHubIntegrationProvider, validate_url
from mediahub.integrations.launch_urls import APP_ID, validate_launch_url
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
        self.environment_origin = (
            config.fjordhub_base_url
            if config.fjordhub_base_url and config.fjordhub_access_token
            else None
        )
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
    def removal_key(origin):
        return "integration.removed." + sha256(origin.encode()).hexdigest()

    @staticmethod
    def launch_key(identifier):
        return "integration.launch-urls." + identifier

    def launch_overrides(self, identifier):
        with self.sessions() as db:
            setting = db.scalar(select(Setting).where(Setting.key == self.launch_key(identifier)))
            return dict(setting.value) if setting else {}

    def set_launch_url(self, identifier, app_id, value):
        if not APP_ID.fullmatch(app_id):
            raise DomainError("invalid_app_id", "Invalid integration app identifier", 422)
        with self.persistence_lock, self.sessions.begin() as db:
            row = db.get(ExternalIntegration, identifier)
            if row is None or row.provider != "fjordhub":
                raise DomainError("not_found", "Integration not found", 404)
            key = self.launch_key(identifier)
            setting = db.scalar(select(Setting).where(Setting.key == key))
            overrides = dict(setting.value) if setting else {}
            known = any(
                app.get("id") == app_id
                for app in (row.snapshot or {}).get("apps", [])
                if isinstance(app, dict)
            )
            known = known or app_id in ((row.snapshot or {}).get("app_info") or {})
            if value is not None:
                if not known:
                    raise DomainError("not_found", "Integration app not found", 404)
                token = (
                    self.store.get(row.secret_reference).decode() if row.secret_reference else ""
                )
                try:
                    value = validate_launch_url(value, row.base_url, row.allow_http, token)
                except ValueError:
                    raise DomainError(
                        "invalid_launch_url",
                        "Use a credential-free same-host HTTP(S) app URL without query or fragment; HTTP requires LAN consent",
                        422,
                    ) from None
                overrides[app_id] = value
            else:
                # Clearing remains possible when an app vanishes from a later snapshot.
                overrides.pop(app_id, None)
            if overrides:
                if setting:
                    setting.value = overrides
                else:
                    db.add(Setting(key=key, value=overrides))
            elif setting:
                db.delete(setting)
        self.events.publish("integration.updated", {"id": identifier})
        return {"id": identifier, "appLaunchOverrides": overrides}

    def public(self, row):
        return {
            "id": row.id,
            "provider": row.provider,
            "name": row.name,
            "baseUrl": row.base_url,
            "allowHttp": row.allow_http,
            "tokenConfigured": bool(row.secret_reference),
            "enabled": row.enabled,
            "managedByEnvironment": row.base_url == self.environment_origin,
            "snapshot": row.snapshot,
            "appLaunchOverrides": self.launch_overrides(row.id),
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
            if row and any(token in value for value in self.launch_overrides(row.id).values()):
                raise DomainError(
                    "invalid_integration_metadata", "Token must only be in its private field", 422
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
            marker = db.scalar(select(Setting).where(Setting.key == self.removal_key(origin)))
            if marker:
                db.delete(marker)
            db.add(row)
            db.flush()
            output = self.public(row)
        self.events.record("integration.configured", "FjordHub", "Read-only integration configured")
        if old_reference:
            self.store.delete(old_reference)
        return output

    def register_detected(self, origin, allow_http, name="FjordHub", *, reconnect=False):
        with self.persistence_lock, self.sessions.begin() as db:
            marker = db.scalar(select(Setting).where(Setting.key == self.removal_key(origin)))
            if marker:
                if not reconnect:
                    raise DomainError(
                        "integration_removed", "Integration was permanently removed", 409
                    )
                db.delete(marker)
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
        with self.sessions() as db:
            removed_at_start = db.scalar(
                select(Setting.id).where(Setting.key == self.removal_key(origin))
            )
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
        with self.persistence_lock:
            with self.sessions() as db:
                removed = db.scalar(
                    select(Setting.id).where(Setting.key == self.removal_key(origin))
                )
            if removed and removed != removed_at_start:
                raise DomainError("integration_removed", "Integration was permanently removed", 409)
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
                    normalized = self.origin(origin, origin.startswith("http://"))
                    with self.sessions() as db:
                        if db.scalar(
                            select(Setting).where(Setting.key == self.removal_key(normalized))
                        ):
                            continue
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
            with self.persistence_lock, self.sessions.begin() as db:
                row = db.get(ExternalIntegration, identifier)
                # Removal/disconnect during the network await wins over late snapshots.
                if row is None:
                    raise DomainError("not_found", "Integration not found", 404)
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
                if snapshot.app_info is None:
                    row.snapshot["app_info"] = previous.get("app_info")
                    row.snapshot["app_info_stale"] = True
                if snapshot.updates is None:
                    row.snapshot["updates"] = previous.get("updates")
                else:
                    row.snapshot["updates"] = {
                        **{
                            key: {**value, "stale": True}
                            for key, value in (previous.get("updates") or {}).items()
                            if key not in snapshot.updates
                        },
                        **snapshot.updates,
                    }
                # Dedicated update polling owns its schedule; resource refreshes
                # cannot erase accepted starts or turn stale status into success.
                for key in ("updates_error", "updates_polled_at", "updates_next_poll"):
                    if key in previous:
                        row.snapshot[key] = previous[key]
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

    def update_view(self, row):
        snapshot = row.snapshot or {}
        return {
            "app_info": snapshot.get("app_info") or {},
            "app_info_stale": snapshot.get("app_info_stale", True),
            "updates": snapshot.get("updates") or {},
            "error": snapshot.get("updates_error"),
            "polled_at": snapshot.get("updates_polled_at"),
        }

    async def updates(self, identifier, app_id=None, action=None):
        from mediahub.integrations.fjordhub import ProviderFailure
        from mediahub.integrations.fjordhub_metadata import APP_ID

        if app_id is not None and not APP_ID.fullmatch(app_id):
            raise DomainError("invalid_app_id", "Ugyldigt app-ID", 422)
        if self.lock.locked():
            if action:
                raise DomainError(
                    "integration_busy", "FjordHub behandles allerede. Prøv igen.", 409
                )
            with self.sessions() as db:
                row = db.get(ExternalIntegration, identifier)
                if row is None:
                    raise DomainError("not_found", "Integration ikke fundet", 404)
                return self.update_view(row)
        async with self.lock:
            with self.sessions() as db:
                row = db.get(ExternalIntegration, identifier)
                if row is None or not row.enabled or not row.secret_reference:
                    raise DomainError("not_found", "Integration er ikke tilsluttet", 404)
                reference, origin, allow_http = row.secret_reference, row.base_url, row.allow_http
                previous = dict(row.snapshot or {})
                running = any(s.get("running") for s in (previous.get("updates") or {}).values())
                if not action and time.time() < previous.get("updates_next_poll", 0):
                    return self.update_view(row)
            client = self.provider_factory(
                origin, self.store.get(reference).decode(), allow_http=allow_http
            )
            output = dict(previous)
            error = None
            try:
                info = await client.metadata()
                output.update(app_info=info, app_info_stale=False)
                statuses = await client.update_poll()
                # An omitted app is not a confirmed update outcome (for example
                # token permissions changed while its updater was restarting).
                statuses = {
                    **{
                        key: {**value, "stale": True}
                        for key, value in (previous.get("updates") or {}).items()
                        if key not in statuses
                    },
                    **statuses,
                }
                output.update(updates=statuses, updates_error=None, updates_polled_at=now())
                if action:
                    item = info.get(app_id)
                    if not item or not item.get("installed"):
                        raise DomainError(
                            "not_found", "Appen er ikke installeret eller delt med tokenet", 404
                        )
                    if not item["permissions"]["updates"]:
                        raise DomainError(
                            "missing_permission",
                            "Tokenet har ikke opdateringsadgang til appen",
                            403,
                        )
                    status = statuses.get(app_id)
                    if action == "start" and (
                        not status or not status.get("ok") or status.get("stale")
                    ):
                        raise DomainError(
                            "unknown_update_status", "Opdateringsstatus er ikke bekræftet", 409
                        )
                    if (status and status.get("running")) or (
                        action == "start" and not status.get("update_available")
                    ):
                        raise DomainError(
                            "update_conflict",
                            "Appen opdateres allerede eller har ingen bekræftet opdatering",
                            409,
                        )
                    # Persist uncertain in-progress state before sending start: a restart or
                    # timeout after acceptance must never invite an automatic retry.
                    if action == "start":
                        pending = {**status, "running": True, "state": "updating", "stale": True}
                        with self.persistence_lock, self.sessions.begin() as db:
                            row = db.get(ExternalIntegration, identifier)
                            if row is None or not row.enabled or row.secret_reference != reference:
                                raise DomainError(
                                    "integration_changed", "Integrationen blev ændret", 409
                                )
                            row.snapshot = {**output, "updates": {**statuses, app_id: pending}}
                        output["updates"] = {**statuses, app_id: pending}
                    result = await client.update_action(app_id, action)
                    output["updates"] = {**statuses, app_id: result}
            except (ProviderFailure, httpx.HTTPError, TimeoutError) as exc:
                code = exc.status if isinstance(exc, ProviderFailure) else "timeout"
                messages = {
                    "authentication_failed": "Ugyldigt eller udløbet FjordHub-token (401).",
                    "lan_access_denied": "FjordHub afviste adgang eller rettighed (403).",
                    "api_incompatible": "App eller API findes ikke; ældre FjordHub kan mangle støtte (404).",
                    "update_conflict": "FjordHub er optaget eller blokeret af filflytning (409).",
                }
                output["updates_error"] = messages.get(
                    code,
                    "FjordHub svarer ikke. Sidste status bevares; en start er ikke bekræftet færdig.",
                )
                output["app_info_stale"] = True
                output["updates"] = {
                    key: {**value, "stale": True}
                    for key, value in (output.get("updates") or {}).items()
                }
                if action:
                    error = DomainError(
                        code,
                        output["updates_error"],
                        {
                            "authentication_failed": 401,
                            "lan_access_denied": 403,
                            "api_incompatible": 404,
                            "update_conflict": 409,
                        }.get(code, 503),
                    )
            except DomainError as exc:
                error = exc
            running = any(s.get("running") for s in (output.get("updates") or {}).values())
            output["updates_next_poll"] = time.time() + (5 if running else 45)
            with self.persistence_lock, self.sessions.begin() as db:
                row = db.get(ExternalIntegration, identifier)
                if row is None or not row.enabled or row.secret_reference != reference:
                    raise DomainError("integration_changed", "Integrationen blev ændret", 409)
                row.snapshot = output
                view = self.update_view(row)
            self.events.publish("integration.updated", {"id": identifier})
            if error:
                raise error
            return view

    async def icon(self, identifier, app_id):
        from mediahub.integrations.fjordhub import ProviderFailure
        from mediahub.integrations.fjordhub_metadata import APP_ID, icon_path

        if not APP_ID.fullmatch(app_id):
            raise DomainError("not_found", "Ikon ikke fundet", 404)
        with self.sessions() as db:
            row = db.get(ExternalIntegration, identifier)
            if row is None or not row.enabled or not row.secret_reference:
                raise DomainError("not_found", "Ikon ikke fundet", 404)
            path = (row.snapshot.get("app_info") or {}).get(app_id, {}).get("icon_path")
            reference, origin, allow_http = row.secret_reference, row.base_url, row.allow_http
        if not path:
            raise DomainError("not_found", "Ikon ikke fundet", 404)
        try:
            client = self.provider_factory(
                origin, self.store.get(reference).decode(), allow_http=allow_http
            )
            if icon_path(origin + path, client) != path:
                raise ProviderFailure("invalid_response")
            async with httpx.AsyncClient(
                base_url=origin,
                headers={"Authorization": "Bearer " + client._access_token},
                timeout=5,
                follow_redirects=False,
                trust_env=False,
                transport=client._transport,
            ) as transport:
                async with transport.stream("GET", path) as response:
                    kind = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if response.status_code != 200 or kind not in {
                        "image/png",
                        "image/jpeg",
                        "image/webp",
                    }:
                        raise ProviderFailure("invalid_response")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            raise ProviderFailure("invalid_response")
                    signatures = {
                        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
                        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
                        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
                    }
                    if not signatures[kind]:
                        raise ProviderFailure("invalid_response")
            with self.sessions() as db:
                row = db.get(ExternalIntegration, identifier)
                if row is None or not row.enabled or row.secret_reference != reference:
                    raise ProviderFailure("invalid_response")
            return bytes(data), kind
        except (ProviderFailure, httpx.HTTPError, TimeoutError, DomainError, ValueError):
            raise DomainError("not_found", "Ikon ikke tilgængeligt", 404) from None

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

    def remove(self, identifier):
        with self.persistence_lock, self.sessions.begin() as db:
            row = db.get(ExternalIntegration, identifier)
            if row is None:
                raise DomainError("not_found", "Integration not found", 404)
            if row.enabled:
                raise DomainError(
                    "integration_active",
                    "Disconnect the integration before permanently removing it.",
                    409,
                )
            if row.base_url == self.environment_origin:
                raise DomainError(
                    "integration_environment_managed",
                    "Remove FJORDHUB_BASE_URL and FJORDHUB_ACCESS_TOKEN (including MEDIAHUB_ aliases) from the server environment and restart MediaHub before removing this integration.",
                    409,
                )
            reference = row.secret_reference
            if reference:
                shared = db.scalar(
                    select(ExternalIntegration.id).where(
                        ExternalIntegration.id != identifier,
                        ExternalIntegration.secret_reference == reference,
                    )
                )
                if not shared and reference.startswith("external-"):
                    self.store.delete(reference)
            key = self.removal_key(row.base_url)
            if db.scalar(select(Setting).where(Setting.key == key)) is None:
                # Durable opt-out also fences discovery already awaiting the network.
                db.add(Setting(key=key, value={}))
            launch_setting = db.scalar(
                select(Setting).where(Setting.key == self.launch_key(identifier))
            )
            if launch_setting:
                db.delete(launch_setting)
            db.delete(row)
        self.events.publish("integration.removed", {"id": identifier})
        self.events.record(
            "integration.removed",
            "FjordHub",
            "External integration permanently removed from MediaHub",
        )
        return {"id": identifier, "removed": True}

    def disconnect(self, identifier):
        reference = None
        with self.persistence_lock, self.sessions.begin() as db:
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
