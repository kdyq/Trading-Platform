from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
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

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin


class OrderStatus(StrEnum):
    PENDING_SELLER_CONFIRMATION = "pending_seller_confirmation"
    ACCEPTED = "accepted"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DISPUTED = "disputed"


class CreditEventType(StrEnum):
    ORDER_COMPLETED = "order_completed"
    REVIEW_RECEIVED = "review_received"
    MODERATION_ADJUSTMENT = "moderation_adjustment"


class Order(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_orders_buyer_idempotency"),
        CheckConstraint("buyer_id <> seller_id", name="distinct_parties"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        Index("ix_orders_buyer_status", "buyer_id", "status"),
        Index("ix_orders_seller_status", "seller_id", "status"),
        Index(
            "uq_orders_active_product",
            "product_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_seller_confirmation', 'accepted', 'scheduled', 'disputed')"
            ),
        ),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    seller_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="order_status",
        ),
        default=OrderStatus.PENDING_SELLER_CONFIRMATION,
        server_default=OrderStatus.PENDING_SELLER_CONFIRMATION.value,
    )
    scheduled_for: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]

    events: Mapped[list[OrderEvent]] = relationship(back_populates="order")
    reviews: Mapped[list[Review]] = relationship(back_populates="order")


class OrderEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_events"
    __table_args__ = (Index("ix_order_events_order_created", "order_id", "created_at"),)

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    from_status: Mapped[OrderStatus | None] = mapped_column(
        Enum(
            OrderStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="order_event_from_status",
        )
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="order_event_to_status",
        )
    )
    note: Mapped[str | None] = mapped_column(Text)
    event_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)

    order: Mapped[Order] = relationship(back_populates="events")


class Review(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("order_id", "reviewer_id", name="uq_reviews_order_reviewer"),
        CheckConstraint("reviewer_id <> reviewee_id", name="distinct_parties"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        Index("ix_reviews_reviewee_id", "reviewee_id"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewee_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    rating: Mapped[int]
    content: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="reviews")


class CreditLedger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credit_ledgers"
    __table_args__ = (
        UniqueConstraint("user_id", "event_type", "reference_id", name="uq_credit_ledgers_source"),
        CheckConstraint("delta <> 0", name="delta_nonzero"),
        Index("ix_credit_ledgers_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    event_type: Mapped[CreditEventType] = mapped_column(
        Enum(
            CreditEventType,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="credit_event_type",
        )
    )
    reference_id: Mapped[UUID]
    delta: Mapped[int]
    balance_after: Mapped[int]
    reason: Mapped[str] = mapped_column(String(255))
