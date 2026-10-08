"""Public first-install contracts. No arbitrary host paths or Compose input."""

from pydantic import Field, SecretStr

from mediahub.apps.seedbox import SeedboxInstallation
from mediahub.apps.seedbox_credentials import QBitInitialSettings
from mediahub.contracts import StrictModel

STEPS = (
    "Overview",
    "Target Host",
    "Storage",
    "VPN Provider",
    "VPN Configuration",
    "Port Forwarding",
    "qBittorrent Configuration",
    "Credentials",
    "Review",
    "Preflight",
    "Install",
    "Verify",
    "Complete",
)


class WizardConfiguration(StrictModel):
    revision: int = Field(ge=0)
    installation: SeedboxInstallation
    qBittorrent: QBitInitialSettings = Field(default_factory=QBitInitialSettings)
    portForwardingAcknowledged: bool = False


class WizardAdvance(StrictModel):
    revision: int = Field(ge=0)
    direction: str = Field(pattern="^(next|back)$")


class VPNImport(StrictModel):
    revision: int = Field(ge=0)
    vpnConfig: SecretStr = Field(exclude=True, min_length=1, max_length=65536)


class ClientImport(StrictModel):
    revision: int = Field(ge=0)
    webUsername: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    webPassword: SecretStr = Field(exclude=True, min_length=16, max_length=256)


class WizardExecute(StrictModel):
    revision: int = Field(ge=0)
    reviewedPlanDigest: str = Field(pattern=r"^[a-f0-9]{64}$")
