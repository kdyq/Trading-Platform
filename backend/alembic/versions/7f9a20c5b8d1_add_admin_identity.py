"""add admin username and first-login password gate

Revision ID: 7f9a20c5b8d1
Revises: c7a29f6d8b13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7f9a20c5b8d1"
down_revision: str | None = "c7a29f6d8b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_users_username",
        "users",
        [sa.text("lower(username)")],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_username", table_name="users")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "username")
