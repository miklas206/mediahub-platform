import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from mediahub import __version__
from mediahub.agent_client import AgentClient
from mediahub.agent_updates import AgentUpdates
from mediahub.agent_updates_api import router as agent_updates_router
from mediahub.api import router
from mediahub.apps.cloudflared import (
    register_cloudflared_app,
    should_register_cloudflared_app,
)
from mediahub.apps.framework import AppManager
from mediahub.apps.remote_registry import register_remote_apps
from mediahub.auth import AuthService
from mediahub.backups_api import router as backups_router
from mediahub.catalog import Catalog
from mediahub.cloudflare_tunnel import CloudflareTunnelMonitor
from mediahub.config import Config
from mediahub.db import connect, migrate
from mediahub.errors import DomainError
from mediahub.events import EventBus
from mediahub.fjordhub_api import router as fjordhub_router
from mediahub.fjordhub_deploy import FjordHubDeploy
from mediahub.hosts import HostRegistry
from mediahub.hosts_api import router as hosts_router
from mediahub.imports import ImportPlanner
from mediahub.integrations.api import router as integrations_router
from mediahub.integrations.service import IntegrationService
from mediahub.logging import request_id, setup_logging
from mediahub.phase2_api import router as phase2_router
from mediahub.platform_update_runtime import PlatformUpdateRuntime
from mediahub.release_credentials import GitHubReleaseCredentials
from mediahub.security_api import router as security_router
from mediahub.seedbox_rss_feeds import RSSFeeds
from mediahub.settings import SettingsService
from mediahub.setup import SetupService
from mediahub.storage import StorageManager
from mediahub.system import SystemService
from mediahub.update_monitor import UpdateMonitor

logger = logging.getLogger("mediahub.core")


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    if not config.dev_mode:
        from mediahub.runtime_security import protect_process_memory

        protect_process_memory()
    setup_logging(config.log_level)

    @asynccontextmanager
    async def lifespan(app):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            config.data_dir.chmod(0o700)
        migrate(config.database_url)
        engine, sessions = connect(config.database_url)
        events = EventBus(sessions)
        svc = SimpleNamespace(
            config=config,
            engine=engine,
            sessions=sessions,
            events=events,
            system=SystemService(config),
            settings=SettingsService(sessions),
        )
        svc.auth = AuthService(sessions, config, events)
        svc.storage = StorageManager(sessions, config, events)
        svc.apps = AppManager(sessions, events, config)
        svc.apps.initialize()
        svc.agent = AgentClient(config)
        svc.catalog = Catalog(config, sessions, svc.agent)
        svc.integrations = IntegrationService(config, sessions, events)
        svc.cloudflare_tunnel = CloudflareTunnelMonitor(config)
        svc.cloudflare_tunnel.configure(svc.catalog.configuration("org.mediahub.cloudflared"))
        svc.release_credentials = GitHubReleaseCredentials(config)
        svc.platform_update = PlatformUpdateRuntime(svc)
        svc.hosts = HostRegistry(svc)
        svc.agent_updates = AgentUpdates(svc)
        svc.rss_feeds = RSSFeeds(svc)
        svc.fjordhub_deploy = FjordHubDeploy(sessions)
        register_remote_apps(svc)
        if should_register_cloudflared_app(svc):
            register_cloudflared_app(svc)
        svc.updates = UpdateMonitor(svc)
        svc.imports = ImportPlanner(sessions, svc.agent, svc.apps)
        svc.snapshot = svc.system.status()
        app.state.services = svc
        svc.setup = SetupService(svc)
        events.record(
            "system.started", "core", "MediaHub Core started; host status collected separately"
        )
        logger.info("Core started; host status collected separately")

        async def collect():
            while True:
                await asyncio.sleep(config.sample_seconds)
                try:
                    svc.snapshot = svc.system.status()
                    events.publish("system.status", svc.snapshot)
                except Exception:
                    logger.error("System metrics temporarily unavailable")

        collector = asyncio.create_task(collect())

        async def collect_hosts():
            while True:
                try:
                    await svc.hosts.refresh()
                except Exception:
                    logger.error("Host status temporarily unavailable")
                await asyncio.sleep(15)

        host_collector = asyncio.create_task(collect_hosts())
        integration_collector = asyncio.create_task(svc.integrations.poll())
        update_collector = asyncio.create_task(svc.updates.poll())
        rss_collector = asyncio.create_task(svc.rss_feeds.poll())
        try:
            yield
        finally:
            collector.cancel()
            host_collector.cancel()
            integration_collector.cancel()
            update_collector.cancel()
            rss_collector.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await rss_collector
            with contextlib.suppress(asyncio.CancelledError):
                await update_collector
            with contextlib.suppress(asyncio.CancelledError):
                await integration_collector
            with contextlib.suppress(asyncio.CancelledError):
                await host_collector
            with contextlib.suppress(asyncio.CancelledError):
                await collector
            engine.dispose()

    app = FastAPI(
        title="MediaHub API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    hosts = sorted({urlsplit(origin).hostname for origin in config.origins})
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(config.origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-MediaHub-CSRF"],
    )

    def failure(code, message, status, rid=None):
        return JSONResponse(
            {
                "data": None,
                "error": {"code": code, "message": message},
                "metadata": {"requestId": rid or request_id.get(), "version": __version__},
            },
            status_code=status,
        )

    @app.middleware("http")
    async def security(request: Request, call_next):
        rid = str(uuid4())
        token = request_id.set(rid)
        try:
            origin = request.headers.get("origin")
            if (
                config.base_url.startswith("https://")
                and request.url.scheme != "https"
                and request.url.path.startswith("/api/")
                and request.url.path not in {"/api/v1/health", "/api/health"}
            ):
                # Reject before parsing credentials. Never redirect a sensitive POST.
                # ProxyHeadersMiddleware already validates the trusted proxy boundary.
                response = failure("https_required", "Use the configured HTTPS address", 403, rid)
            elif (
                request.method not in {"GET", "HEAD", "OPTIONS"}
                and origin
                and origin not in config.origins
            ):
                response = failure("origin_rejected", "Request origin is not allowed", 403, rid)
            else:
                try:
                    response = await call_next(request)
                except Exception:
                    logger.error("Request failed; internal details withheld")
                    response = failure(
                        "internal_error", "Service temporarily unavailable", 500, rid
                    )
            response.headers["X-Request-ID"] = rid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Frame-Options"] = "DENY"
            if request.url.path.startswith(
                "/api/"
            ) and "text/event-stream" not in response.headers.get("content-type", ""):
                response.headers["Cache-Control"] = "no-store"
            return response
        finally:
            request_id.reset(token)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return failure(error.code, error.message, error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # No input values: even validation failures must not echo passwords.
        fields = sorted({".".join(map(str, item["loc"])) for item in error.errors()})
        return failure("invalid_request", "Check these fields: " + ", ".join(fields), 422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return failure(
            "http_error",
            "Resource not found" if error.status_code == 404 else "Request rejected",
            error.status_code,
        )

    app.include_router(router, prefix="/api/v1")
    app.include_router(phase2_router, prefix="/api/v1")
    app.include_router(hosts_router, prefix="/api/v1")
    app.include_router(agent_updates_router, prefix="/api/v1")
    app.include_router(fjordhub_router, prefix="/api/v1")
    app.include_router(integrations_router, prefix="/api/v1")
    app.include_router(security_router, prefix="/api/v1")
    app.include_router(backups_router, prefix="/api/v1")
    app.include_router(router, prefix="/api", include_in_schema=False)

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        if path.startswith("api/"):
            raise DomainError("not_found", "API endpoint not found", 404)
        root = config.frontend_dir.resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise DomainError("not_found", "Resource not found", 404)
        if target.is_file():
            return FileResponse(target)
        if (root / "index.html").is_file():
            return FileResponse(root / "index.html")
        return failure(
            "frontend_not_built", "Build the frontend or open the Vite development server", 503
        )

    # Keep proxy trust at one layer, including in tests/alternate ASGI deployments.
    # Untrusted direct clients cannot spoof scheme or client IP using forwarded headers.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=config.trusted_proxies)
    return app
