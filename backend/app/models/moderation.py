from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, VersionMixin


class ModerationTargetType(StrEnum):
    USER = "user"
    PRODUCT = "product"
    MESSAGE = "message"
    ORDER = "order"
    REVIEW = "review"


class ReportStatus(StrEnum):
    OPEN = "open"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    WITHDRAWN = "withdrawn"
    APPEALED = "appealed"


class ModerationAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    HIDE = "hide"
    RESTORE = "restore"
    WARN = "warn"
    SUSPEND = "suspend"


class Report(UUIDPrimaryKeyMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id",
            "target_type",
            "target_id",
            "reason_code",
            name="uq_reports_key",
        ),
        Index("ix_reports_status_created", "status", "created_at"),
        Index("ix_reports_target", "target_type", "target_id"),
    )

    reporter_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    target_type: Mapped[ModerationTargetType] = mapped_column(
        Enum(
            ModerationTargetType,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="moderation_target_type",
        )
    )
    target_id: Mapped[UUID]
    reason_code: Mapped[str] = mapped_column(String(64))
    details: Mapped[str | None] = mapped_column(Text)
    public_result: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None]
    withdrawn_at: Mapped[datetime | None]
    status: Mapped[ReportStatus] = mapped_column(
        Enum(
            ReportStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="report_status",
        ),
        default=ReportStatus.OPEN,
        server_default=ReportStatus.OPEN.value,
    )


class ReportEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "report_evidence"
    __table_args__ = (
        UniqueConstraint("report_id", "sha256", name="uq_report_evidence_content"),
        Index("ix_report_evidence_report_created", "report_id", "created_at"),
    )

    report_id: Mapped[UUID] = mapped_column(ForeignKey("reports.id", ondelete="RESTRICT"))
    uploader_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))


class ReportEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "report_events"
    __table_args__ = (Index("ix_report_events_report_created", "report_id", "created_at"),)

    report_id: Mapped[UUID] = mapped_column(ForeignKey("reports.id", ondelete="RESTRICT"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    from_status: Mapped[ReportStatus | None] = mapped_column(
        Enum(
            ReportStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="report_event_from_status",
        )
    )
    to_status: Mapped[ReportStatus] = mapped_column(
        Enum(
            ReportStatus,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="report_event_to_status",
        )
    )
    public_note: Mapped[str | None] = mapped_column(Text)
    event_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class ModerationRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "moderation_records"
    __table_args__ = (Index("ix_moderation_records_target", "target_type", "target_id"),)

    report_id: Mapped[UUID | None] = mapped_column(ForeignKey("reports.id", ondelete="RESTRICT"))
    moderator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    target_type: Mapped[ModerationTargetType] = mapped_column(
        Enum(
            ModerationTargetType,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="moderation_record_target_type",
        )
    )
    target_id: Mapped[UUID]
    action: Mapped[ModerationAction] = mapped_column(
        Enum(
            ModerationAction,
            values_callable=lambda members: [member.value for member in members],
            native_enum=False,
            create_constraint=True,
            name="moderation_action",
        )
    )
    reason: Mapped[str] = mapped_column(Text)
    action_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_audit_logs_request_id"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
    )

    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    request_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(96))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID | None]
    audit_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
