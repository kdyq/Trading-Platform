"""add asynchronous audit export jobs

Revision ID: 1c3e90d4a72b
Revises: 7f9a20c5b8d1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1c3e90d4a72b"
down_revision: str | None = "7f9a20c5b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_export_jobs",
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("object_key", sa.String(80), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_audit_export_jobs_actor_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_export_jobs"),
        sa.UniqueConstraint("object_key", name="uq_audit_export_jobs_object_key"),
    )
    op.create_index(
        "ix_audit_export_jobs_actor_created", "audit_export_jobs", ["actor_id", "created_at"]
    )
    op.create_index("ix_audit_export_jobs_status", "audit_export_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_audit_export_jobs_status", table_name="audit_export_jobs")
    op.drop_index("ix_audit_export_jobs_actor_created", table_name="audit_export_jobs")
    op.drop_table("audit_export_jobs")
