"""allow new reports while an earlier case is appealed

Revision ID: b6d14e8f032a
Revises: a5e0c2d46f74
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6d14e8f032a"
down_revision: str | None = "a5e0c2d46f74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_reports_active_key", table_name="reports")
    op.create_index(
        "uq_reports_active_key",
        "reports",
        ["reporter_id", "target_type", "target_id", "reason_code"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'reviewing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_reports_active_key", table_name="reports")
    op.create_index(
        "uq_reports_active_key",
        "reports",
        ["reporter_id", "target_type", "target_id", "reason_code"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'reviewing', 'appealed')"),
    )
