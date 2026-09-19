"""add product image uploads

Revision ID: 6c2b917ef4a1
Revises: 31e6e5a7c8d9
"""

import sqlalchemy as sa

from alembic import op

revision: str = "6c2b917ef4a1"
down_revision: str | None = "31e6e5a7c8d9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "product_image_uploads",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("original_key", sa.String(length=512), nullable=False),
        sa.Column("thumbnail_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "temporary",
                "confirmed",
                "deleted",
                name="product_image_upload_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="temporary",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "width > 0 AND height > 0",
            name=op.f("ck_product_image_uploads_dimensions_positive"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_product_image_uploads_size_positive")),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_product_image_uploads_owner_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_image_uploads")),
        sa.UniqueConstraint("original_key", name="uq_product_image_uploads_original_key"),
        sa.UniqueConstraint("thumbnail_key", name="uq_product_image_uploads_thumbnail_key"),
    )
    op.create_index(
        "ix_product_image_uploads_owner_status",
        "product_image_uploads",
        ["owner_id", "status"],
    )
    op.create_index(
        "ix_product_image_uploads_status_expires",
        "product_image_uploads",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_image_uploads_status_expires", table_name="product_image_uploads")
    op.drop_index("ix_product_image_uploads_owner_status", table_name="product_image_uploads")
    op.drop_table("product_image_uploads")
