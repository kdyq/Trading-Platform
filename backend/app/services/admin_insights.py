from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.admin import AuditExportJob
from app.models.catalog import Product, ProductStatus
from app.models.identity import CampusVerification, User, UserSession
from app.models.moderation import AuditLog, Report
from app.models.trade import Order, OrderStatus
from app.schemas.admin import (
    AuditEntryAdmin,
    AuditExportList,
    AuditExportSummary,
    AuditListAdmin,
    DashboardMetricsAdmin,
)
from app.services.admin import AdminService
from app.services.auth import AuthContext

REDACT_KEYS = (
    "password",
    "token",
    "secret",
    "email",
    "ip",
    "object_key",
    "material_key",
    "evidence",
    "message",
    "content",
)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")


def redacted_data(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[已脱敏]"
            if any(part in str(key).lower() for part in REDACT_KEYS)
            else redacted_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redacted_data(item) for item in value]
    if isinstance(value, str):
        return EMAIL_PATTERN.sub("[已脱敏邮箱]", value)
    return value


def checked_window(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise AppError(status_code=422, code="timezone_required", message="时间必须包含时区")
    start = starts_at.astimezone(UTC)
    end = ends_at.astimezone(UTC)
    if (
        start >= end
        or end - start > timedelta(days=90)
        or end > datetime.now(UTC) + timedelta(minutes=1)
    ):
        raise AppError(status_code=422, code="invalid_time_window", message="时间区间应在 90 天内")
    return start, end


class AdminInsightsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.admin = AdminService(session, settings)

    async def dashboard(
        self, context: AuthContext, starts_at: datetime, ends_at: datetime
    ) -> DashboardMetricsAdmin:
        await self.admin.require(context, "dashboard:read")
        start, end = checked_window(starts_at, ends_at)
        now = datetime.now(UTC)

        async def count(statement: Any) -> int:
            return int(await self.session.scalar(statement) or 0)

        return DashboardMetricsAdmin(
            starts_at=start,
            ends_at=end,
            registered_users=await count(
                select(func.count())
                .select_from(User)
                .where(User.created_at >= start, User.created_at < end, User.deleted_at.is_(None))
            ),
            verified_campus=await count(
                select(func.count())
                .select_from(CampusVerification)
                .where(
                    CampusVerification.verified_at >= start, CampusVerification.verified_at < end
                )
            ),
            published_products=await count(
                select(func.count())
                .select_from(Product)
                .where(Product.published_at >= start, Product.published_at < end)
            ),
            completed_orders=await count(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.status == OrderStatus.COMPLETED,
                    Order.completed_at >= start,
                    Order.completed_at < end,
                )
            ),
            submitted_reports=await count(
                select(func.count())
                .select_from(Report)
                .where(Report.created_at >= start, Report.created_at < end)
            ),
            pending_products_now=await count(
                select(func.count())
                .select_from(Product)
                .where(Product.status == ProductStatus.PENDING_REVIEW, Product.deleted_at.is_(None))
            ),
            active_sessions_now=await count(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.revoked_at.is_(None), UserSession.expires_at > now)
            ),
        )

    async def audit(
        self,
        context: AuthContext,
        *,
        starts_at: datetime,
        ends_at: datetime,
        action: str | None,
        actor_id: UUID | None,
        target_type: str | None,
        page: int,
        page_size: int,
    ) -> AuditListAdmin:
        await self.admin.require(context, "audit:read")
        start, end = checked_window(starts_at, ends_at)
        filters = [AuditLog.created_at >= start, AuditLog.created_at < end]
        if action:
            filters.append(AuditLog.action == action)
        if actor_id:
            filters.append(AuditLog.actor_id == actor_id)
        if target_type:
            filters.append(AuditLog.target_type == target_type)
        total = int(
            await self.session.scalar(select(func.count()).select_from(AuditLog).where(*filters))
            or 0
        )
        rows = (
            await self.session.scalars(
                select(AuditLog)
                .where(*filters)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return AuditListAdmin(
            items=[
                AuditEntryAdmin(
                    id=row.id,
                    actor_id=row.actor_id,
                    action=row.action,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    audit_data=cast(dict[str, object], redacted_data(row.audit_data)),
                    created_at=row.created_at,
                )
                for row in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def create_export(
        self,
        context: AuthContext,
        *,
        starts_at: datetime,
        ends_at: datetime,
        action: str | None,
        reason: str,
    ) -> AuditExportSummary:
        await self.admin.require(context, "audit:export", high_risk=True)
        start, end = checked_window(starts_at, ends_at)
        now = datetime.now(UTC)
        job = AuditExportJob(
            id=uuid4(),
            actor_id=context.user.id,
            status="queued",
            filters={
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "action": action,
                "reason": reason,
            },
            object_key=None,
            expires_at=now + timedelta(hours=1),
            revoked=False,
            failure_code=None,
            completed_at=None,
        )
        self.session.add(job)
        await self.admin._audit(
            context.user.id,
            "audit.export.requested",
            "audit_export",
            job.id,
            {"starts_at": start.isoformat(), "ends_at": end.isoformat(), "reason": reason},
        )
        await self.session.flush()
        return self._job_summary(job)

    async def get_export(self, context: AuthContext, job_id: UUID) -> AuditExportSummary:
        job = await self._authorized_job(context, job_id)
        return self._job_summary(job)

    async def list_exports(
        self, context: AuthContext, *, page: int, page_size: int
    ) -> AuditExportList:
        await self.admin.require(context, "audit:export")
        owner = AuditExportJob.actor_id == context.user.id
        total = int(
            await self.session.scalar(select(func.count()).select_from(AuditExportJob).where(owner))
            or 0
        )
        rows = (
            await self.session.scalars(
                select(AuditExportJob)
                .where(owner)
                .order_by(AuditExportJob.created_at.desc(), AuditExportJob.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return AuditExportList(
            items=[self._job_summary(job) for job in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def revoke_export(self, context: AuthContext, job_id: UUID) -> AuditExportSummary:
        await self.admin.require(context, "audit:export", high_risk=True)
        job = await self._authorized_job(context, job_id, lock=True)
        job.revoked = True
        await self.admin._audit(
            context.user.id,
            "audit.export.revoked",
            "audit_export",
            job.id,
            {"reason": "operator_revoked"},
        )
        await self.session.flush()
        return self._job_summary(job)

    async def download_export(self, context: AuthContext, job_id: UUID) -> Path:
        job = await self._authorized_job(context, job_id)
        if job.revoked or job.expires_at <= datetime.now(UTC):
            raise AppError(status_code=410, code="export_unavailable", message="导出已过期或已撤销")
        if job.status != "ready" or job.object_key is None:
            raise AppError(status_code=409, code="export_not_ready", message="导出尚未完成")
        path = self.settings.resolved_private_storage_root / "exports" / job.object_key
        if not path.is_file():
            raise AppError(status_code=404, code="export_file_missing", message="导出文件不存在")
        return path

    async def _authorized_job(
        self, context: AuthContext, job_id: UUID, *, lock: bool = False
    ) -> AuditExportJob:
        await self.admin.require(context, "audit:export")
        query = select(AuditExportJob).where(
            AuditExportJob.id == job_id, AuditExportJob.actor_id == context.user.id
        )
        if lock:
            query = query.with_for_update()
        job = await self.session.scalar(query)
        if job is None:
            raise AppError(status_code=404, code="export_not_found", message="导出任务不存在")
        return job

    @staticmethod
    def _job_summary(job: AuditExportJob) -> AuditExportSummary:
        expired_unfinished = job.expires_at <= datetime.now(UTC) and job.status in {
            "queued",
            "processing",
        }
        return AuditExportSummary(
            id=job.id,
            status="failed" if expired_unfinished else job.status,
            created_at=job.created_at,
            expires_at=job.expires_at,
            revoked=job.revoked,
            failure_code="export_expired" if expired_unfinished else job.failure_code,
        )
