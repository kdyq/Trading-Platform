"""add order command result references

Revision ID: c8a31e7f4b2d
Revises: b7f2d9c41a6e
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8a31e7f4b2d"
down_revision: str | None = "b7f2d9c41a6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("order_commands", sa.Column("result_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("order_commands", "result_id")
