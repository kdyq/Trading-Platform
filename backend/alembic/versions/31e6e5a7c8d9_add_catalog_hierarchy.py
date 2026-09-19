"""add catalog hierarchy and ordering

Revision ID: 31e6e5a7c8d9
Revises: c98670cf61e1
"""

import sqlalchemy as sa

from alembic import op

revision: str = "31e6e5a7c8d9"
down_revision: str | None = "c98670cf61e1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("slug", sa.String(length=64), nullable=True))
    op.add_column(
        "categories",
        sa.Column("level", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.execute(sa.text("UPDATE categories SET slug = code WHERE slug IS NULL"))
    op.alter_column("categories", "slug", nullable=False)
    op.create_unique_constraint(op.f("uq_categories_slug"), "categories", ["slug"])
    op.create_check_constraint(
        op.f("ck_categories_level_supported"), "categories", "level BETWEEN 0 AND 1"
    )
    op.create_check_constraint(
        op.f("ck_categories_level_matches_parent"),
        "categories",
        "(level = 0 AND parent_id IS NULL) OR (level = 1 AND parent_id IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_categories_parent_not_self"),
        "categories",
        "parent_id IS NULL OR parent_id <> id",
    )
    op.add_column(
        "campuses",
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_campuses_display_order_nonnegative"), "campuses", "display_order >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_campuses_display_order_nonnegative"), "campuses", type_="check")
    op.drop_column("campuses", "display_order")
    op.drop_constraint(op.f("ck_categories_parent_not_self"), "categories", type_="check")
    op.drop_constraint(op.f("ck_categories_level_matches_parent"), "categories", type_="check")
    op.drop_constraint(op.f("ck_categories_level_supported"), "categories", type_="check")
    op.drop_constraint(op.f("uq_categories_slug"), "categories", type_="unique")
    op.drop_column("categories", "level")
    op.drop_column("categories", "slug")
