from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuditExportJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_export_jobs"
    __table_args__ = (
        Index("ix_audit_export_jobs_actor_created", "actor_id", "created_at"),
        Index("ix_audit_export_jobs_status", "status"),
    )

    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(24), default="queued", server_default="queued")
    filters: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    object_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    expires_at: Mapped[datetime]
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None]
