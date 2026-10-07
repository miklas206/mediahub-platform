from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from mediahub.contracts import StrictModel

CONTAINER_APPS = {
    "jellyfin": {
        "name": "Jellyfin",
        "repository": "jellyfin/jellyfin",
        "port": 8096,
        "digest": "sha256:357724bf0ae27a672c7cbaa899db2d9abeb13dbd8657ccce750258a4c059d037",
    },
    "prowlarr": {
        "name": "Prowlarr",
        "repository": "linuxserver/prowlarr",
        "port": 9696,
        "digest": "sha256:f9151e5bc1025c6d0a630d503210cdcb6bb55a7cc098562609d96a408d838902",
    },
    "radarr": {
        "name": "Radarr",
        "repository": "linuxserver/radarr",
        "port": 7878,
        "digest": "sha256:7dfd049e79c00b16fbc29c3f5d96a9e7b9e73a23930b4c5b3c4541d60b366814",
    },
    "sonarr": {
        "name": "Sonarr",
        "repository": "linuxserver/sonarr",
        "port": 8989,
        "digest": "sha256:f247545d23ba8b233d6604575347e48a623fe6ad75dda02348bf81917f3b5c06",
    },
    "autobrr": {
        "name": "autobrr",
        "repository": "ghcr.io/autobrr/autobrr",
        "port": 7474,
        "digest": "sha256:e200008d43fe6cd2d944c9bcf20900cfb8ba8a8e509625bb78ee51910b994005",
    },
}


def container_slots(app):
    slots = {"appdata": ("/config", False, True)}
    if app in {"jellyfin", "radarr"}:
        slots["movies"] = ("/movies", app == "jellyfin", app == "radarr")
    if app in {"jellyfin", "sonarr"}:
        slots["tv"] = ("/tv", app == "jellyfin", app == "sonarr")
    if app in {"radarr", "sonarr"}:
        slots["downloads"] = ("/downloads", False, True)
    return slots


class ContainerInstallation(StrictModel):
    app: Literal["jellyfin", "prowlarr", "radarr", "sonarr", "autobrr"]
    hostId: str = Field(min_length=1, max_length=80)
    storageIds: dict[str, str] = Field(default_factory=dict, max_length=4)
    timezone: str = Field(default="Europe/Copenhagen", min_length=1, max_length=80)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Choose a valid timezone") from None
        return value


class ContainerInstallRequest(StrictModel):
    installation: ContainerInstallation
    confirmedPlanDigest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ContainerRemoval(StrictModel):
    confirmedInstallationId: str = Field(min_length=1, max_length=80)
