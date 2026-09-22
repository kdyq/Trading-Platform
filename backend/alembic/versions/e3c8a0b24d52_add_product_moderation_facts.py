"""add product moderation facts

Revision ID: e3c8a0b24d52
Revises: d2b7f9a13c41
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3c8a0b24d52"
down_revision: str | None = "d2b7f9a13c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("moderation_reason_code", sa.String(64), nullable=True))
    op.add_column("products", sa.Column("moderation_public_note", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("hidden_from_status", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "hidden_from_status")
    op.drop_column("products", "moderation_public_note")
    op.drop_column("products", "moderation_reason_code")
