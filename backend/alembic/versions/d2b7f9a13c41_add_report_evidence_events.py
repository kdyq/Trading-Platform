"""add report evidence and events

Revision ID: d2b7f9a13c41
Revises: c1a8e4d72f90
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2b7f9a13c41"
down_revision: str | None = "c1a8e4d72f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPORT_STATUSES = ("open", "reviewing", "resolved", "dismissed", "withdrawn", "appealed")


def report_status_enum(name: str) -> sa.Enum:
    return sa.Enum(*REPORT_STATUSES, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.execute("ALTER TABLE reports DROP CONSTRAINT ck_reports_report_status")
    op.execute(
        "ALTER TABLE reports ADD CONSTRAINT ck_reports_report_status "
        "CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed', "
        "'withdrawn', 'appealed'))"
    )
    op.add_column("reports", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("reports", sa.Column("public_result", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "report_evidence",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
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
            ondelete="RESTRICT",
            name=op.f("fk_report_evidence_report_id_reports"),
        ),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_report_evidence_uploader_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_evidence")),
        sa.UniqueConstraint("object_key", name=op.f("uq_report_evidence_object_key")),
        sa.UniqueConstraint("report_id", "sha256", name="uq_report_evidence_content"),
    )
    op.create_index(
        "ix_report_evidence_report_created",
        "report_evidence",
        ["report_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "report_events",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("from_status", report_status_enum("report_event_from_status"), nullable=True),
        sa.Column("to_status", report_status_enum("report_event_to_status"), nullable=False),
        sa.Column("public_note", sa.Text(), nullable=True),
        sa.Column("event_data", sa.JSON(), nullable=False),
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
            ["actor_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_report_events_actor_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            ondelete="RESTRICT",
            name=op.f("fk_report_events_report_id_reports"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_events")),
    )
    op.create_index(
        "ix_report_events_report_created",
        "report_events",
        ["report_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_report_events_report_created", table_name="report_events")
    op.drop_table("report_events")
    op.drop_index("ix_report_evidence_report_created", table_name="report_evidence")
    op.drop_table("report_evidence")
    op.drop_column("reports", "withdrawn_at")
    op.drop_column("reports", "resolved_at")
    op.drop_column("reports", "public_result")
    op.drop_column("reports", "version")
    op.execute("ALTER TABLE reports DROP CONSTRAINT ck_reports_report_status")
    op.execute(
        "ALTER TABLE reports ADD CONSTRAINT ck_reports_report_status "
        "CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed'))"
    )
