"""Optional TOTP and one-use recovery codes; secrets live in encrypted storage."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_security",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("secret_reference", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("pending_expires", sa.Integer(), nullable=False),
        sa.Column("last_counter", sa.Integer(), nullable=False),
        sa.Column("recovery_hashes", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("user_security")
