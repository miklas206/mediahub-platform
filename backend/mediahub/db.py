from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> str:
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now, onupdate=now)


class User(Record, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="administrator")


class Session(Record, Base):
    __tablename__ = "sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    csrf_token: Mapped[str] = mapped_column(String)
    expires_at: Mapped[int] = mapped_column(Integer)


class UserSecurity(Base):
    __tablename__ = "user_security"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_expires: Mapped[int] = mapped_column(Integer, default=0)
    last_counter: Mapped[int] = mapped_column(Integer, default=-1)
    recovery_hashes: Mapped[list] = mapped_column(JSON, default=list)


class Setting(Record, Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, unique=True)
    value: Mapped[dict] = mapped_column(JSON)


class InstalledApp(Record, Base):
    __tablename__ = "installed_apps"
    package_id: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="stopped")
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)


class StorageLocation(Record, Base):
    __tablename__ = "storage_locations"
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String, unique=True)


class StorageMapping(Record, Base):
    __tablename__ = "storage_mappings"
    app_id: Mapped[str] = mapped_column(ForeignKey("installed_apps.id"))
    location_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"))
    target: Mapped[str] = mapped_column(String)
    access: Mapped[str] = mapped_column(String, default="ro")


class Event(Record, Base):
    __tablename__ = "events"
    type: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="info")
    message: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Activity(Record, Base):
    __tablename__ = "activity_log"
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), unique=True)


class Notification(Record, Base):
    __tablename__ = "notifications"
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    state: Mapped[str] = mapped_column(String, default="pending")


class UpdateHistory(Record, Base):
    __tablename__ = "update_history"
    app_id: Mapped[str | None] = mapped_column(ForeignKey("installed_apps.id"), nullable=True)
    from_version: Mapped[str] = mapped_column(String)
    to_version: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String)


def connect(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def sqlite_settings(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    return engine, sessionmaker(engine, expire_on_commit=False)


class InstallationState(Record, Base):
    __tablename__ = "installation_state"
    singleton: Mapped[str] = mapped_column(String, unique=True, default="primary")
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_version: Mapped[int] = mapped_column(Integer, default=2)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    draft: Mapped[dict] = mapped_column(JSON, default=dict)


class PendingImport(Record, Base):
    __tablename__ = "pending_imports"
    source_type: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String, unique=True)
    detected_app: Mapped[str] = mapped_column(String)
    target_app: Mapped[str] = mapped_column(String)
    source_paths: Mapped[list] = mapped_column(JSON)
    target_storage_mappings: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    findings: Mapped[list] = mapped_column(JSON)


class AppConfiguration(Record, Base):
    __tablename__ = "app_configurations"
    package_id: Mapped[str] = mapped_column(String, unique=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_secrets: Mapped[dict] = mapped_column(JSON, default=dict)


class ExternalIntegration(Record, Base):
    __tablename__ = "external_integrations"
    provider: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    allow_http: Mapped[bool] = mapped_column(Boolean, default=False)
    secret_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    last_success: Mapped[str | None] = mapped_column(String, nullable=True)
    next_sync: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)


class Host(Record, Base):
    __tablename__ = "hosts"
    name: Mapped[str] = mapped_column(String, unique=True)
    address: Mapped[str] = mapped_column(String, unique=True)
    local: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="offline")
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    encrypted_token: Mapped[str | None] = mapped_column(String, nullable=True)


class PairingRequest(Record, Base):
    __tablename__ = "pairing_requests"
    name: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[int] = mapped_column(Integer)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class LogicalStorage(Record, Base):
    __tablename__ = "logical_storage"
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    dataset_ref: Mapped[str] = mapped_column(String)


class HostStorage(Record, Base):
    __tablename__ = "host_storage"
    __table_args__ = (
        UniqueConstraint("host_id", "logical_id"),
        UniqueConstraint("host_id", "path"),
    )
    host_id: Mapped[str] = mapped_column(ForeignKey("hosts.id"))
    logical_id: Mapped[str] = mapped_column(ForeignKey("logical_storage.id"))
    path: Mapped[str] = mapped_column(String)
    access: Mapped[str] = mapped_column(String, default="ro")


def migrate(url: str, revision: str = "head") -> None:
    from alembic import command
    from alembic.config import Config

    from mediahub.config import ROOT

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, revision)
