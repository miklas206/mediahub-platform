import os
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(os.environ.get("MEDIAHUB_PROJECT_ROOT", str(Path(__file__).resolve().parents[2])))


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIAHUB_", env_file=".env", extra="ignore")
    base_url: str = "http://127.0.0.1:18765"
    public_url: str | None = None
    fjordhub_url: str | None = None  # Optional operator-discovered normal LAN URL.
    operator_app_urls: dict[str, str] = Field(default_factory=dict)
    cloudflared_status_url: str | None = None
    cloudflared_probe_urls: list[str] = Field(default_factory=list)

    @field_validator("operator_app_urls")
    @classmethod
    def valid_operator_urls(cls, values):
        for address in values.values():
            parsed = urlsplit(address)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Operator app URLs require HTTP(S), without embedded credentials")
        return values

    @field_validator("cloudflared_status_url")
    @classmethod
    def valid_cloudflared_status_url(cls, value):
        if value is None:
            return None
        parsed = urlsplit(value)
        try:
            address = ip_address(parsed.hostname or "")
        except ValueError:
            raise ValueError("Cloudflared status requires an explicit private IP") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not (address.is_private or address.is_loopback)
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/", "/status"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Cloudflared status URL must be a private HTTP(S) status endpoint")
        return value.rstrip("/")

    @field_validator("cloudflared_probe_urls")
    @classmethod
    def valid_cloudflared_probe_urls(cls, values):
        if len(values) > 20:
            raise ValueError("At most 20 Cloudflare routes can be monitored")
        output = []
        for value in values:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Cloudflare route probes require HTTPS URLs without credentials")
            output.append(value.rstrip("/"))
        return output

    cookie_samesite: Literal["strict", "lax", "none"] = "strict"
    agent_ca_file: Path | None = None
    internal_tls_cert: Path | None = None
    internal_tls_key: Path | None = None
    internal_tls_host: str = "127.0.0.1"
    internal_tls_port: int = Field(default=18766, ge=1024, le=65535)
    # Optional direct browser TLS; independent of the restricted Agent listener.
    browser_tls_cert: Path | None = None
    browser_tls_key: Path | None = None
    data_dir: Path = Path(".data")
    manifest_dir: Path = ROOT / "apps"
    frontend_dir: Path = ROOT / "frontend" / "dist"
    allowed_origins: list[str] = [
        "http://127.0.0.1:18765",
        "http://localhost:18765",
        "http://127.0.0.1:15173",
        "http://localhost:15173",
    ]
    trusted_proxies: list[str] = []
    storage_roots: list[Path] = []
    dev_mode: bool = False
    mock_app: bool = False
    seedbox_requires_remote_host: bool = False
    agent_url: str = "http://127.0.0.1:18767"
    agent_token_file: Path = Path(".agent/token")
    agent_socket: Path | None = None
    session_hours: int = Field(default=12, ge=1, le=168)
    sample_seconds: float = Field(default=3, ge=1, le=60)
    log_level: str = "INFO"

    @field_validator("agent_url")
    @classmethod
    def validate_agent(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "agent"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Agent must use an explicitly configured local/private transport")
        return value.rstrip("/")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("base_url must be an HTTP(S) origin without credentials or a path")
        return value.rstrip("/")

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        return [cls.validate_url(value) for value in values]

    @field_validator("public_url")
    @classmethod
    def validate_public_url(cls, value):
        if value is None:
            return None
        value = cls.validate_url(value)
        if not value.startswith("https://"):
            raise ValueError("Public access requires HTTPS")
        return value

    @model_validator(mode="after")
    def validate_transport(self):
        if bool(self.browser_tls_cert) != bool(self.browser_tls_key):
            raise ValueError("Browser TLS requires both certificate and private key")
        if self.browser_tls_cert and not self.base_url.startswith("https://"):
            raise ValueError("Direct browser TLS requires an HTTPS base_url")
        if bool(self.internal_tls_cert) != bool(self.internal_tls_key):
            raise ValueError("Internal TLS requires both certificate and private key")
        if self.cookie_samesite == "none" and any(
            url.startswith("http://") for url in self.origins
        ):
            raise ValueError("SameSite=None requires HTTPS for every configured browser origin")
        return self

    @field_validator("trusted_proxies")
    @classmethod
    def validate_proxies(cls, values: list[str]) -> list[str]:
        from ipaddress import ip_network

        for value in values:
            network = ip_network(value)  # No wildcard trust.
            if network.prefixlen == 0:
                raise ValueError("Do not trust every proxy address")
        return values

    @field_validator("log_level")
    @classmethod
    def validate_level(cls, value: str) -> str:
        if value not in {"DEBUG", "INFO", "WARN", "WARNING", "ERROR"}:
            raise ValueError("Invalid logging level")
        return value

    @property
    def secure_cookies(self) -> bool:
        return self.base_url.startswith("https://")

    @property
    def origins(self) -> set[str]:
        return {*self.allowed_origins, self.base_url} | (
            {self.public_url} if self.public_url else set()
        )

    @property
    def database_url(self) -> str:
        return "sqlite:///" + (self.data_dir.resolve() / "mediahub.db").as_posix()
