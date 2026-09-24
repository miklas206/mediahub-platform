"""Host identity and logical shared storage; no filesystem operations."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
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
        "hosts",
        *record(),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("address", sa.String(), nullable=False, unique=True),
        sa.Column("local", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_seen", sa.String(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("encrypted_token", sa.String(), nullable=True),
    )
    op.create_table(
        "pairing_requests",
        *record(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "logical_storage",
        *record(),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dataset_ref", sa.String(), nullable=False),
    )
    op.create_table(
        "host_storage",
        *record(),
        sa.Column("host_id", sa.String(), sa.ForeignKey("hosts.id"), nullable=False),
        sa.Column("logical_id", sa.String(), sa.ForeignKey("logical_storage.id"), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("access", sa.String(), nullable=False),
        sa.UniqueConstraint("host_id", "logical_id"),
        sa.UniqueConstraint("host_id", "path"),
    )


def downgrade():
    for table in ["host_storage", "logical_storage", "pairing_requests", "hosts"]:
        op.drop_table(table)
