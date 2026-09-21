from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "event_key", name="uq_notifications_user_event_key"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    event_key: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(String(240))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[UUID | None]
    read_at: Mapped[datetime | None]


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_notification_preferences_user_category"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    category: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class NotificationDeliveryAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("notification_id", "attempt_no", name="uq_notification_attempt_number"),
        CheckConstraint("attempt_no > 0", name="positive_attempt_number"),
        Index("ix_notification_attempts_status", "status", "created_at"),
        Index("ix_notification_attempts_retry", "status", "next_retry_at"),
    )

    notification_id: Mapped[UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="RESTRICT")
    )
    attempt_no: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None]
    next_retry_at: Mapped[datetime | None]
