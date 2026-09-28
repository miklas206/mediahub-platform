"""Bounded everyday operations. Private torrent inputs never serialize implicitly."""

from typing import Literal

from pydantic import Field, SecretStr, model_validator

from mediahub.contracts import StrictModel


class AddTorrent(StrictModel):
    magnet: SecretStr | None = Field(default=None, exclude=True, max_length=16384)
    torrentBase64: SecretStr | None = Field(default=None, exclude=True, max_length=2796204)
    storageId: str = Field(min_length=1, max_length=128)
    downloadLocationId: str = Field(
        default="root", pattern=r"^(?:root|(?:folder|location)-[a-f0-9]{64})$"
    )
    startImmediately: bool = False

    @model_validator(mode="after")
    def one_input(self):
        if (self.magnet is None) == (self.torrentBase64 is None):
            raise ValueError("Choose exactly one torrent input")
        return self

    def private_payload(self):
        # Keep root-only requests compatible with an older remote Agent while a
        # coordinated Agent rollout is still pending. New Agents default to root.
        result = self.model_dump(
            exclude={"downloadLocationId"} if self.downloadLocationId == "root" else None
        )
        for key in ("magnet", "torrentBase64"):
            if value := getattr(self, key):
                result[key] = value.get_secret_value()
        return result


class TorrentAction(StrictModel):
    hash: str = Field(pattern=r"^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$")
    action: Literal["pause", "resume", "recheck", "remove"]


class VPNLocation(StrictModel):
    country: str = Field(min_length=1, max_length=80)
    server: str = Field(default="automatic", min_length=1, max_length=128)
