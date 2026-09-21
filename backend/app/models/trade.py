from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
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
    SELLER_DELIVERED = "seller_delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    DISPUTED = "disputed"


class CreditEventType(StrEnum):
    ORDER_COMPLETED = "order_completed"
    REVIEW_RECEIVED = "review_received"
    MODERATION_ADJUSTMENT = "moderation_adjustment"


class MeetingProposalStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


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
                "status IN ('accepted', 'scheduled', 'seller_delivered', 'disputed')"
            ),
        ),
        Index(
            "uq_orders_open_buyer_product",
            "product_id",
            "buyer_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending_seller_confirmation', 'accepted', 'scheduled', "
                "'seller_delivered', 'disputed')"
            ),
        ),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    seller_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    product_title_snapshot: Mapped[str] = mapped_column(String(120))
    campus_name_snapshot: Mapped[str] = mapped_column(String(120))
    buyer_display_name_snapshot: Mapped[str] = mapped_column(String(80))
    seller_display_name_snapshot: Mapped[str] = mapped_column(String(80))
    payment_mode: Mapped[str] = mapped_column(
        String(24), default="offline", server_default="offline"
    )
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
    seller_delivered_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    cancellation_reason_code: Mapped[str | None] = mapped_column(String(64))
    cancellation_note: Mapped[str | None] = mapped_column(Text)
    disputed_at: Mapped[datetime | None]
    dispute_reason_code: Mapped[str | None] = mapped_column(String(64))
    dispute_details: Mapped[str | None] = mapped_column(Text)

    events: Mapped[list[OrderEvent]] = relationship(back_populates="order")
    reviews: Mapped[list[Review]] = relationship(back_populates="order")
    meeting_proposals: Mapped[list[OrderMeetingProposal]] = relationship(back_populates="order")
    commands: Mapped[list[OrderCommand]] = relationship(back_populates="order")


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


class OrderMeetingProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_meeting_proposals"
    __table_args__ = (
        Index("ix_order_meeting_proposals_order_created", "order_id", "created_at"),
        CheckConstraint("length(location_text) BETWEEN 2 AND 200", name="location_length"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    proposer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    proposed_for: Mapped[datetime]
    location_text: Mapped[str] = mapped_column(String(200))
    status: Mapped[MeetingProposalStatus] = mapped_column(
        Enum(
            MeetingProposalStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="meeting_proposal_status",
        ),
        default=MeetingProposalStatus.PENDING,
        server_default=MeetingProposalStatus.PENDING.value,
    )
    buyer_confirmed_at: Mapped[datetime | None]
    seller_confirmed_at: Mapped[datetime | None]

    order: Mapped[Order] = relationship(back_populates="meeting_proposals")


class OrderCommand(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_commands"
    __table_args__ = (
        UniqueConstraint("actor_id", "client_action_id", name="uq_order_commands_actor_action"),
        Index("ix_order_commands_order_created", "order_id", "created_at"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    client_action_id: Mapped[str] = mapped_column(String(64))
    command: Mapped[str] = mapped_column(String(48))
    payload_hash: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("order_events.id", ondelete="RESTRICT")
    )
    result_id: Mapped[UUID | None]

    event: Mapped[OrderEvent | None] = relationship()

    order: Mapped[Order] = relationship(back_populates="commands")


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
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    hidden_at: Mapped[datetime | None]

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
