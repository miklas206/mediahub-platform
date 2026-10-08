"""Encrypted GitHub release access for private MediaHub repositories."""

import re

from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore

REFERENCE = "github_release_token"


class GitHubReleaseCredentials:
    """Keep the GitHub token encrypted and expose only configured/not-configured state."""

    def __init__(self, config):
        self.store = SecretStore((config.data_dir / "release-secrets").resolve())

    def status(self):
        return self.store.status(REFERENCE)

    def save(self, token: str):
        value = token.strip()
        # GitHub may add token prefixes over time. Bound the accepted alphabet and
        # size without baking today's prefixes into the open-source application.
        if not re.fullmatch(r"[A-Za-z0-9_]{20,512}", value):
            raise DomainError(
                "invalid_github_token",
                "Use a valid GitHub access token without spaces.",
                422,
            )
        payload = value.encode("ascii")
        if self.status()["configured"]:
            self.store.replace(REFERENCE, payload)
        else:
            self.store.put(REFERENCE, payload)
        return {"configured": True}

    def token(self):
        if not self.status()["configured"]:
            return None
        try:
            return self.store.get(REFERENCE).decode("ascii")
        except (UnicodeDecodeError, DomainError):
            raise DomainError(
                "github_credentials_unavailable",
                "Stored GitHub private access is unavailable. Replace it in Updates.",
                409,
            ) from None

    def remove(self):
        self.store.delete(REFERENCE)
        return {"configured": False}
