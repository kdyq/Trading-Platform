"""add report appeals

Revision ID: f4d9b1c35e63
Revises: e3c8a0b24d52
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4d9b1c35e63"
down_revision: str | None = "e3c8a0b24d52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE moderation_records DROP CONSTRAINT ck_moderation_records_moderation_action"
    )
    op.execute(
        "ALTER TABLE moderation_records ADD CONSTRAINT "
        "ck_moderation_records_moderation_action CHECK "
        "(action IN ('approve', 'reject', 'hide', 'restore', 'warn', 'suspend', "
        "'review', 'dismiss', 'reverse'))"
    )
    op.add_column("reports", sa.Column("subject_user_id", sa.Uuid(), nullable=True))
    op.add_column("reports", sa.Column("decision_moderator_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_reports_subject_user_id_users"),
        "reports",
        "users",
        ["subject_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_reports_decision_moderator_id_users"),
        "reports",
        "users",
        ["decision_moderator_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "report_appeals",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("appellant_id", sa.Uuid(), nullable=False),
        sa.Column("original_moderator_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_report_appeals_report_id_reports"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["appellant_id"],
            ["users.id"],
            name=op.f("fk_report_appeals_appellant_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["original_moderator_id"],
            ["users.id"],
            name=op.f("fk_report_appeals_original_moderator_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name=op.f("fk_report_appeals_reviewer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_appeals")),
        sa.UniqueConstraint("report_id", name="uq_report_appeals_report_id"),
    )


def downgrade() -> None:
    op.drop_table("report_appeals")
    op.drop_constraint(
        op.f("fk_reports_decision_moderator_id_users"), "reports", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_reports_subject_user_id_users"), "reports", type_="foreignkey")
    op.drop_column("reports", "decision_moderator_id")
    op.drop_column("reports", "subject_user_id")
    op.execute(
        "ALTER TABLE moderation_records DROP CONSTRAINT ck_moderation_records_moderation_action"
    )
    op.execute(
        "UPDATE moderation_records SET action = CASE "
        "WHEN action = 'review' THEN 'warn' "
        "WHEN action = 'dismiss' THEN 'reject' "
        "WHEN action = 'reverse' THEN 'restore' ELSE action END"
    )
    op.execute(
        "ALTER TABLE moderation_records ADD CONSTRAINT "
        "ck_moderation_records_moderation_action CHECK "
        "(action IN ('approve', 'reject', 'hide', 'restore', 'warn', 'suspend'))"
    )
