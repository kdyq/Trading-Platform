"""scope active reports and penalty provenance

Revision ID: a5e0c2d46f74
Revises: f4d9b1c35e63
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a5e0c2d46f74"
down_revision: str | None = "f4d9b1c35e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_ledgers", sa.Column("sequence_no", sa.BigInteger(), nullable=True))
    op.execute(
        """
        WITH numbered AS (
            SELECT id, row_number() OVER (
                PARTITION BY user_id ORDER BY created_at, id
            ) AS sequence_no
            FROM credit_ledgers
        )
        UPDATE credit_ledgers AS ledger
        SET sequence_no = numbered.sequence_no
        FROM numbered
        WHERE ledger.id = numbered.id
        """
    )
    op.alter_column("credit_ledgers", "sequence_no", nullable=False)
    op.create_unique_constraint(
        "uq_credit_ledgers_user_sequence", "credit_ledgers", ["user_id", "sequence_no"]
    )
    op.drop_index("ix_credit_ledgers_user_created", table_name="credit_ledgers")
    op.create_index("ix_credit_ledgers_user_created", "credit_ledgers", ["user_id", "sequence_no"])
    op.drop_constraint("uq_reports_key", "reports", type_="unique")
    op.create_index(
        "uq_reports_active_key",
        "reports",
        ["reporter_id", "target_type", "target_id", "reason_code"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'reviewing', 'appealed')"),
    )
    op.add_column("products", sa.Column("moderation_source_report_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("suspension_source_report_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_products_moderation_source_report_id_reports"),
        "products",
        "reports",
        ["moderation_source_report_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_users_suspension_source_report_id_reports"),
        "users",
        "reports",
        ["suspension_source_report_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_users_suspension_source_report_id_reports"), "users", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_products_moderation_source_report_id_reports"),
        "products",
        type_="foreignkey",
    )
    op.drop_column("users", "suspension_source_report_id")
    op.drop_column("products", "moderation_source_report_id")
    op.drop_index("uq_reports_active_key", table_name="reports")
    op.create_unique_constraint(
        "uq_reports_key",
        "reports",
        ["reporter_id", "target_type", "target_id", "reason_code"],
    )
    op.drop_index("ix_credit_ledgers_user_created", table_name="credit_ledgers")
    op.create_index("ix_credit_ledgers_user_created", "credit_ledgers", ["user_id", "created_at"])
    op.drop_constraint("uq_credit_ledgers_user_sequence", "credit_ledgers", type_="unique")
    op.drop_column("credit_ledgers", "sequence_no")
