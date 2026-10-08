"""Explicit setup state and planning-only import/configuration records."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
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
        "installation_state",
        *record(),
        sa.Column("singleton", sa.String(), unique=True, nullable=False),
        sa.Column("setup_completed", sa.Boolean(), nullable=False),
        sa.Column("setup_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
    )
    op.create_table(
        "pending_imports",
        *record(),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), unique=True, nullable=False),
        sa.Column("detected_app", sa.String(), nullable=False),
        sa.Column("target_app", sa.String(), nullable=False),
        sa.Column("source_paths", sa.JSON(), nullable=False),
        sa.Column("target_storage_mappings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
    )
    op.create_table(
        "app_configurations",
        *record(),
        sa.Column("package_id", sa.String(), unique=True, nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("encrypted_secrets", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("app_configurations")
    op.drop_table("pending_imports")
    op.drop_table("installation_state")
