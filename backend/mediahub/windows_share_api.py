"""Guided Windows connection details; saving never modifies the SMB server."""

from fastapi import APIRouter, Depends, Request, Response

from mediahub.api import administrator, authenticated, result, services
from mediahub.apps.windows_share import register_windows_share_app
from mediahub.windows_share import APP_ID, WindowsShareConfiguration

router = APIRouter(prefix="/windows-share")


@router.get("/configuration")
def configuration(request: Request, user=Depends(authenticated)):
    return result(services(request).windows_share.configured())


@router.put("/configuration")
async def save_configuration(
    body: WindowsShareConfiguration, request: Request, user=Depends(administrator)
):
    svc = services(request)
    saved = svc.windows_share.save(body)
    register_windows_share_app(svc)
    svc.events.record(
        "windows-share.configured",
        APP_ID,
        "Windows share connection saved; server and media unchanged",
    )
    svc.events.record(
        "app.health.changed",
        APP_ID,
        "Windows share connection configured; Windows access remains unverified",
    )
    return result(saved)


@router.get("/status")
async def status(request: Request, user=Depends(authenticated)):
    return result(await services(request).windows_share.status())


@router.post("/check")
async def check(request: Request, user=Depends(administrator)):
    svc = services(request)
    svc.windows_share.require_configuration()
    return result(await svc.windows_share.status(force=True))


def script_download(request, diagnostics):
    from mediahub.windows_share_scripts import (
        generate_connect_script,
        generate_diagnostics_script,
        utf8_bom_script,
    )

    config = services(request).windows_share.require_configuration()
    generate = generate_diagnostics_script if diagnostics else generate_connect_script
    script = generate(config.server, config.shareName, config.driveLetter, config.username or None)
    filename = "mediahub-windows-diagnostics.ps1" if diagnostics else "mediahub-connect-share.ps1"
    return Response(
        utf8_bom_script(script),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/connect.ps1")
def connect_script(request: Request, user=Depends(administrator)):
    return script_download(request, False)


@router.get("/diagnostics.ps1")
def diagnostic_script(request: Request, user=Depends(administrator)):
    return script_download(request, True)
