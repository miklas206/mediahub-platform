"""Optional external integrations; tokens remain outside the database."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "external_integrations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("allow_http", sa.Boolean(), nullable=False),
        sa.Column("secret_reference", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("last_success", sa.String(), nullable=True),
        sa.Column("next_sync", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("external_integrations")
