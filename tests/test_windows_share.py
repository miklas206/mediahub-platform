import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mediahub.apps.windows_share import register_windows_share_app
from mediahub.db import AppConfiguration, InstalledApp
from mediahub.errors import DomainError
from mediahub.windows_share import (
    APP_ID,
    PACKAGE_ID,
    WindowsShareConfiguration,
    WindowsShareService,
    tcp_connect,
)
from pydantic import ValidationError
from sqlalchemy import select

CONFIG = {
    "server": "192.168.1.148",
    "shareName": "MediaHub",
    "username": "mediahub",
    "driveLetter": "M",
}


@pytest.mark.parametrize(
    "server",
    [
        "8.8.8.8",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "255.255.255.255",
        "100.64.1.1",
        "192.0.2.1",
        "198.18.0.1",
        "172.32.0.1",
        "localhost",
        "nas.local",
        "http://192.168.1.1",
        "192.168.1.1:445",
        "192.168.01.1",
        "192.168.1.1\n",
        "::1",
        "fd00::1",
        "::ffff:192.168.1.1",
    ],
)
def test_probe_targets_are_only_literal_private_lan_ipv4(server):
    with pytest.raises(ValidationError):
        WindowsShareConfiguration(**{**CONFIG, "server": server})


@pytest.mark.parametrize("server", ["10.0.0.1", "172.16.0.1", "172.31.255.1", "192.168.1.2"])
def test_rfc1918_targets_are_accepted(server):
    assert WindowsShareConfiguration(**{**CONFIG, "server": server}).server == server


@pytest.mark.parametrize(
    "field,value",
    [
        ("shareName", "../secret"),
        ("shareName", "Media\\Film"),
        ("shareName", "Media;exit"),
        ("shareName", "Media'"),
        ("shareName", "Media\nOther"),
        ("shareName", "Media."),
        ("shareName", " Media"),
        ("shareName", "Media "),
        ("shareName", ".."),
        ("username", "user;exit"),
        ("username", "user`whoami"),
        ("username", "user\npassword"),
        ("username", "'user'"),
        ("username", " user"),
        ("driveLetter", "C"),
        ("driveLetter", "M:"),
        ("driveLetter", "MM"),
        ("driveLetter", "Z\n"),
        ("server", 123456),
    ],
)
def test_command_inputs_reject_paths_shell_syntax_and_control_characters(field, value):
    with pytest.raises(ValidationError):
        WindowsShareConfiguration(**{**CONFIG, field: value})


def test_optional_fields_default_and_normalize():
    config = WindowsShareConfiguration(server=CONFIG["server"], shareName="Media Hub")
    assert config.username == "" and config.driveLetter == "M"
    assert (
        WindowsShareConfiguration(
            **{**CONFIG, "driveLetter": "z", "username": "DOMAIN\\reader"}
        ).driveLetter
        == "Z"
    )


def test_routes_require_login_and_configuration_changes_require_csrf(client, logged_in):
    cookie = client.cookies.get("mediahub_session")
    client.cookies.clear()
    for suffix in ("configuration", "status", "connect.ps1", "diagnostics.ps1", "reset-password.ps1"):
        assert client.get("/api/v1/windows-share/" + suffix).status_code == 401
    assert client.post("/api/v1/windows-share/check").status_code == 401
    assert client.put("/api/v1/windows-share/configuration", json=CONFIG).status_code == 401
    client.cookies.set("mediahub_session", cookie)
    for method, suffix in ((client.put, "configuration"), (client.post, "check")):
        response = method(
            "/api/v1/windows-share/" + suffix, json=CONFIG, headers={"X-MediaHub-CSRF": "wrong"}
        )
        assert response.status_code == 403


def test_viewer_cannot_save_probe_or_download_helpers(logged_in, monkeypatch):
    auth = logged_in.app.state.services.auth
    real = auth.authenticate
    monkeypatch.setattr(auth, "authenticate", lambda token: {**real(token), "role": "viewer"})
    assert logged_in.get("/api/v1/windows-share/configuration").status_code == 200
    assert logged_in.get("/api/v1/windows-share/status").status_code == 200
    assert logged_in.put("/api/v1/windows-share/configuration", json=CONFIG).status_code == 403
    assert logged_in.post("/api/v1/windows-share/check").status_code == 403
    assert logged_in.get("/api/v1/windows-share/connect.ps1").status_code == 403
    assert logged_in.get("/api/v1/windows-share/diagnostics.ps1").status_code == 403
    assert logged_in.get("/api/v1/windows-share/reset-password.ps1").status_code == 403


def test_catalog_does_not_install_or_register_an_unconfigured_share(logged_in):
    svc = logged_in.app.state.services
    manifest = next(
        item for item in logged_in.get("/api/v1/catalog").json()["data"] if item["id"] == PACKAGE_ID
    )
    assert manifest["name"] == "Windows folder access" and manifest["availability"] == "available"
    assert manifest["services"] == {} and manifest["secrets"] == []
    assert all(app["packageId"] != PACKAGE_ID for app in svc.apps.list())
    assert logged_in.get("/api/v1/windows-share/configuration").json()["data"] == {
        "configured": False,
        "appId": None,
        "configuration": None,
    }
    assert logged_in.get("/api/v1/windows-share/status").json()["data"]["tcpReachable"] is None
    assert logged_in.get("/api/v1/windows-share/connect.ps1").status_code == 409
    assert logged_in.post("/api/v1/windows-share/check").status_code == 409
    response = logged_in.put(f"/api/v1/catalog/{PACKAGE_ID}/configuration", json={"values": {}})
    assert response.status_code == 409
    with svc.sessions() as db:
        assert (
            db.scalar(select(AppConfiguration).where(AppConfiguration.package_id == PACKAGE_ID))
            is None
        )


def test_saved_connection_is_genuine_persistent_and_registers_only_once(logged_in, monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr("mediahub.windows_share.tcp_connect", probe)
    svc = logged_in.app.state.services
    response = logged_in.put("/api/v1/windows-share/configuration", json=CONFIG)
    assert response.status_code == 200
    assert response.json()["data"] == {"configured": True, "appId": APP_ID, "configuration": CONFIG}
    probe.assert_not_awaited()
    assert svc.apps.get(APP_ID)["packageId"] == PACKAGE_ID
    assert svc.apps.get(APP_ID)["isMock"] is False
    assert svc.apps.get(APP_ID)["detailPath"] == "/apps/windows-share"
    assert WindowsShareService(svc.sessions).configuration().model_dump() == CONFIG
    register_windows_share_app(svc)
    logged_in.put("/api/v1/windows-share/configuration", json={**CONFIG, "driveLetter": "z"})
    with svc.sessions() as db:
        assert (
            len(db.scalars(select(InstalledApp).where(InstalledApp.package_id == PACKAGE_ID)).all())
            == 1
        )
    svc.apps.adapters.pop(APP_ID)
    register_windows_share_app(svc)
    assert APP_ID in svc.apps.adapters
    assert svc.windows_share.configuration().driveLetter == "Z"


def test_passwords_unknown_fields_and_invalid_targets_never_persist(logged_in, monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr("mediahub.windows_share.tcp_connect", probe)
    for payload in (
        {**CONFIG, "password": "private-secret"},
        {**CONFIG, "server": "8.8.8.8"},
        {**CONFIG, "port": 22},
    ):
        response = logged_in.put("/api/v1/windows-share/configuration", json=payload)
        assert response.status_code == 422
        assert "private-secret" not in response.text
    assert logged_in.app.state.services.windows_share.configuration() is None
    probe.assert_not_awaited()


def test_core_probe_is_cached_and_does_not_claim_windows_access(logged_in, monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr("mediahub.windows_share.tcp_connect", probe)
    logged_in.put("/api/v1/windows-share/configuration", json=CONFIG)
    report = logged_in.post("/api/v1/windows-share/check").json()["data"]
    assert report["tcpReachable"] is True and report["status"] == "reachable"
    assert report["shareAccessVerified"] is False and report["windowsAccessVerified"] is False
    assert report["checkedFrom"] == "mediahub-core" and report["port"] == 445
    assert report["checkedAt"] and report["latencyMs"] >= 0
    assert "not been verified" in report["message"]
    assert logged_in.get("/api/v1/windows-share/status").json()["data"]["cached"] is True
    health = logged_in.get(f"/api/v1/apps/{APP_ID}/health").json()["data"]
    assert health["status"] == "unknown"
    assert health["checks"][0]["status"] == "healthy"
    assert health["checks"][1]["status"] == "unknown"
    runtime = logged_in.get(f"/api/v1/apps/{APP_ID}/runtime").json()["data"]
    assert runtime["view"] == "windows-share"
    assert runtime["report"]["windowsShare"]["windowsAccessVerified"] is False
    probe.assert_awaited_once_with(CONFIG["server"])


def test_failed_probe_does_not_expose_raw_os_errors_or_claim_windows_failure(
    logged_in, monkeypatch
):
    monkeypatch.setattr(
        "mediahub.windows_share.tcp_connect", AsyncMock(side_effect=OSError("PRIVATE OS DETAIL"))
    )
    logged_in.put("/api/v1/windows-share/configuration", json=CONFIG)
    response = logged_in.post("/api/v1/windows-share/check")
    report = response.json()["data"]
    assert report["status"] == "unreachable" and report["tcpReachable"] is False
    assert report["latencyMs"] is None
    assert "does not determine" in report["message"] and "PRIVATE" not in response.text


def test_config_changed_during_probe_is_not_reported_as_new_target_health(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    svc.windows_share.save(WindowsShareConfiguration(**CONFIG))

    async def probe(_):
        svc.windows_share.save(WindowsShareConfiguration(**{**CONFIG, "server": "10.0.0.2"}))

    monkeypatch.setattr("mediahub.windows_share.tcp_connect", probe)
    with pytest.raises(DomainError) as error:
        asyncio.run(svc.windows_share.status())
    assert error.value.code == "windows_share_changed"
    assert svc.windows_share.cached is None


def test_parallel_refresh_requests_share_one_bounded_probe(logged_in, monkeypatch):
    svc = logged_in.app.state.services
    svc.windows_share.save(WindowsShareConfiguration(**CONFIG))

    async def probe(_):
        await asyncio.sleep(0.01)

    mocked = AsyncMock(side_effect=probe)
    monkeypatch.setattr("mediahub.windows_share.tcp_connect", mocked)

    async def run():
        reports = await asyncio.gather(*(svc.windows_share.status(force=True) for _ in range(5)))
        assert all(report["tcpReachable"] is True for report in reports)
        assert sum(not report["cached"] for report in reports) == 1

    asyncio.run(run())
    mocked.assert_awaited_once()


def test_removal_only_clears_config_and_registration_and_can_be_readded(logged_in, monkeypatch):
    monkeypatch.setattr("mediahub.windows_share.tcp_connect", AsyncMock())
    svc = logged_in.app.state.services
    svc.agent.request = AsyncMock(side_effect=AssertionError("Agent must not be called"))
    logged_in.put("/api/v1/windows-share/configuration", json=CONFIG)
    path = f"/api/v1/apps/{APP_ID}/uninstall"
    status = logged_in.get(path).json()["data"]
    assert status["mode"] == "monitoring" and status["installationId"] == APP_ID
    assert logged_in.post(path, json={"confirmedInstallationId": "wrong"}).status_code == 409
    assert svc.windows_share.configuration() is not None
    response = logged_in.post(path, json={"confirmedInstallationId": APP_ID})
    assert response.status_code == 200 and response.json()["data"]["dataPreserved"] is True
    assert svc.windows_share.configuration() is None
    assert all(app["id"] != APP_ID for app in svc.apps.list())
    register_windows_share_app(svc)
    assert APP_ID not in svc.apps.adapters
    assert logged_in.put("/api/v1/windows-share/configuration", json=CONFIG).status_code == 200
    assert svc.apps.get(APP_ID)["state"] == "configured"
    svc.agent.request.assert_not_awaited()


def test_service_control_is_never_forwarded_to_smb_server(logged_in):
    logged_in.put("/api/v1/windows-share/configuration", json=CONFIG)
    for action in ("start", "stop", "restart"):
        response = logged_in.post(f"/api/v1/apps/{APP_ID}/actions/{action}")
        assert response.status_code == 400 and response.json()["error"]["code"] == "read_only_app"


@pytest.mark.parametrize("share_name", ["MediaHub", ".hidden", "Film og serier"])
def test_downloads_are_generated_from_saved_connection_without_running_them(
    logged_in, monkeypatch, share_name
):
    probe = AsyncMock()
    monkeypatch.setattr("mediahub.windows_share.tcp_connect", probe)
    payload = {**CONFIG, "shareName": share_name, "username": "DOMAIN\\reader", "driveLetter": "z"}
    assert logged_in.put("/api/v1/windows-share/configuration", json=payload).status_code == 200
    for endpoint, filename in (
        ("connect.ps1", "mediahub-connect-share.ps1"),
        ("diagnostics.ps1", "mediahub-windows-diagnostics.ps1"),
        ("reset-password.ps1", "mediahub-reset-smb-password.ps1"),
    ):
        response = logged_in.get("/api/v1/windows-share/" + endpoint)
        assert response.status_code == 200
        assert response.headers["content-disposition"] == f'attachment; filename="{filename}"'
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content.startswith(b"\xef\xbb\xbf")
        script = response.content.decode("utf-8-sig")
        assert "$ServerAddress = '192.168.1.148'" in script
        assert f"$SharePath = '\\\\192.168.1.148\\{share_name}'" in script
        assert "$DriveName = 'Z'" in script
        assert "$SuggestedUsername = 'DOMAIN\\reader'" in script
        if endpoint == "connect.ps1":
            assert "Get-Credential" not in script
            assert "Read-Host" in script
            assert "-AsSecureString" in script
    probe.assert_not_awaited()


def test_tcp_probe_uses_fixed_445_and_closes_without_sending_data(monkeypatch):
    writer = SimpleNamespace(close=MagicMock(), wait_closed=AsyncMock(), write=MagicMock())
    connect = AsyncMock(return_value=(object(), writer))
    monkeypatch.setattr("mediahub.windows_share.asyncio.open_connection", connect)
    asyncio.run(tcp_connect(CONFIG["server"]))
    connect.assert_awaited_once_with(CONFIG["server"], 445)
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()
    writer.write.assert_not_called()


def test_tcp_probe_has_real_total_timeout(monkeypatch):
    cancelled = []

    async def connect(*_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr("mediahub.windows_share.asyncio.open_connection", connect)
    monkeypatch.setattr("mediahub.windows_share.CHECK_TIMEOUT", 0.01)
    with pytest.raises(TimeoutError):
        asyncio.run(tcp_connect(CONFIG["server"]))
    assert cancelled == [True]
