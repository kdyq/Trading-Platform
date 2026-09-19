"""add market search indexes

Revision ID: b48271ca3e5d
Revises: 9a4d0ef137b2
"""

import sqlalchemy as sa

from alembic import op

revision: str = "b48271ca3e5d"
down_revision: str | None = "9a4d0ef137b2"
branch_labels: str | None = None
depends_on: str | None = None

PUBLIC = "deleted_at IS NULL AND status IN ('on_sale', 'reserved', 'sold')"


def upgrade() -> None:
    op.create_index(
        "ix_products_public_newest",
        "products",
        [sa.text("published_at DESC"), "id"],
        unique=False,
        postgresql_where=sa.text(PUBLIC),
    )
    op.create_index(
        "ix_products_public_category_price",
        "products",
        ["category_id", "price", "id"],
        unique=False,
        postgresql_where=sa.text(PUBLIC),
    )
    op.create_index(
        "ix_products_public_campus_price",
        "products",
        ["campus_id", "price", "id"],
        unique=False,
        postgresql_where=sa.text(PUBLIC),
    )
    op.create_index(
        "ix_favorites_user_created",
        "favorites",
        ["user_id", sa.text("created_at DESC"), "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_favorites_user_created", table_name="favorites")
    op.drop_index(
        "ix_products_public_campus_price",
        table_name="products",
        postgresql_where=sa.text(PUBLIC),
    )
    op.drop_index(
        "ix_products_public_category_price",
        table_name="products",
        postgresql_where=sa.text(PUBLIC),
    )
    op.drop_index(
        "ix_products_public_newest",
        table_name="products",
        postgresql_where=sa.text(PUBLIC),
    )
