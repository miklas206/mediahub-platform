from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mediahub.db import now


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthState(StrEnum):
    healthy = "healthy"
    degraded = "degraded"
    unhealthy = "unhealthy"
    unknown = "unknown"


class HealthCheck(StrictModel):
    name: str
    status: HealthState
    message: str


class Health(StrictModel):
    status: HealthState
    summary: str
    checks: list[HealthCheck] = []
    lastChecked: str = Field(default_factory=now)


class PlatformSettings(StrictModel):
    display_name: str = Field(default="MediaHub", min_length=1, max_length=60)
    theme: Literal["dark", "light", "system"] = "dark"
    activity_page_size: int = Field(default=50, ge=10, le=100)
    advanced_mode: bool = False
    release_repository: str | None = Field(default=None, max_length=201)
    visible_navigation: list[
        Literal[
            "/",
            "/apps",
            "/storage",
            "/hosts",
            "/activity",
            "/logs",
            "/updates",
            "/backups",
            "/integrations",
            "/settings",
        ]
    ] = ["/", "/apps", "/storage", "/updates", "/backups", "/settings"]
    dashboard_sections: list[
        Literal[
            "system",
            "storage",
            "apps",
            "activity",
            "network",
            "core",
            "runtime",
            "integrations",
            "cloudflare",
        ]
    ] = ["storage", "apps", "system"]

    @field_validator("visible_navigation")
    @classmethod
    def validate_navigation(cls, value: list[str]):
        if len(value) != len(set(value)):
            raise ValueError("Navigation entries must be unique")
        if not {"/", "/settings"}.issubset(value):
            raise ValueError("Dashboard and Settings must remain visible")
        return value

    @field_validator("release_repository")
    @classmethod
    def validate_release_repository(cls, value: str | None):
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        import re

        if not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})",
            value,
        ):
            raise ValueError("Use a GitHub repository in owner/name format")
        return value

    @field_validator("dashboard_sections")
    @classmethod
    def validate_dashboard_sections(cls, value: list[str]):
        if not value:
            raise ValueError("At least one dashboard section must remain visible")
        if len(value) != len(set(value)):
            raise ValueError("Dashboard sections must be unique")
        return value


class StorageInput(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal[
        "downloads",
        "incomplete_downloads",
        "completed_downloads",
        "movies",
        "tv",
        "appdata",
        "backups",
        "temp",
        "custom",
    ]
    path: str = Field(min_length=1, max_length=4096)
