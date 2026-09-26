"""add private appeal evidence

Revision ID: c7a29f6d8b13
Revises: b6d14e8f032a
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a29f6d8b13"
down_revision: str | None = "b6d14e8f032a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_appeal_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("appeal_id", sa.Uuid(), nullable=False),
        sa.Column("uploader_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["appeal_id"],
            ["report_appeals.id"],
            name=op.f("fk_report_appeal_evidence_appeal_id_report_appeals"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["users.id"],
            name=op.f("fk_report_appeal_evidence_uploader_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_appeal_evidence")),
        sa.UniqueConstraint("appeal_id", "sha256", name="uq_appeal_evidence_content"),
        sa.UniqueConstraint("object_key", name=op.f("uq_report_appeal_evidence_object_key")),
    )
    op.create_index(
        "ix_appeal_evidence_appeal_created", "report_appeal_evidence", ["appeal_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_appeal_evidence_appeal_created", table_name="report_appeal_evidence")
    op.drop_table("report_appeal_evidence")
