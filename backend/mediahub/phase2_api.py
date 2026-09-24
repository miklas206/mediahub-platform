import platform
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mediahub.api import administrator, authenticated, result, services
from mediahub.apps.remote_registry import register_remote_apps
from mediahub.apps.remote_status import RemoteStatusCache
from mediahub.apps.seedbox import SeedboxInstallation
from mediahub.auth import COOKIE
from mediahub.contracts import StorageInput, StrictModel
from mediahub.db import InstalledApp, Setting, StorageLocation
from mediahub.errors import DomainError
from mediahub.network import cookie_options
from mediahub.plex_api import router as plex_router
from mediahub.seedbox_daily_api import router as daily_router
from mediahub.seedbox_wizard_api import router as wizard_router
from mediahub.setup import NetworkSettings, SaveDraft

router = APIRouter()
router.include_router(wizard_router)
router.include_router(daily_router)
router.include_router(plex_router)


class Bootstrap(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=256)
    token: str = Field(min_length=40, max_length=200)


class Revision(StrictModel):
    revision: int = Field(ge=0)


class PathBody(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    confirmed_path: str | None = None


class ConfigValues(StrictModel):
    values: dict[str, str]


class InstallPlan(StrictModel):
    mappings: dict[str, str] = {}
    host_id: str = "local"
    logical_mappings: dict[str, str] = {}


class ImportSelection(StrictModel):
    selected: list[str] = Field(max_length=200)
    mappings: dict[str, dict[str, str]] = {}
    ports: dict[str, list[int]] = {}


class PrepareSeedboxRequest(StrictModel):
    installation: SeedboxInstallation
    reviewedPlanDigest: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.get("/seedbox/status")
async def seedbox_status(request: Request, user=Depends(authenticated)):
    svc = services(request)
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        if binding is None:
            raise DomainError("seedbox_not_installed", "Seedbox is not installed", 404)
        host_id = binding.value["hostId"]
    if not hasattr(svc, "runtime_status_cache"):
        svc.runtime_status_cache = RemoteStatusCache()
    return result(await svc.runtime_status_cache.get(host_id, svc.hosts.client(host_id)))


@router.post("/seedbox/plan")
async def seedbox_install_plan(
    body: SeedboxInstallation, request: Request, user=Depends(authenticated)
):
    if services(request).config.seedbox_requires_remote_host and body.hostId == "local":
        raise DomainError("seedbox_target_denied", "Seedbox requires its separate host", 403)
    return result(
        await services(request)
        .hosts.client(body.hostId)
        .request("POST", "/v1/seedbox/plan", body.model_dump())
    )


@router.get("/seedbox/configuration")
async def seedbox_configuration(request: Request, user=Depends(authenticated)):
    with services(request).sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        if binding is None:
            raise DomainError(
                "configuration_required",
                "Provision a dedicated host policy and private credentials first",
                409,
            )
        # Credential reference only. Never return private configuration or passwords.
        return result(SeedboxInstallation.model_validate(binding.value).model_dump())


@router.post("/seedbox/install")
async def seedbox_install(
    body: PrepareSeedboxRequest, request: Request, user=Depends(administrator)
):
    svc = services(request)
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        if binding is None or binding.value != body.installation.model_dump():
            raise DomainError(
                "installation_conflict", "Review and prepare the dedicated host binding first", 409
            )
    svc.events.record(
        "app.install_requested",
        "org.mediahub.seedbox",
        "Reviewed isolated runtime installation requested",
    )
    return result(
        await svc.hosts.client(body.installation.hostId).request(
            "POST", "/v1/seedbox/install", body.model_dump()
        )
    )


@router.post("/seedbox/prepare")
async def seedbox_prepare(
    body: PrepareSeedboxRequest, request: Request, user=Depends(administrator)
):
    if (
        services(request).config.seedbox_requires_remote_host
        and body.installation.hostId == "local"
    ):
        raise DomainError("seedbox_target_denied", "Seedbox requires its separate host", 403)
    svc = services(request)
    with svc.sessions() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        if binding is not None and binding.value != body.installation.model_dump():
            raise DomainError(
                "installation_conflict", "Existing Seedbox binding must be reconciled", 409
            )
    prepared = await svc.hosts.client(body.installation.hostId).request(
        "POST", "/v1/seedbox/prepare", body.model_dump()
    )
    with svc.sessions.begin() as db:
        binding = db.scalar(select(Setting).where(Setting.key == "seedbox_installation"))
        if binding is None:
            db.add(Setting(key="seedbox_installation", value=body.installation.model_dump()))
        elif binding.value != body.installation.model_dump():
            raise DomainError(
                "installation_conflict", "Existing Seedbox binding must be reconciled", 409
            )
        app = db.scalar(
            select(InstalledApp).where(InstalledApp.package_id == "org.mediahub.seedbox")
        )
        if app is None:
            db.add(
                InstalledApp(
                    package_id="org.mediahub.seedbox",
                    name="Seedbox",
                    version="0.1.0",
                    state="prepared",
                    is_mock=False,
                )
            )
    register_remote_apps(svc)
    return result(prepared)


@router.get("/setup/status")
async def setup_status(request: Request):
    svc = services(request)
    state = svc.setup.state()
    return result(
        {key: state[key] for key in ["setup_required", "setup_completed", "setup_version"]}
        | {"hasAdmin": not svc.auth.needs_setup()}
    )


@router.get("/setup/public-checks")
async def public_checks():
    # Public checks intentionally exclude hostname, filesystem paths and agent inventory.
    return result(
        {
            "core": [
                {"name": "Core API", "state": "passed", "message": "Connected"},
                {
                    "name": "Operating system",
                    "state": "passed",
                    "message": platform.system() + " / " + platform.machine(),
                },
                {
                    "name": "Full compatibility checks",
                    "state": "warning",
                    "message": "Administrator authentication required for runtime and storage details",
                },
            ],
            "runtime": [],
        }
    )


@router.post("/setup/administrator")
async def setup_admin(body: Bootstrap, request: Request, response: Response):
    svc = services(request)
    cookies = cookie_options(request, svc.config)
    svc.setup.bootstrap(body.username, body.password, body.token)
    token, user = svc.auth.login(body.username, body.password, "bootstrap")
    response.set_cookie(
        COOKIE,
        token,
        **cookies,
        max_age=svc.config.session_hours * 3600,
    )
    return result(user)


@router.get("/setup/draft")
async def draft(request: Request, user=Depends(authenticated)):
    return result(services(request).setup.state())


@router.put("/setup/draft")
async def save_draft(body: SaveDraft, request: Request, user=Depends(authenticated)):
    return result(services(request).setup.save(body))


@router.get("/setup/checks")
async def checks(request: Request, user=Depends(authenticated)):
    return result(await services(request).setup.checks())


@router.get("/setup/review")
async def review(request: Request, user=Depends(authenticated)):
    return result(await services(request).setup.review())


@router.post("/setup/apply")
async def apply(body: Revision, request: Request, user=Depends(authenticated)):
    return result(await services(request).setup.apply(body.revision))


@router.get("/runtime")
async def runtime(request: Request, user=Depends(authenticated)):
    return result(await services(request).agent.status())


@router.get("/agent/directories")
async def directories(request: Request, path: str | None = None, user=Depends(authenticated)):
    query = "?" + urlencode({"path": path}) if path is not None else ""
    return result(await services(request).agent.request("GET", "/v1/directories" + query))


@router.post("/agent/directories/inspect")
async def inspect_directory(body: PathBody, request: Request, user=Depends(authenticated)):
    return result(
        await services(request).agent.request(
            "POST", "/v1/directories/inspect", {"path": body.path}
        )
    )


@router.post("/agent/directories/create")
async def create_directory(body: PathBody, request: Request, user=Depends(authenticated)):
    created = await services(request).agent.request(
        "POST", "/v1/directories/create", body.model_dump()
    )
    services(request).events.record(
        "storage.directory.created", "agent", "Explicitly confirmed directory created"
    )
    return result(created)


@router.get("/storage/locations")
async def storage_locations(request: Request, user=Depends(authenticated)):
    svc = services(request)
    with svc.sessions() as db:
        records = db.scalars(select(StorageLocation)).all()
    items = []
    for record in records:
        try:
            inspection = await svc.agent.request(
                "POST", "/v1/directories/inspect", {"path": record.path}
            )
        except DomainError as error:
            inspection = {
                "exists": False,
                "readable": False,
                "writable": False,
                "freeBytes": None,
                "totalBytes": None,
                "error": error.message,
            }
        items.append(
            {
                "id": record.id,
                "name": record.name,
                "kind": record.kind,
                "path": record.path,
                **inspection,
            }
        )
    return result(items)


@router.get("/storage/locations/{identifier}/files")
async def storage_files(
    identifier: str,
    request: Request,
    path: str | None = None,
    user=Depends(authenticated),
):
    """List media metadata below one registered location; never returns file contents."""

    svc = services(request)
    with svc.sessions() as db:
        record = db.get(StorageLocation, identifier)
        if not record:
            raise DomainError("not_found", "Storage location not found", 404)
        location = {
            "id": record.id,
            "name": record.name,
            "kind": record.kind,
            "path": record.path,
        }
    if location["kind"] in {"appdata", "backups", "temp"}:
        raise DomainError(
            "storage_not_browsable",
            "This technical storage location is intentionally hidden from the media browser",
            403,
        )
    root = Path(location["path"])
    selected = Path(path) if path is not None else root
    if not selected.is_absolute() or ".." in selected.parts or not selected.is_relative_to(root):
        raise DomainError("path_not_allowed", "Choose a folder inside this media location", 403)
    listing = await svc.agent.request("GET", "/v1/files?" + urlencode({"path": str(selected)}))
    parent = None if selected == root else str(selected.parent)
    return result(
        {
            "location": location,
            "path": listing["path"],
            "parent": parent,
            "items": listing["items"],
            "truncated": listing["truncated"],
        }
    )


@router.put("/storage/locations/{identifier}")
async def update_storage(
    identifier: str, body: StorageInput, request: Request, user=Depends(authenticated)
):
    svc = services(request)
    checked = await svc.agent.request("POST", "/v1/directories/inspect", {"path": body.path})
    if not checked["exists"] or not checked["readable"]:
        raise DomainError("invalid_storage", "Choose an existing readable directory")
    try:
        with svc.sessions.begin() as db:
            row = db.get(StorageLocation, identifier)
            if not row:
                raise DomainError("not_found", "Storage location not found", 404)
            row.name, row.kind, row.path = body.name, body.kind, checked["path"]
    except IntegrityError:
        raise DomainError(
            "storage_conflict", "Another location uses this name or path", 409
        ) from None
    svc.events.record(
        "storage.mapping.updated", "storage", "Storage mapping changed; no files moved"
    )
    return result({"saved": True, "filesMoved": False})


@router.post("/storage/locations", status_code=201)
async def register_location(body: StorageInput, request: Request, user=Depends(authenticated)):
    svc = services(request)
    checked = await svc.agent.request("POST", "/v1/directories/inspect", {"path": body.path})
    if not checked["exists"] or not checked["readable"]:
        raise DomainError("invalid_storage", "Choose an existing readable directory")
    try:
        with svc.sessions.begin() as db:
            record = StorageLocation(name=body.name, kind=body.kind, path=checked["path"])
            db.add(record)
            db.flush()
            identifier = record.id
    except IntegrityError:
        raise DomainError(
            "storage_conflict", "This name or path is already registered", 409
        ) from None
    return result({"id": identifier, "filesMoved": False})


@router.get("/discovery")
async def discovery_snapshot(request: Request, user=Depends(authenticated)):
    return result(services(request).imports.snapshot())


@router.post("/discovery/scan")
async def discovery_scan(request: Request, user=Depends(authenticated)):
    return result(await services(request).imports.discover())


@router.get("/imports")
async def imports(request: Request, user=Depends(authenticated)):
    return result(services(request).imports.list())


@router.post("/imports/preview")
async def import_preview(body: ImportSelection, request: Request, user=Depends(authenticated)):
    return result(await services(request).imports.preview(body.selected, body.mappings, body.ports))


@router.get("/catalog")
async def catalog(request: Request, user=Depends(authenticated)):
    return result(services(request).catalog.list())


@router.get("/catalog/{package_id}/configuration")
async def configuration(package_id: str, request: Request, user=Depends(authenticated)):
    return result(services(request).catalog.configuration(package_id))


@router.put("/catalog/{package_id}/configuration")
async def save_configuration(
    package_id: str, body: ConfigValues, request: Request, user=Depends(authenticated)
):
    return result(services(request).catalog.save(package_id, body.values))


@router.post("/catalog/{package_id}/plan")
async def plan(package_id: str, body: InstallPlan, request: Request, user=Depends(authenticated)):
    svc = services(request)
    manifest = svc.catalog.get(package_id)
    mappings = dict(body.mappings)
    blockers = []
    for slot, logical_id in body.logical_mappings.items():
        requirement = next((s for s in manifest.storageRequirements if s.id == slot), None)
        if requirement is None:
            raise DomainError("invalid_mapping", "Unknown storage slot")
        try:
            resolved = await svc.hosts.resolve(logical_id, body.host_id, requirement.access)
            mappings[slot] = resolved["path"]
        except DomainError as error:
            blockers.append(slot + ": " + error.message)
    preview = await svc.catalog.plan(package_id, mappings, svc.hosts.client(body.host_id))
    if (
        svc.config.seedbox_requires_remote_host
        and package_id == "org.mediahub.seedbox"
        and body.host_id == "local"
    ):
        blockers.append(
            "This installation requires Seedbox on a separate host; no Seedbox VM exists yet"
        )
    preview.update(hostId=body.host_id, recommendedIsolation=manifest.recommendedIsolation)
    preview["blockers"].extend(blockers)
    return result(preview)


@router.get("/network")
async def network(request: Request, user=Depends(authenticated)):
    svc = services(request)
    with svc.sessions() as db:
        saved = db.scalar(select(Setting).where(Setting.key == "network_pending"))
        desired = saved.value if saved else NetworkSettings().model_dump()
    return result(
        {
            "pending": desired,
            "active": {
                "base_url": svc.config.base_url,
                "allowed_origins": svc.config.allowed_origins,
                "trusted_proxies": svc.config.trusted_proxies,
            },
            "activation": "Explicit restart with --saved-network; no firewall or proxy changes",
        }
    )


@router.put("/network")
async def save_network(body: NetworkSettings, request: Request, user=Depends(authenticated)):
    with services(request).sessions.begin() as db:
        saved = db.scalar(select(Setting).where(Setting.key == "network_pending"))
        if saved:
            saved.value = body.model_dump()
        else:
            db.add(Setting(key="network_pending", value=body.model_dump()))
    return result({"saved": True, "restartRequired": True, "firewallChanged": False})
