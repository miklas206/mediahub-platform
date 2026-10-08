"""Plex installation contract. Browser requests select logical storage, never host paths."""

from pydantic import Field, SecretStr, model_validator

from mediahub.contracts import StrictModel


class PlexInstallation(StrictModel):
    hostId: str = Field(default="local", min_length=1, max_length=80)
    installationId: str = Field(default="plex-main", pattern=r"^[a-z][a-z0-9-]{2,40}$")
    moviesStorageIds: list[str] = Field(default_factory=list, max_length=8)
    tvStorageIds: list[str] = Field(default_factory=list, max_length=8)
    otherStorageIds: list[str] = Field(default_factory=list, max_length=8)
    appdataStorageId: str = Field(min_length=1, max_length=80)
    serverName: str = Field(default="MediaHub", min_length=1, max_length=80)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Choose a valid timezone") from None
        media = self.moviesStorageIds + self.tvStorageIds + self.otherStorageIds
        if not media or len(media) != len(set(media)) or self.appdataStorageId in media:
            raise ValueError("Select unique media mappings separate from app data")
        if any(not value or len(value) > 80 for value in media):
            raise ValueError("Invalid logical storage identifier")
        if any(ord(c) < 32 for c in self.serverName):
            raise ValueError("Invalid server name")
        return self


class PlexInstallRequest(StrictModel):
    installation: PlexInstallation
    reviewedPlanDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
    claimToken: SecretStr | None = Field(default=None, exclude=True, max_length=256)
