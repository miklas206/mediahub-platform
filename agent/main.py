import asyncio
import contextlib
import hmac
import os
import platform
import re
import secrets
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
import psutil
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from mediahub.apps.manifest import DeviceRequirement
from mediahub.apps.plex import PlexInstallation, PlexInstallRequest
from mediahub.apps.seedbox import SeedboxInstallation
from mediahub.apps.seedbox_daily import AddTorrent, TorrentAction, TorrentRetention, VPNLocation
from mediahub.apps.seedbox_wizard import (
    ClientImport,
    VPNImport,
    WizardAdvance,
    WizardConfiguration,
    WizardExecute,
)
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError
from mediahub.path_policy import DirectoryPolicy
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent.app_backups import AppBackups
from agent.devices import device_report
from agent.discovery import discovery_report
from agent.fixtures import containers
from agent.plex_control import PlexControl
from agent.plex_runtime import PlexRuntime
from agent.seedbox_control import SeedboxControl
from agent.seedbox_install import PrepareSeedbox, SeedboxInstaller
from agent.seedbox_status import SeedboxStatus
from agent.seedbox_torrents import TorrentService
from agent.seedbox_workflow import SeedboxWorkflow
from agent.uploads import UploadSessions
from agent.vpn_locations import LocationService


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIAHUB_AGENT_", extra="ignore", env_file=".env")
    state_dir: Path = Path(".agent")
    token_file: Path = Path(".agent/token")
    storage_roots: list[Path] = []
    create_enabled: bool = False
    docker_socket: Path | None = None
    dev_mode: bool = False
    fixtures: bool = False
    listen_host: str = "127.0.0.1"
    port: int = Field(default=18767, ge=1024, le=65535)
    host_os_release: Path | None = None
    tls_cert: Path | None = None
    tls_key: Path | None = None
    usb_sysfs_root: Path | None = None
    block_sysfs_root: Path | None = None
    device_snapshot_file: Path | None = None
    required_devices: list[DeviceRequirement] = []
    device_selectors: dict[str, dict[str, str]] = {}
    seedbox_policy_file: Path | None = None
    plex_policy_file: Path | None = None
    plex_install_policy_file: Path | None = None

    @model_validator(mode="after")
    def validate_tls(self):
        if bool(self.tls_cert) != bool(self.tls_key):
            raise ValueError("Agent TLS requires both certificate and key")
        return self


class PlexVPNImport(StrictModel):
    vpnConfig: SecretStr = Field(exclude=True, min_length=100, max_length=65536)


def initialize(config: AgentConfig):
    config.state_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        config.state_dir.chmod(0o700)
    if not config.token_file.exists():
        config.token_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(config.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(48))
    if not config.storage_roots:
        (config.state_dir / "storage-sandbox").mkdir(exist_ok=True)


def command_version(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        match = re.search(r"\d+\.\d+\.\d+", result.stdout)
        return match.group(0) if match and result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class AgentRuntime:
    def __init__(self, config):
        self.config = config

    async def docker_get(self, path):
        if not self.config.docker_socket:
            raise DomainError(
                "runtime_unavailable", "Docker socket has not been explicitly configured", 503
            )
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=str(self.config.docker_socket)),
                base_url="http://docker",
                timeout=4,
                trust_env=False,
            ) as client:
                response = await client.get(path)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError):
            raise DomainError("runtime_unavailable", "Docker runtime is unavailable", 503) from None

    async def status(self):
        docker = shutil.which("docker")
        client_version = command_version([docker, "--version"]) if docker else None
        compose_version = (
            command_version([docker, "compose", "version", "--short"]) if docker else None
        )
        engine_version = None
        if self.config.docker_socket:
            try:
                engine_version = (await self.docker_get("/version")).get("Version")
            except DomainError:
                pass
        return {
            "available": engine_version is not None,
            "version": engine_version,
            "clientVersion": client_version,
            "composeAvailable": compose_version is not None,
            "composeVersion": compose_version,
            "operations": "read-only",
        }

    async def discover(self):
        if self.config.fixtures:
            if not self.config.dev_mode:
                raise DomainError("fixtures_disabled", "Fixtures require development mode", 403)
            return discovery_report(containers(), fixture=True)
        listing = await self.docker_get("/containers/json?all=1")
        results = []
        for item in listing[:200]:
            identifier = item.get("Id", "")
            if re.fullmatch("[a-f0-9]{64}", identifier):
                results.append(await self.docker_get(f"/containers/{identifier}/json"))
        return discovery_report(results)


class DirectoryRequest(StrictModel):
    path: str = Field(min_length=1, max_length=4096)


class CreateRequest(DirectoryRequest):
    confirmed_path: str


class UploadRequest(StrictModel):
    root: str = Field(min_length=1, max_length=4096)
    path: str = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0, le=512 * 1024**3)


class RemoveRuntimeRequest(StrictModel):
    confirmedInstallationId: str = Field(min_length=1, max_length=80)


class AppBackupRequest(StrictModel):
    password: SecretStr = Field(min_length=16, max_length=256)


def create_agent(config: AgentConfig | None = None):
    config = config or AgentConfig()
    if not config.dev_mode:
        from mediahub.runtime_security import protect_process_memory

        protect_process_memory()
    # Startup does not invent trust. Explicit agent-init must provision its token first.
    expected = config.token_file.read_text().strip()
    if len(expected) < 40:
        raise RuntimeError("Agent token must be provisioned before startup")
    policy = DirectoryPolicy(
        config.storage_roots or [(config.state_dir / "storage-sandbox").resolve()],
        config.create_enabled,
    )
    runtime = AgentRuntime(config)
    uploads = UploadSessions(policy, config.state_dir / "uploads")
    seedbox = SeedboxInstaller(config.seedbox_policy_file)
    seedbox_status = SeedboxStatus(seedbox, config.docker_socket)

    def devices():
        return device_report(
            config.usb_sysfs_root,
            config.block_sysfs_root,
            config.required_devices,
            config.device_selectors,
            config.device_snapshot_file,
        )

    control = SeedboxControl(seedbox, config.docker_socket, devices, seedbox_status)
    workflow = SeedboxWorkflow(control)
    torrents = TorrentService(control)
    locations = LocationService(control)
    plex = PlexControl(config.plex_policy_file, config.docker_socket)
    plex_runtime = PlexRuntime(plex, config.plex_install_policy_file, config.state_dir)
    if config.plex_install_policy_file:
        plex.runtime = plex_runtime
    backups = AppBackups(plex, control)

    @asynccontextmanager
    async def lifespan(app):
        cleanup = asyncio.create_task(uploads.cleanup())
        torrent_cleanup = (
            asyncio.create_task(torrents.retention.poll()) if config.seedbox_policy_file else None
        )
        if config.seedbox_policy_file:
            control.monitor_task = asyncio.create_task(control.monitor())
        if config.plex_policy_file:
            plex.monitor_task = asyncio.create_task(plex.monitor())
        yield
        if torrent_cleanup:
            torrent_cleanup.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await torrent_cleanup
        await plex.close()
        await control.close()
        cleanup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup

    async def authorize(request: Request):
        provided = request.headers.get("authorization", "")
        if not hmac.compare_digest(provided, "Bearer " + expected):
            raise DomainError("unauthorized", "Agent authentication required", 401)

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(authorize)],
        lifespan=lifespan,
    )

    @app.exception_handler(DomainError)
    async def error_handler(request, error):
        return JSONResponse(
            {"code": error.code, "message": error.message}, status_code=error.status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic hide_input_in_errors affects repr, not FastAPI's default JSON.
        # Never return request fragments, including passwords, on invalid input.
        return JSONResponse(
            {"code": "invalid_request", "message": "Request validation failed"}, status_code=422
        )

    @app.get("/v1/health")
    async def health():
        return {"status": "healthy"}

    @app.get("/v1/version")
    async def version():
        from mediahub import __version__

        return {
            "version": __version__,
            "protocolVersion": 1,
            "sourceCommit": os.environ.get("MEDIAHUB_SOURCE_COMMIT"),
        }

    @app.get("/v1/status")
    async def status():
        storage = []
        for root in policy.roots:
            try:
                storage.append(policy.inspect(str(root)))
            except DomainError as error:
                storage.append({"path": str(root), "available": False, "error": error.code})
        host = {}
        try:
            info = await runtime.docker_get("/info")
            host = {
                "hostname": info.get("Name"),
                "cores": info.get("NCPU"),
                "ramBytes": info.get("MemTotal"),
                "metricsScope": "docker-host",
            }
        except DomainError:
            pass
        os_name = platform.system()
        if config.host_os_release:
            try:
                values = dict(
                    line.split("=", 1)
                    for line in config.host_os_release.read_text().splitlines()
                    if "=" in line
                )
                os_name = values.get("PRETTY_NAME", os_name).strip('"')
            except OSError:
                pass
        return {
            "version": "0.4.3",
            "protocolVersion": 1,
            "hostname": platform.node(),
            "os": os_name,
            "architecture": platform.machine(),
            "cores": psutil.cpu_count(),
            "ramBytes": psutil.virtual_memory().total,
            "docker": await runtime.status(),
            "createEnabled": config.create_enabled,
            "fixtureMode": config.dev_mode and config.fixtures,
            "capabilities": ["runtime.inspect", "storage.inspect"]
            + (["storage.create"] if config.create_enabled else []),
            "storage": storage,
            "devices": device_report(
                config.usb_sysfs_root,
                config.block_sysfs_root,
                config.required_devices,
                config.device_selectors,
                config.device_snapshot_file,
            ),
            **host,
        }

    @app.get("/v1/discovery")
    async def discover():
        return await runtime.discover()

    @app.post("/v1/seedbox/plan")
    async def seedbox_plan(body: SeedboxInstallation):
        plan = seedbox.plan(body)
        engine, inventory = await runtime.status(), devices()
        plan["capabilities"] = {
            "dockerAvailable": engine["available"],
            "deviceHealth": inventory["health"],
        }
        if not engine["available"]:
            plan["blockers"].append("Docker runtime is unavailable")
        if inventory["health"] != "healthy":
            plan["blockers"].append("Required devices are not verified healthy")
        return plan

    async def secure_workflow(request: Request):
        if request.url.scheme != "https":
            raise DomainError(
                "https_required", "Installation and credentials require verified HTTPS", 403
            )

    @app.get("/v1/seedbox/wizard")
    async def wizard_status():
        return workflow.public()

    @app.get("/v1/plex/status")
    async def plex_status():
        return await plex.status()

    @app.get("/v1/plex/install-options")
    async def plex_install_options():
        return await plex_runtime.options()

    @app.post("/v1/plex/install-plan", dependencies=[Depends(secure_workflow)])
    async def plex_install_plan(body: PlexInstallation):
        return await plex_runtime.plan(body)

    @app.post("/v1/plex/install", dependencies=[Depends(secure_workflow)], status_code=202)
    async def plex_install(body: PlexInstallRequest):
        return await plex_runtime.install(body)

    @app.post("/v1/plex/actions/{action}", dependencies=[Depends(secure_workflow)])
    async def plex_action(action: str):
        return await plex.action(action)

    @app.post("/v1/plex/vpn/enable", dependencies=[Depends(secure_workflow)], status_code=202)
    async def plex_vpn_enable(body: PlexVPNImport):
        return await plex_runtime.enable_vpn(body.vpnConfig.get_secret_value().encode())

    @app.get("/v1/plex/logs")
    async def plex_logs():
        policy = plex.policy()
        return {
            "entries": [
                {**entry, "hostId": policy.hostId, "app": "org.mediahub.plex"}
                for entry in plex.events[-100:]
            ]
        }

    @app.post("/v1/plex/update-check", dependencies=[Depends(secure_workflow)])
    async def plex_update_check():
        return await plex.update_check()

    @app.post("/v1/plex/update", dependencies=[Depends(secure_workflow)], status_code=202)
    async def plex_update():
        return await plex_runtime.update()

    @app.post("/v1/plex/rollback", dependencies=[Depends(secure_workflow)])
    async def plex_rollback():
        return await plex_runtime.rollback()

    @app.post("/v1/backups/{application}/export", dependencies=[Depends(secure_workflow)])
    async def app_backup(application: Literal["plex", "seedbox"], body: AppBackupRequest):
        return await backups.export(application, body.password.get_secret_value())

    @app.get("/v1/seedbox/torrents", dependencies=[Depends(secure_workflow)])
    async def torrent_list():
        return await torrents.list()

    @app.post("/v1/seedbox/torrents/add", dependencies=[Depends(secure_workflow)])
    async def torrent_add(body: AddTorrent):
        return await torrents.add(body)

    @app.post("/v1/seedbox/torrents/action", dependencies=[Depends(secure_workflow)])
    async def torrent_action(body: TorrentAction):
        return await torrents.action(body)

    @app.post("/v1/seedbox/torrents/retention", dependencies=[Depends(secure_workflow)])
    async def torrent_retention(body: TorrentRetention):
        return await torrents.configure_retention(body)

    @app.get("/v1/seedbox/locations", dependencies=[Depends(secure_workflow)])
    async def vpn_locations():
        return await locations.public()

    @app.post("/v1/seedbox/locations", dependencies=[Depends(secure_workflow)], status_code=202)
    async def vpn_location_change(body: VPNLocation):
        return await locations.change(body)

    @app.post("/v1/seedbox/wizard/configure", dependencies=[Depends(secure_workflow)])
    async def wizard_configure(body: WizardConfiguration):
        return await workflow.configure(body)

    @app.post("/v1/seedbox/wizard/advance", dependencies=[Depends(secure_workflow)])
    async def wizard_advance(body: WizardAdvance):
        return await workflow.advance(body)

    @app.post("/v1/seedbox/wizard/vpn", dependencies=[Depends(secure_workflow)])
    async def wizard_vpn(body: VPNImport):
        return await workflow.import_vpn(body)

    @app.post("/v1/seedbox/wizard/client", dependencies=[Depends(secure_workflow)])
    async def wizard_client(body: ClientImport):
        return await workflow.import_client(body)

    @app.get("/v1/seedbox/wizard/review")
    async def wizard_review():
        return await workflow.review()

    @app.post(
        "/v1/seedbox/wizard/preflight", dependencies=[Depends(secure_workflow)], status_code=202
    )
    async def wizard_preflight(body: WizardExecute):
        return await workflow.preflight(body)

    @app.post(
        "/v1/seedbox/wizard/install", dependencies=[Depends(secure_workflow)], status_code=202
    )
    async def wizard_install(body: WizardExecute):
        return await workflow.install(body)

    @app.post("/v1/seedbox/wizard/adopt", dependencies=[Depends(secure_workflow)], status_code=202)
    async def wizard_adopt():
        return await workflow.adopt()

    @app.post(
        "/v1/seedbox/wizard/rotate/client", dependencies=[Depends(secure_workflow)], status_code=202
    )
    async def rotate_client(body: ClientImport):
        return await workflow.rotation(body, "client")

    @app.post(
        "/v1/seedbox/wizard/rotate/vpn", dependencies=[Depends(secure_workflow)], status_code=202
    )
    async def rotate_vpn(body: VPNImport):
        return await workflow.rotation(body, "vpn")

    @app.post(
        "/v1/seedbox/wizard/rollback", dependencies=[Depends(secure_workflow)], status_code=202
    )
    async def wizard_rollback():
        return await workflow.rollback()

    @app.get("/v1/seedbox/status")
    async def seedbox_health():
        report = {**await seedbox_status.report(devices()), "control": control.public()}
        forwarding = control.driver.forwarding.public()
        report["portForwarding"] = forwarding
        if report["health"] == "healthy" and forwarding["status"] != "healthy":
            report["health"] = "degraded"
        return report

    @app.post("/v1/seedbox/actions/{action}", status_code=202)
    async def seedbox_action(action: str):
        return await control.submit(action)

    @app.get("/v1/seedbox/logs")
    async def seedbox_logs():
        return {"entries": control.events[-100:]}

    @app.post("/v1/seedbox/uninstall", status_code=202)
    async def seedbox_uninstall(body: RemoveRuntimeRequest):
        return await control.uninstall(body.confirmedInstallationId)

    @app.post("/v1/seedbox/install", status_code=202)
    async def seedbox_install(body: PrepareSeedbox):
        return await control.install(body)

    @app.post("/v1/seedbox/prepare")
    def seedbox_prepare(body: PrepareSeedbox):
        return seedbox.prepare(body)

    @app.get("/v1/directories")
    async def directories(path: str | None = None):
        return policy.browse(path)

    @app.get("/v1/files")
    async def files(path: str):
        return await asyncio.to_thread(policy.list_entries, path)

    @app.post("/v1/uploads")
    async def begin_upload(body: UploadRequest):
        return uploads.create(body.root, body.path, body.filename, body.size)

    @app.get("/v1/uploads/{identifier}")
    async def upload_status(identifier: str, root: str):
        return await uploads.status(identifier, root)

    @app.put("/v1/uploads/{identifier}")
    async def upload_chunk(identifier: str, root: str, offset: int, request: Request):
        return await uploads.chunk(identifier, root, offset, request.stream())

    @app.post("/v1/uploads/{identifier}/finish")
    async def finish_upload(identifier: str, root: str):
        return await uploads.finish(identifier, root)

    @app.delete("/v1/uploads/{identifier}")
    async def cancel_upload(identifier: str, root: str):
        return await uploads.cancel(identifier, root)

    @app.put("/v1/files/upload")
    async def upload_file(
        request: Request,
        path: str,
        filename: str,
        expected_size: int | None = None,
    ):
        return await policy.upload(path, filename, request.stream(), expected_size)

    @app.post("/v1/directories/inspect")
    async def inspect(body: DirectoryRequest):
        return policy.inspect(body.path)

    @app.post("/v1/directories/create")
    async def create(body: CreateRequest):
        return policy.create(body.path, body.confirmed_path)

    return app


if __name__ == "__main__":
    import uvicorn

    config = AgentConfig()
    uvicorn.run(
        "agent.main:create_agent",
        factory=True,
        host=config.listen_host,
        port=config.port,
        access_log=False,
        proxy_headers=False,
        ssl_certfile=str(config.tls_cert) if config.tls_cert else None,
        ssl_keyfile=str(config.tls_key) if config.tls_key else None,
    )
