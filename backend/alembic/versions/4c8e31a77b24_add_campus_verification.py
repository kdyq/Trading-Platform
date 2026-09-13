"""add campus verification configuration and appeals

Revision ID: 4c8e31a77b24
Revises: da90b108fc44
Create Date: 2026-09-13 17:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4c8e31a77b24"
down_revision: str | None = "da90b108fc44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "school_email_domains",
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column(
            "allow_subdomains",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "domain = lower(domain)",
            name="ck_school_email_domains_domain_lowercase",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_email_domains_school_id_schools",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_school_email_domains"),
        sa.UniqueConstraint("domain", name="uq_school_email_domains_domain"),
    )
    op.create_index("ix_school_email_domains_school_id", "school_email_domains", ["school_id"])

    op.create_table(
        "campus_verification_appeals",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("campus_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(8), server_default="pending", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("material_key", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_campus_verification_appeals_campus_appeal_status",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_campus_verification_appeals_material_size_positive",
        ),
        sa.ForeignKeyConstraint(
            ["campus_id"],
            ["campuses.id"],
            name="fk_campus_verification_appeals_campus_id_campuses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["users.id"],
            name="fk_campus_verification_appeals_reviewer_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_campus_verification_appeals_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_campus_verification_appeals"),
        sa.UniqueConstraint("material_key", name="uq_campus_verification_appeals_material_key"),
    )
    op.create_index(
        "ix_campus_verification_appeals_user_id",
        "campus_verification_appeals",
        ["user_id"],
    )
    op.create_index(
        "ix_campus_verification_appeals_status",
        "campus_verification_appeals",
        ["status"],
    )
    op.create_index(
        "ix_campus_verification_appeals_retention_until",
        "campus_verification_appeals",
        ["retention_until"],
    )
    op.create_index(
        "uq_campus_verification_appeals_pending_user",
        "campus_verification_appeals",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_campus_verification_appeals_pending_user",
        table_name="campus_verification_appeals",
    )
    op.drop_index(
        "ix_campus_verification_appeals_retention_until",
        table_name="campus_verification_appeals",
    )
    op.drop_index(
        "ix_campus_verification_appeals_status",
        table_name="campus_verification_appeals",
    )
    op.drop_index(
        "ix_campus_verification_appeals_user_id",
        table_name="campus_verification_appeals",
    )
    op.drop_table("campus_verification_appeals")
    op.drop_index("ix_school_email_domains_school_id", table_name="school_email_domains")
    op.drop_table("school_email_domains")
