from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin


class ProductStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ON_SALE = "on_sale"
    RESERVED = "reserved"
    SOLD = "sold"
    REJECTED = "rejected"
    HIDDEN = "hidden"
    DELETED = "deleted"


class ProductCondition(StrEnum):
    NEW = "new"
    LIKE_NEW = "like_new"
    GOOD = "good"
    FAIR = "fair"


class ProductImageUploadStatus(StrEnum):
    TEMPORARY = "temporary"
    CONFIRMED = "confirmed"
    DELETED = "deleted"


class Category(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("code", name="uq_categories_code"),
        UniqueConstraint("slug", name="uq_categories_slug"),
        CheckConstraint("display_order >= 0", name="display_order_nonnegative"),
        CheckConstraint("level BETWEEN 0 AND 1", name="level_supported"),
        CheckConstraint(
            "(level = 0 AND parent_id IS NULL) OR (level = 1 AND parent_id IS NOT NULL)",
            name="level_matches_parent",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="parent_not_self"),
    )

    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(80))
    level: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    display_order: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))

    parent: Mapped[Category | None] = relationship(
        remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")
    products: Mapped[list[Product]] = relationship(back_populates="category")


class Product(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="price_nonnegative"),
        CheckConstraint(
            "original_price IS NULL OR original_price >= 0",
            name="original_price_nonnegative",
        ),
        Index("ix_products_seller_status", "seller_id", "status"),
        Index("ix_products_campus_status", "campus_id", "status"),
        Index("ix_products_category_status", "category_id", "status"),
        Index("ix_products_created_at", "created_at"),
        Index(
            "ix_products_public_newest",
            text("published_at DESC"),
            "id",
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('on_sale', 'reserved', 'sold')"
            ),
        ),
        Index(
            "ix_products_public_category_price",
            "category_id",
            "price",
            "id",
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('on_sale', 'reserved', 'sold')"
            ),
        ),
        Index(
            "ix_products_public_campus_price",
            "campus_id",
            "price",
            "id",
            postgresql_where=text(
                "deleted_at IS NULL AND status IN ('on_sale', 'reserved', 'sold')"
            ),
        ),
    )

    seller_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    campus_id: Mapped[UUID] = mapped_column(ForeignKey("campuses.id", ondelete="RESTRICT"))
    category_id: Mapped[UUID] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    condition: Mapped[ProductCondition] = mapped_column(
        Enum(
            ProductCondition,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="product_condition",
        ),
        default=ProductCondition.GOOD,
        server_default=ProductCondition.GOOD.value,
    )
    is_negotiable: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    view_count: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    delivery_notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(
            ProductStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="product_status",
        ),
        default=ProductStatus.DRAFT,
        server_default=ProductStatus.DRAFT.value,
    )
    published_at: Mapped[datetime | None]
    reserved_at: Mapped[datetime | None]
    sold_at: Mapped[datetime | None]
    moderation_reason_code: Mapped[str | None] = mapped_column(String(64))
    moderation_public_note: Mapped[str | None] = mapped_column(Text)
    hidden_from_status: Mapped[str | None] = mapped_column(String(32))

    category: Mapped[Category] = relationship(back_populates="products")
    images: Mapped[list[ProductImage]] = relationship(back_populates="product")


class ProductImage(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("object_key", name="uq_product_images_object_key"),
        CheckConstraint("display_order >= 0", name="display_order_nonnegative"),
        Index(
            "uq_product_images_active_position",
            "product_id",
            "display_order",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(512))
    thumbnail_object_key: Mapped[str] = mapped_column(String(512))
    alt_text: Mapped[str | None] = mapped_column(String(255))
    display_order: Mapped[int] = mapped_column(default=0, server_default=text("0"))

    product: Mapped[Product] = relationship(back_populates="images")


class ProductImageUpload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_image_uploads"
    __table_args__ = (
        UniqueConstraint("original_key", name="uq_product_image_uploads_original_key"),
        UniqueConstraint("thumbnail_key", name="uq_product_image_uploads_thumbnail_key"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
        Index("ix_product_image_uploads_owner_status", "owner_id", "status"),
        Index("ix_product_image_uploads_status_expires", "status", "expires_at"),
    )

    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    original_key: Mapped[str] = mapped_column(String(512))
    thumbnail_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int]
    width: Mapped[int]
    height: Mapped[int]
    status: Mapped[ProductImageUploadStatus] = mapped_column(
        Enum(
            ProductImageUploadStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="product_image_upload_status",
        ),
        default=ProductImageUploadStatus.TEMPORARY,
        server_default=ProductImageUploadStatus.TEMPORARY.value,
    )
    expires_at: Mapped[datetime]
    confirmed_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class Favorite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_favorites_user_product"),
        Index("ix_favorites_product_id", "product_id"),
        Index("ix_favorites_user_created", "user_id", text("created_at DESC"), "id"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
