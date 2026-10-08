"""Seedbox schema adapter over the generic encrypted record store."""

import json

from mediahub.apps.seedbox_credentials import SeedboxCredentials
from mediahub.errors import DomainError
from mediahub.secret_store import SecretStore


class SeedboxSecretStore(SecretStore):
    def stage(self, reference, credentials: SeedboxCredentials):
        return self.put(
            reference,
            json.dumps(
                {
                    "vpnConfig": credentials.vpnConfig.get_secret_value(),
                    "webUsername": credentials.webUsername,
                    "webPassword": credentials.webPassword.get_secret_value(),
                }
            ).encode(),
        )

    def load(self, reference):
        try:
            return SeedboxCredentials.model_validate_json(self.get(reference))
        except ValueError:
            raise DomainError(
                "credentials_unavailable", "Private configuration invalid", 409
            ) from None

    def status(self, reference):
        try:
            self.load(reference)
        except DomainError:
            return {"configured": False}
        return {"configured": True}
