import platform
import re
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mediahub.api import administrator, authenticated, result, services
from mediahub.apps.cloudflared import register_cloudflared_app
from mediahub.apps.remote_registry import register_remote_apps
from mediahub.apps.remote_status import RemoteStatusCache
from mediahub.apps.seedbox import SeedboxInstallation
from mediahub.auth import COOKIE
from mediahub.contracts import StorageInput, StrictModel
from mediahub.db import InstalledApp, Setting, StorageLocation
from mediahub.errors import DomainError
from mediahub.network import cookie_options
from mediahub.path_policy import DirectoryPolicy
from mediahub.plex_api import router as plex_router
from mediahub.plex_media_api import router as plex_media_router
from mediahub.seedbox_daily_api import router as daily_router
from mediahub.seedbox_rss import router as rss_router
from mediahub.seedbox_rss_feeds import router as rss_feeds_router
from mediahub.seedbox_wizard_api import router as wizard_router
from mediahub.setup import NetworkSettings, SaveDraft

router = APIRouter()
router.include_router(wizard_router)
router.include_router(daily_router)
router.include_router(rss_router)
router.include_router(rss_feeds_router)
router.include_router(plex_router)
router.include_router(plex_media_router)


class Bootstrap(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=256)


class Revision(StrictModel):
    revision: int = Field(ge=0)


class PathBody(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    confirmed_path: str | None = None


class UploadFolder(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    relativePath: str = Field(min_length=1, max_length=4096)


class BeginUpload(StrictModel):
    path: str = Field(min_length=1, max_length=4096)
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0, le=512 * 1024**3)


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
    svc.setup.bootstrap(body.username, body.password)
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


def upload_root(svc, identifier):
    with svc.sessions() as db:
        record = db.get(StorageLocation, identifier)
        if not record:
            raise DomainError("not_found", "Storage location not found", 404)
        if record.kind in {"appdata", "backups", "temp"}:
            raise DomainError(
                "storage_not_writable", "Technical storage cannot receive uploads", 403
            )
        return Path(record.path)


def upload_session_path(svc, identifier, upload_id):
    if not re.fullmatch(r"[a-f0-9]{32}", upload_id):
        raise DomainError("invalid_upload", "Invalid upload identifier", 400)
    return "/v1/uploads/" + upload_id, str(upload_root(svc, identifier))


@router.post("/storage/locations/{identifier}/uploads")
async def begin_storage_upload(
    identifier: str, body: BeginUpload, request: Request, user=Depends(administrator)
):
    svc = services(request)
    root = upload_root(svc, identifier)
    selected = Path(body.path)
    if not selected.is_absolute() or ".." in selected.parts or not selected.is_relative_to(root):
        raise DomainError("path_not_allowed", "Choose a folder inside this media location", 403)
    return result(
        await svc.agent.request("POST", "/v1/uploads", {**body.model_dump(), "root": str(root)})
    )


@router.get("/storage/locations/{identifier}/uploads/{upload_id}")
async def storage_upload_status(
    identifier: str, upload_id: str, request: Request, user=Depends(administrator)
):
    svc = services(request)
    endpoint, root = upload_session_path(svc, identifier, upload_id)
    return result(await svc.agent.request("GET", endpoint + "?" + urlencode({"root": root})))


@router.put("/storage/locations/{identifier}/uploads/{upload_id}")
async def storage_upload_chunk(
    identifier: str, upload_id: str, request: Request, offset: int, user=Depends(administrator)
):
    svc = services(request)
    _, root = upload_session_path(svc, identifier, upload_id)
    try:
        length = int(request.headers.get("content-length", "-1"))
    except ValueError:
        length = -1
    if not 0 < length <= 8 * 1024**2 or offset < 0:
        raise DomainError("invalid_upload", "Expected an upload chunk of at most 8 MiB", 400)
    return result(await svc.agent.upload_chunk(upload_id, root, offset, request.stream(), length))


@router.head("/storage/locations/{identifier}/uploads/{upload_id}")
@router.patch("/storage/locations/{identifier}/uploads/{upload_id}")
@router.options("/storage/locations/{identifier}/uploads/{upload_id}")
async def tus_storage_upload(
    identifier: str, upload_id: str, request: Request, user=Depends(administrator)
):
    """Tus core protocol for sessions allocated by the authenticated creation API."""
    headers = {"Tus-Resumable": "1.0.0", "Cache-Control": "no-store"}
    if request.method == "OPTIONS":
        return Response(status_code=204, headers={**headers, "Tus-Version": "1.0.0"})
    if request.headers.get("tus-resumable") != "1.0.0":
        return Response(status_code=412, headers={**headers, "Tus-Version": "1.0.0"})
    svc = services(request)
    try:
        endpoint, root = upload_session_path(svc, identifier, upload_id)
        if request.method == "HEAD":
            status = await svc.agent.request("GET", endpoint + "?" + urlencode({"root": root}))
            return Response(
                status_code=200,
                headers={
                    **headers,
                    "Upload-Offset": str(status["offset"]),
                    "Upload-Length": str(status["size"]),
                },
            )
        if request.headers.get("content-type") != "application/offset+octet-stream":
            raise DomainError(
                "invalid_upload", "Tus chunks require application/offset+octet-stream", 415
            )
        raw_offset = request.headers.get("upload-offset", "")
        raw_length = request.headers.get("content-length", "")
        if not re.fullmatch(r"[0-9]{1,16}", raw_offset) or not re.fullmatch(
            r"[0-9]{1,16}", raw_length
        ):
            raise DomainError("invalid_upload", "Upload offset and length are required", 400)
        offset, length = int(raw_offset), int(raw_length)
        if length > 5 * 1024**2:
            raise DomainError("upload_too_large", "Tus chunks must not exceed 5 MiB", 413)
        if length:
            status = await svc.agent.upload_chunk(upload_id, root, offset, request.stream(), length)
        else:
            status = await svc.agent.request("GET", endpoint + "?" + urlencode({"root": root}))
            if status["offset"] != offset:
                raise DomainError("upload_offset", "Upload position changed; check progress", 409)
        return Response(
            status_code=204, headers={**headers, "Upload-Offset": str(status["offset"])}
        )
    except DomainError as error:
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message}},
            status_code=error.status,
            headers=headers,
        )


@router.post("/storage/locations/{identifier}/uploads/{upload_id}/finish")
async def finish_storage_upload(
    identifier: str, upload_id: str, request: Request, user=Depends(administrator)
):
    svc = services(request)
    endpoint, root = upload_session_path(svc, identifier, upload_id)
    uploaded = await svc.agent.request("POST", endpoint + "/finish?" + urlencode({"root": root}))
    svc.events.record(
        "storage.file.uploaded", "storage", f"File uploaded ({uploaded['size']} bytes)"
    )
    return result(uploaded)


@router.delete("/storage/locations/{identifier}/uploads/{upload_id}")
async def cancel_storage_upload(
    identifier: str, upload_id: str, request: Request, user=Depends(administrator)
):
    svc = services(request)
    endpoint, root = upload_session_path(svc, identifier, upload_id)
    return result(await svc.agent.request("DELETE", endpoint + "?" + urlencode({"root": root})))


@router.post("/storage/locations/{identifier}/files/folder")
async def prepare_upload_folder(
    identifier: str, body: UploadFolder, request: Request, user=Depends(administrator)
):
    """Create only the selected upload hierarchy within one registered media root."""
    svc = services(request)
    with svc.sessions() as db:
        record = db.get(StorageLocation, identifier)
        if not record:
            raise DomainError("not_found", "Storage location not found", 404)
        if record.kind in {"appdata", "backups", "temp"}:
            raise DomainError(
                "storage_not_writable", "Technical storage cannot receive uploads", 403
            )
        root = Path(record.path)
    selected = Path(body.path)
    if not selected.is_absolute() or ".." in selected.parts or not selected.is_relative_to(root):
        raise DomainError("path_not_allowed", "Choose a folder inside this media location", 403)
    parts = body.relativePath.split("/")
    if len(parts) > 32:
        raise DomainError("invalid_upload", "Upload folder nesting exceeds 32 levels", 400)
    # Validate every component before creating anything, including empty components.
    for part in parts:
        DirectoryPolicy._upload_filename(part)
        if Path(part).drive or ":" in part:
            raise DomainError("invalid_upload", "Choose a valid folder name", 400)
    checked = await svc.agent.request("POST", "/v1/directories/inspect", {"path": str(selected)})
    if not checked["exists"] or not checked["writable"]:
        raise DomainError("storage_not_writable", "Upload destination is not writable", 403)
    for part in parts:
        selected /= part
        checked = await svc.agent.request(
            "POST", "/v1/directories/inspect", {"path": str(selected)}
        )
        if not checked["exists"]:
            try:
                await svc.agent.request(
                    "POST",
                    "/v1/directories/create",
                    {"path": str(selected), "confirmed_path": str(selected)},
                )
            except DomainError as error:
                if error.code != "already_exists":
                    raise
        # Recheck paths created concurrently; the Agent rejects files and symlinks.
        checked = await svc.agent.request(
            "POST", "/v1/directories/inspect", {"path": str(selected)}
        )
        if not checked["exists"] or not checked["writable"]:
            raise DomainError("storage_not_writable", "Upload folder is not writable", 403)
    return result({"path": str(selected)})


@router.post("/storage/locations/{identifier}/files/upload")
async def upload_storage_file(
    identifier: str,
    request: Request,
    filename: str,
    path: str | None = None,
    user=Depends(administrator),
):
    """Stream one new file to an approved media location without overwriting data."""

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
            "storage_not_writable",
            "Technical storage cannot receive browser uploads",
            403,
        )
    root = Path(location["path"])
    selected = Path(path) if path is not None else root
    if not selected.is_absolute() or ".." in selected.parts or not selected.is_relative_to(root):
        raise DomainError("path_not_allowed", "Choose a folder inside this media location", 403)
    raw_length = request.headers.get("content-length")
    try:
        expected_size = int(raw_length) if raw_length is not None else None
    except ValueError:
        raise DomainError("invalid_upload", "Upload size is invalid", 400) from None
    uploaded = await svc.agent.upload(str(selected), filename, request.stream(), expected_size)
    svc.events.record(
        "storage.file.uploaded",
        "storage",
        f"File uploaded to {location['name']} ({uploaded['sizeBytes']} bytes)",
    )
    return result(uploaded)


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
    svc = services(request)
    if package_id == "org.mediahub.windows-share":
        raise DomainError(
            "windows_share_guided_setup",
            "Use Windows folder access setup to save this connection",
            409,
        )
    saved = svc.catalog.save(package_id, body.values)
    if package_id == "org.mediahub.cloudflared":
        svc.cloudflare_tunnel.configure(saved)
        register_cloudflared_app(svc)
        svc.events.record(
            "cloudflare.configuration.changed",
            package_id,
            "Cloudflare assisted setup saved; read-only monitoring reloaded",
        )
    return result(saved)


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
