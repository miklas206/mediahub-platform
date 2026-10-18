"""Administrator-only transport to the separate root-owned host storage controller."""

import json
import os
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import Field, SecretStr

from mediahub.api import administrator, result, services
from mediahub.contracts import StrictModel
from mediahub.errors import DomainError

router = APIRouter(prefix="/storage-control", dependencies=[Depends(administrator)])
PREPARING = (
    "Storage server setup is being prepared automatically. Refresh shortly, or retry server setup."
)


class NasInput(StrictModel):
    label: str = Field(min_length=1, max_length=80)
    server: str = Field(min_length=7, max_length=15)
    share: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=256, repr=False)
    readOnly: bool = True


class ShareInput(StrictModel):
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    storageId: str = Field(min_length=1, max_length=80)
    readOnly: bool = True
    password: SecretStr | None = Field(default=None, min_length=12, max_length=256, repr=False)


class PasswordInput(StrictModel):
    password: SecretStr = Field(min_length=12, max_length=256, repr=False)


async def host_request(svc, method, path, body=None):
    socket = Path(svc.config.data_dir) / "storage-control/service.sock"
    try:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=str(socket)),
            base_url="http://storage-controller",
            timeout=5 if method == "GET" else 360,
            trust_env=False,
        ) as client:
            response = await client.request(method, path, json=body)
        value = response.json()
        if not response.is_success:
            raise DomainError(
                "storage_operation_failed",
                value.get("message", "Storage operation failed"),
                response.status_code,
            )
        return value
    except (httpx.HTTPError, ValueError):
        raise DomainError("storage_controller_unavailable", PREPARING, 503) from None


def prepare_storage(svc):
    updater = svc.platform_update
    if not updater.available:
        raise DomainError(
            "storage_host_required",
            "Automatic storage setup requires the Linux MediaHub host updater. Install MediaHub with the supported Linux installer.",
            409,
        )
    root = updater.root
    # The preparation container installs the reviewed helper before advertising capability.
    if not updater._host_capability("storageController"):
        raise DomainError("storage_preparation_required", PREPARING, 409)
    target = root / "request.json"
    temporary = root / ("storage-request-" + uuid.uuid4().hex + ".json")
    try:
        temporary.write_text(
            json.dumps({"action": "storage_prepare", "operationId": uuid.uuid4().hex})
        )
        temporary.chmod(0o600)
        os.link(temporary, target)  # Never replace an in-flight update/maintenance request.
    except FileExistsError:
        raise DomainError(
            "host_busy",
            "Wait for the current host operation to finish, then retry storage setup",
            409,
        ) from None
    finally:
        temporary.unlink(missing_ok=True)
    return {"state": "preparing", "message": PREPARING}


async def ensure_storage(svc):
    updater = svc.platform_update
    if not updater._host_capability("storageController"):
        return
    try:
        expected = json.loads((updater.root / "host-capabilities.json").read_text())[
            "storageControllerRevision"
        ]
        current = await host_request(svc, "GET", "/status")
        if current.get("controllerRevision") == expected:
            return
    except (DomainError, OSError, ValueError, KeyError):
        if (Path(svc.config.data_dir) / "storage-control/service.sock").exists():
            return  # A busy controller must not be restarted during a mount/share operation.
    try:
        prepare_storage(svc)
    except DomainError:
        pass  # An existing host operation wins; the Storage tab offers an explicit retry.


@router.get("")
async def overview(request: Request):
    try:
        value = await host_request(services(request), "GET", "/status")
    except DomainError as error:
        value = {
            "available": False,
            "message": error.message,
            "locations": [],
            "nas": [],
            "shares": [],
        }
    return result(value)


@router.post("/prepare", status_code=202)
def prepare(request: Request):
    svc = services(request)
    svc.setup.require_complete()
    return result(prepare_storage(svc))


def body_values(body):
    values = body.model_dump()
    if values.get("password") is not None:
        values["password"] = body.password.get_secret_value()
    return values


@router.post("/nas")
async def add_nas(body: NasInput, request: Request):
    svc = services(request)
    svc.setup.require_complete()
    value = await host_request(svc, "POST", "/nas", body_values(body))
    svc.events.record("storage.nas_configured", "storage", "NAS connection configured")
    return result(value)


@router.post("/nas/{identifier}/{action}")
async def nas_action(identifier: str, action: str, request: Request):
    import re

    if not re.fullmatch(r"[a-f0-9]{24}", identifier) or action not in {
        "connect",
        "disconnect",
        "remove",
    }:
        raise DomainError("invalid_storage_action", "Invalid NAS action", 422)
    svc = services(request)
    svc.setup.require_complete()
    return result(await host_request(svc, "POST", f"/nas/{identifier}/{action}"))


@router.post("/shares")
async def add_share(body: ShareInput, request: Request):
    svc = services(request)
    svc.setup.require_complete()
    value = await host_request(svc, "POST", "/shares", body_values(body))
    svc.events.record(
        "storage.share_configured", "storage", "Authenticated LAN Windows share configured"
    )
    return result(value)


@router.delete("/shares/{name}")
async def remove_share(name: str, request: Request):
    import re

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", name):
        raise DomainError("invalid_share_name", "Invalid share name", 422)
    svc = services(request)
    svc.setup.require_complete()
    return result(await host_request(svc, "DELETE", "/shares/" + name))


@router.post("/password")
async def password(body: PasswordInput, request: Request):
    svc = services(request)
    svc.setup.require_complete()
    return result(await host_request(svc, "POST", "/password", body_values(body)))
