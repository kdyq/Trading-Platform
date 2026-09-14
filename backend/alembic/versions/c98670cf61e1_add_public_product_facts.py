"""add public product facts

Revision ID: c98670cf61e1
Revises: 4c8e31a77b24
"""

import sqlalchemy as sa

from alembic import op

revision: str = "c98670cf61e1"
down_revision: str | None = "4c8e31a77b24"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "condition",
            sa.Enum(
                "new",
                "like_new",
                "good",
                "fair",
                name="product_condition",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="good",
            nullable=False,
        ),
    )
    op.add_column(
        "products",
        sa.Column("is_negotiable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("view_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_products_view_count_nonnegative"), "products", "view_count >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_products_view_count_nonnegative"), "products", type_="check")
    op.drop_column("products", "view_count")
    op.drop_column("products", "is_negotiable")
    op.drop_column("products", "condition")
