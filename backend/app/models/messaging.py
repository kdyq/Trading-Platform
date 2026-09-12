from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "buyer_id", "seller_id", name="uq_conversations_product_parties"
        ),
        CheckConstraint("buyer_id <> seller_id", name="distinct_parties"),
        Index("ix_conversations_buyer_updated", "buyer_id", "updated_at"),
        Index("ix_conversations_seller_updated", "seller_id", "updated_at"),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    buyer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    seller_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    last_message_at: Mapped[datetime | None]

    messages: Mapped[list[Message]] = relationship(back_populates="conversation")


class Message(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "sender_id", "client_message_id", name="uq_messages_sender_client_message"
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    client_message_id: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    recalled_at: Mapped[datetime | None]

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
