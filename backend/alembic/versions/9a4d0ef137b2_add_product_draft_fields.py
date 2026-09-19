"""add product draft fields

Revision ID: 9a4d0ef137b2
Revises: 6c2b917ef4a1
"""

import sqlalchemy as sa

from alembic import op

revision: str = "9a4d0ef137b2"
down_revision: str | None = "6c2b917ef4a1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("original_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("products", sa.Column("delivery_notes", sa.Text(), nullable=True))
    op.create_check_constraint(
        op.f("ck_products_original_price_nonnegative"),
        "products",
        "original_price IS NULL OR original_price >= 0",
    )
    op.add_column(
        "product_images", sa.Column("thumbnail_object_key", sa.String(512), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE product_images SET thumbnail_object_key = object_key "
            "WHERE thumbnail_object_key IS NULL"
        )
    )
    op.alter_column("product_images", "thumbnail_object_key", nullable=False)


def downgrade() -> None:
    op.drop_column("product_images", "thumbnail_object_key")
    op.drop_constraint(op.f("ck_products_original_price_nonnegative"), "products", type_="check")
    op.drop_column("products", "delivery_notes")
    op.drop_column("products", "original_price")
