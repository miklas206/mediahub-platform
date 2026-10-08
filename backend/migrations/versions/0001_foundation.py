"""Immutable initial schema; never import mutable application models here."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def record():
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "users",
        *record(),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
    )
    op.create_table(
        "sessions",
        *record(),
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(), unique=True, nullable=False),
        sa.Column("csrf_token", sa.String(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )
    op.create_table(
        "settings",
        *record(),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )
    op.create_table(
        "installed_apps",
        *record(),
        sa.Column("package_id", sa.String(), unique=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "storage_locations",
        *record(),
        sa.Column("name", sa.String(), unique=True, nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("path", sa.String(), unique=True, nullable=False),
    )
    op.create_table(
        "storage_mappings",
        *record(),
        sa.Column("app_id", sa.String(), sa.ForeignKey("installed_apps.id"), nullable=False),
        sa.Column(
            "location_id", sa.String(), sa.ForeignKey("storage_locations.id"), nullable=False
        ),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column("access", sa.String(), nullable=False),
    )
    op.create_table(
        "events",
        *record(),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "activity_log",
        *record(),
        sa.Column("event_id", sa.String(), sa.ForeignKey("events.id"), unique=True, nullable=False),
    )
    op.create_table(
        "notifications",
        *record(),
        sa.Column("event_id", sa.String(), sa.ForeignKey("events.id"), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
    )
    op.create_table(
        "update_history",
        *record(),
        sa.Column("app_id", sa.String(), sa.ForeignKey("installed_apps.id")),
        sa.Column("from_version", sa.String(), nullable=False),
        sa.Column("to_version", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
    )


def downgrade():
    for table in [
        "update_history",
        "notifications",
        "activity_log",
        "events",
        "storage_mappings",
        "storage_locations",
        "installed_apps",
        "settings",
        "sessions",
        "users",
    ]:
        op.drop_table(table)
