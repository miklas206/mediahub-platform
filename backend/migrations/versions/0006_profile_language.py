"""Keep each account's saved language on the user profile."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("preferred_language", sa.String(), nullable=False, server_default="en")
    )
    connection = op.get_bind()
    settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.JSON))
    users = sa.table(
        "users", sa.column("id", sa.String), sa.column("preferred_language", sa.String)
    )
    for key, value in connection.execute(
        sa.select(settings.c.key, settings.c.value).where(
            settings.c.key.startswith("user.preferences:")
        )
    ):
        if isinstance(value, dict) and value.get("language") == "da":
            connection.execute(
                users.update()
                .where(users.c.id == key.split(":", 1)[1])
                .values(preferred_language="da")
            )


def downgrade():
    op.drop_column("users", "preferred_language")
