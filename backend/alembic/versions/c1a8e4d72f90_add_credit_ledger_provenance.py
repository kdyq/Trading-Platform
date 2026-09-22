"""add credit ledger provenance

Revision ID: c1a8e4d72f90
Revises: c8a31e7f4b2d
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1a8e4d72f90"
down_revision: str | None = "c8a31e7f4b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE credit_ledgers DROP CONSTRAINT ck_credit_ledgers_credit_event_type")
    op.execute(
        "ALTER TABLE credit_ledgers ADD CONSTRAINT ck_credit_ledgers_credit_event_type "
        "CHECK (event_type IN ('order_completed', 'review_received', "
        "'report_violation', 'penalty_reversal', 'moderation_adjustment'))"
    )
    op.add_column(
        "credit_ledgers",
        sa.Column("source_type", sa.String(length=48), server_default="legacy", nullable=False),
    )
    op.add_column(
        "credit_ledgers",
        sa.Column("rule_version", sa.String(length=24), server_default="v1", nullable=False),
    )
    op.add_column("credit_ledgers", sa.Column("actor_id", sa.Uuid(), nullable=True))
    op.add_column("credit_ledgers", sa.Column("reversal_of_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_credit_ledgers_actor_id_users"),
        "credit_ledgers",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_credit_ledgers_reversal_of_id_credit_ledgers"),
        "credit_ledgers",
        "credit_ledgers",
        ["reversal_of_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column("credit_ledgers", "source_type", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_credit_ledgers_reversal_of_id_credit_ledgers"),
        "credit_ledgers",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_credit_ledgers_actor_id_users"),
        "credit_ledgers",
        type_="foreignkey",
    )
    op.drop_column("credit_ledgers", "reversal_of_id")
    op.drop_column("credit_ledgers", "actor_id")
    op.drop_column("credit_ledgers", "rule_version")
    op.drop_column("credit_ledgers", "source_type")
    op.execute("ALTER TABLE credit_ledgers DROP CONSTRAINT ck_credit_ledgers_credit_event_type")
    op.execute(
        "ALTER TABLE credit_ledgers ADD CONSTRAINT ck_credit_ledgers_credit_event_type "
        "CHECK (event_type IN ('order_completed', 'review_received', 'moderation_adjustment'))"
    )
