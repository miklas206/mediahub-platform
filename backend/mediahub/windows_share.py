"""Saved, non-secret Windows share guidance and read-only Core TCP checks."""

import asyncio
import contextlib
import time
from ipaddress import IPv4Address, IPv4Network

from pydantic import Field, field_validator
from sqlalchemy import select

from mediahub.contracts import StrictModel
from mediahub.db import Setting, now
from mediahub.errors import DomainError

PACKAGE_ID = "org.mediahub.windows-share"
APP_ID = "windows-share"
SETTING_KEY = "windows_share_connection"
PRIVATE_NETWORKS = tuple(
    IPv4Network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
CHECK_TIMEOUT = 4
CACHE_SECONDS = 60


class WindowsShareConfiguration(StrictModel):
    server: str = Field(strict=True, min_length=7, max_length=15)
    shareName: str = Field(strict=True, min_length=1, max_length=80)
    username: str = Field(default="", strict=True, max_length=128)
    driveLetter: str = Field(default="M", strict=True, pattern=r"^[D-Zd-z]$")

    @field_validator("server")
    @classmethod
    def private_ipv4(cls, value):
        address = IPv4Address(value)
        if not any(address in network for network in PRIVATE_NETWORKS):
            raise ValueError("Use a private LAN IPv4 address")
        return str(address)

    @field_validator("shareName")
    @classmethod
    def share_name(cls, value):
        if (
            value != value.strip()
            or value.endswith(".")
            or value in {".", ".."}
            or not all(character.isalnum() or character in " ._$-" for character in value)
        ):
            raise ValueError("Use a share name without paths, control characters or shell syntax")
        return value

    @field_validator("username")
    @classmethod
    def user_name(cls, value):
        if value != value.strip() or not all(
            character.isalnum() or character in " ._@\\-" for character in value
        ):
            raise ValueError("Use an optional Windows username without shell syntax")
        return value

    @field_validator("driveLetter")
    @classmethod
    def drive_letter(cls, value):
        return value.upper()


async def tcp_connect(server):
    """Open and close TCP 445; do not negotiate SMB or send credentials."""
    writer = None
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            _, writer = await asyncio.open_connection(server, 445)
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 0.5)


class WindowsShareService:
    def __init__(self, sessions):
        self.sessions = sessions
        self.lock = asyncio.Lock()
        self.cached = None

    def configuration(self):
        with self.sessions() as db:
            row = db.scalar(select(Setting).where(Setting.key == SETTING_KEY))
            return WindowsShareConfiguration.model_validate(row.value) if row else None

    def configured(self):
        configuration = self.configuration()
        return {
            "configured": configuration is not None,
            "appId": APP_ID if configuration else None,
            "configuration": configuration.model_dump() if configuration else None,
        }

    def require_configuration(self):
        configuration = self.configuration()
        if configuration is None:
            raise DomainError(
                "windows_share_not_configured", "Save the Windows share connection first", 409
            )
        return configuration

    def save(self, configuration):
        # Callers pass the validated, credential-free contract, never arbitrary JSON.
        with self.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == SETTING_KEY))
            if row:
                row.value = configuration.model_dump()
            else:
                db.add(Setting(key=SETTING_KEY, value=configuration.model_dump()))
        self.cached = None
        return self.configured()

    def clear(self):
        with self.sessions.begin() as db:
            row = db.scalar(select(Setting).where(Setting.key == SETTING_KEY))
            if row:
                db.delete(row)
        self.cached = None

    @staticmethod
    def blank(configuration):
        return {
            "configured": configuration is not None,
            "status": "not_configured",
            "checkedAt": None,
            "checkedFrom": "mediahub-core",
            "server": configuration.server if configuration else None,
            "port": 445,
            "tcpReachable": None,
            "latencyMs": None,
            "shareAccessVerified": False,
            "windowsAccessVerified": False,
            "message": "Save a private Windows share connection to begin",
            "cached": False,
        }

    async def status(self, force=False):
        requested_at = time.monotonic()
        async with self.lock:
            configuration = self.configuration()
            if configuration is None:
                return self.blank(None)
            key = configuration.model_dump_json()
            if self.cached and self.cached[0] == key:
                _, completed_at, report = self.cached
                if completed_at >= requested_at or (
                    not force and requested_at - completed_at < CACHE_SECONDS
                ):
                    return {**report, "cached": True}
            report = self.blank(configuration)
            started = time.monotonic()
            reachable = False
            try:
                async with asyncio.timeout(CHECK_TIMEOUT + 1):
                    await tcp_connect(configuration.server)
                reachable = True
            except (OSError, TimeoutError):
                pass
            report.update(
                status="reachable" if reachable else "unreachable",
                checkedAt=now(),
                tcpReachable=reachable,
                latencyMs=round((time.monotonic() - started) * 1000, 1) if reachable else None,
                message="TCP 445 is reachable from MediaHub Core. Windows sign-in and folder access have not been verified."
                if reachable
                else "TCP 445 could not be reached from MediaHub Core. This does not determine whether your Windows PC can access the share.",
            )
            # A concurrent save/removal must not attach the previous target's result
            # to the new configuration, even for the request already in progress.
            current = self.configuration()
            if current is None or current.model_dump_json() != key:
                raise DomainError(
                    "windows_share_changed",
                    "The share connection changed during the check. Run the check again.",
                    409,
                )
            self.cached = (key, time.monotonic(), report)
            return report
