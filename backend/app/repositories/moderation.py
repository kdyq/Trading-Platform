from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product, ProductStatus
from app.models.identity import Role, User, UserStatus, user_roles
from app.models.moderation import (
    AuditLog,
    ModerationAction,
    ModerationRecord,
    ModerationTargetType,
    Report,
    ReportAppeal,
    ReportAppealEvidence,
    ReportEvidence,
    ReportStatus,
)
from app.models.notification import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationPreference,
)


class SqlAlchemyModerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_role(self, user_id: UUID, roles: set[str]) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(user_roles.join(Role, user_roles.c.role_id == Role.id))
            .where(
                user_roles.c.user_id == user_id,
                Role.code.in_(roles),
                Role.deleted_at.is_(None),
            )
        )
        return bool(count)

    async def list_products(
        self, status: ProductStatus, *, page: int, page_size: int
    ) -> tuple[Sequence[tuple[Product, str]], int]:
        total = int(
            await self.session.scalar(
                select(func.count())
                .select_from(Product)
                .where(Product.status == status, Product.deleted_at.is_(None))
            )
            or 0
        )
        rows = await self.session.execute(
            select(Product, User.display_name)
            .join(User, User.id == Product.seller_id)
            .where(Product.status == status, Product.deleted_at.is_(None))
            .options(selectinload(Product.images))
            .order_by(Product.updated_at, Product.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [(row[0], row[1]) for row in rows], total

    async def get_product(self, product_id: UUID, *, lock: bool = False) -> Product | None:
        query = (
            select(Product)
            .where(Product.id == product_id, Product.deleted_at.is_(None))
            .options(selectinload(Product.images))
        )
        if lock:
            query = query.with_for_update()
        return cast(Product | None, await self.session.scalar(query))

    async def seller_name(self, seller_id: UUID) -> str:
        return str(await self.session.scalar(select(User.display_name).where(User.id == seller_id)))

    def record_decision(
        self,
        *,
        product: Product,
        moderator_id: UUID,
        action: ModerationAction,
        reason: str,
        request_id: str,
        before_status: ProductStatus,
    ) -> None:
        self.session.add(
            ModerationRecord(
                id=uuid4(),
                report_id=None,
                moderator_id=moderator_id,
                target_type=ModerationTargetType.PRODUCT,
                target_id=product.id,
                action=action,
                reason=reason,
                action_data={
                    "before_status": before_status.value,
                    "after_status": product.status.value,
                    "product_version": product.version,
                },
            )
        )
        self.session.add(
            AuditLog(
                id=uuid4(),
                actor_id=moderator_id,
                request_id=request_id,
                action=f"product.moderation.{action.value}",
                target_type="product",
                target_id=product.id,
                audit_data={
                    "reason": reason,
                    "before_status": before_status.value,
                    "after_status": product.status.value,
                },
            )
        )

    async def notify_seller(
        self, *, product: Product, action: str, title: str, summary: str
    ) -> None:
        enabled = await self.session.scalar(
            select(NotificationPreference.enabled).where(
                NotificationPreference.user_id == product.seller_id,
                NotificationPreference.category == "moderation",
            )
        )
        if enabled is False:
            return
        notification_id = uuid4()
        inserted = await self.session.scalar(
            insert(Notification)
            .values(
                id=notification_id,
                user_id=product.seller_id,
                event_key=f"product.moderation.{action}:{product.id}:{product.version}",
                category="moderation",
                title=title,
                summary=summary,
                target_type="product",
                target_id=product.id,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_event_key")
            .returning(Notification.id)
        )
        if inserted is not None:
            self.session.add(
                NotificationDeliveryAttempt(
                    id=uuid4(),
                    notification_id=notification_id,
                    attempt_no=1,
                    status="pending",
                    next_retry_at=datetime.now(UTC),
                )
            )

    async def list_reports(
        self, status: ReportStatus | None, *, page: int, page_size: int
    ) -> tuple[Sequence[Report], int]:
        query = select(Report)
        count_query = select(func.count()).select_from(Report)
        if status is not None:
            query = query.where(Report.status == status)
            count_query = count_query.where(Report.status == status)
        total = int(await self.session.scalar(count_query) or 0)
        items = list(
            await self.session.scalars(
                query.order_by(Report.created_at.desc(), Report.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    async def get_report(self, report_id: UUID, *, lock: bool = False) -> Report | None:
        query = select(Report).where(Report.id == report_id)
        if lock:
            query = query.with_for_update()
        return cast(Report | None, await self.session.scalar(query))

    async def report_evidence_ids(self, report_id: UUID) -> list[UUID]:
        return list(
            await self.session.scalars(
                select(ReportEvidence.id)
                .where(ReportEvidence.report_id == report_id)
                .order_by(ReportEvidence.created_at, ReportEvidence.id)
            )
        )

    async def get_report_evidence(self, evidence_id: UUID) -> ReportEvidence | None:
        return cast(ReportEvidence | None, await self.session.get(ReportEvidence, evidence_id))

    async def suspend_user(self, user_id: UUID, report_id: UUID) -> None:
        user = await self.session.get(User, user_id, with_for_update=True)
        if user is not None and user.status == UserStatus.ACTIVE:
            user.status = UserStatus.SUSPENDED
            user.suspension_source_report_id = report_id

    async def activate_user(self, user_id: UUID, report_id: UUID) -> None:
        user = await self.session.get(User, user_id, with_for_update=True)
        if (
            user is not None
            and user.status == UserStatus.SUSPENDED
            and user.suspension_source_report_id == report_id
        ):
            user.status = UserStatus.ACTIVE
            user.suspension_source_report_id = None

    async def set_user_suspension_source(
        self, user_id: UUID, from_report_id: UUID, report_id: UUID
    ) -> None:
        user = await self.session.get(User, user_id, with_for_update=True)
        if (
            user is not None
            and user.status == UserStatus.SUSPENDED
            and user.suspension_source_report_id == from_report_id
        ):
            user.suspension_source_report_id = report_id

    async def hide_report_product(self, report: Report) -> None:
        if report.target_type != ModerationTargetType.PRODUCT:
            return
        product = await self.get_product(report.target_id, lock=True)
        if product is None:
            return
        if product.status == ProductStatus.HIDDEN or product.status != ProductStatus.ON_SALE:
            return
        product.hidden_from_status = product.status.value
        product.status = ProductStatus.HIDDEN
        product.moderation_reason_code = "report_violation"
        product.moderation_public_note = report.public_result
        product.moderation_source_report_id = report.id

    async def restore_report_product(self, report: Report) -> None:
        if report.target_type != ModerationTargetType.PRODUCT:
            return
        product = await self.get_product(report.target_id, lock=True)
        if (
            product is None
            or product.status != ProductStatus.HIDDEN
            or product.moderation_source_report_id != report.id
        ):
            return
        try:
            restored = ProductStatus(product.hidden_from_status or "")
        except ValueError:
            restored = ProductStatus.PENDING_REVIEW
        if restored != ProductStatus.ON_SALE:
            restored = ProductStatus.PENDING_REVIEW
        product.status = restored
        product.hidden_from_status = None
        product.moderation_source_report_id = None
        product.moderation_reason_code = "penalty_reversed"
        product.moderation_public_note = report.public_result

    async def set_product_moderation_source(self, report: Report, report_id: UUID) -> None:
        if report.target_type != ModerationTargetType.PRODUCT:
            return
        product = await self.get_product(report.target_id, lock=True)
        if (
            product is not None
            and product.status == ProductStatus.HIDDEN
            and product.moderation_source_report_id == report.id
        ):
            product.moderation_source_report_id = report_id

    async def blocking_penalty_report_id(
        self, report: Report, action: ModerationAction
    ) -> UUID | None:
        target_filter = (
            Report.subject_user_id == report.subject_user_id
            if action == ModerationAction.SUSPEND
            else (ModerationRecord.target_type == report.target_type)
            & (ModerationRecord.target_id == report.target_id)
        )
        return cast(
            UUID | None,
            await self.session.scalar(
                select(ModerationRecord.report_id)
                .join(Report, Report.id == ModerationRecord.report_id)
                .where(
                    ModerationRecord.report_id.is_not(None),
                    ModerationRecord.report_id != report.id,
                    target_filter,
                    ModerationRecord.action == action,
                    Report.status.in_((ReportStatus.RESOLVED, ReportStatus.APPEALED)),
                )
                .order_by(ModerationRecord.created_at.desc(), ModerationRecord.id.desc())
                .limit(1)
            ),
        )

    def record_report_decision(
        self,
        *,
        report: Report,
        moderator_id: UUID,
        action: ModerationAction,
        internal_reason: str,
        request_id: str,
        evidence_ids: list[UUID],
        before_status: ReportStatus,
    ) -> None:
        self.session.add(
            ModerationRecord(
                id=uuid4(),
                report_id=report.id,
                moderator_id=moderator_id,
                target_type=report.target_type,
                target_id=report.target_id,
                action=action,
                reason=internal_reason,
                action_data={
                    "before_status": before_status.value,
                    "after_status": report.status.value,
                    "evidence_ids": [str(item) for item in evidence_ids],
                },
            )
        )
        self.session.add(
            AuditLog(
                id=uuid4(),
                actor_id=moderator_id,
                request_id=request_id,
                action=f"report.moderation.{action.value}",
                target_type="report",
                target_id=report.id,
                audit_data={
                    "internal_reason": internal_reason,
                    "evidence_ids": [str(item) for item in evidence_ids],
                    "before_status": before_status.value,
                    "after_status": report.status.value,
                },
            )
        )

    async def create_appeal(
        self, *, report: Report, appellant_id: UUID, details: str
    ) -> tuple[ReportAppeal, bool]:
        appeal_id = uuid4()
        inserted = await self.session.scalar(
            insert(ReportAppeal)
            .values(
                id=appeal_id,
                report_id=report.id,
                appellant_id=appellant_id,
                original_moderator_id=report.decision_moderator_id,
                details=details,
                status="pending",
                version=1,
            )
            .on_conflict_do_nothing(constraint="uq_report_appeals_report_id")
            .returning(ReportAppeal.id)
        )
        appeal = await self.session.scalar(
            select(ReportAppeal).where(ReportAppeal.report_id == report.id)
        )
        assert appeal is not None
        return appeal, inserted is not None

    async def get_appeal(self, appeal_id: UUID, *, lock: bool = False) -> ReportAppeal | None:
        query = select(ReportAppeal).where(ReportAppeal.id == appeal_id)
        if lock:
            query = query.with_for_update()
        return cast(ReportAppeal | None, await self.session.scalar(query))

    async def get_report_appeal(self, report_id: UUID) -> ReportAppeal | None:
        return cast(
            ReportAppeal | None,
            await self.session.scalar(
                select(ReportAppeal).where(ReportAppeal.report_id == report_id)
            ),
        )

    async def add_appeal_evidence(
        self,
        *,
        appeal_id: UUID,
        uploader_id: UUID,
        object_key: str,
        original_filename: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
    ) -> tuple[ReportAppealEvidence, bool]:
        evidence_id = uuid4()
        inserted = await self.session.scalar(
            insert(ReportAppealEvidence)
            .values(
                id=evidence_id,
                appeal_id=appeal_id,
                uploader_id=uploader_id,
                object_key=object_key,
                original_filename=original_filename,
                media_type=media_type,
                size_bytes=size_bytes,
                sha256=sha256,
            )
            .on_conflict_do_nothing(constraint="uq_appeal_evidence_content")
            .returning(ReportAppealEvidence.id)
        )
        evidence = await self.session.scalar(
            select(ReportAppealEvidence).where(
                ReportAppealEvidence.appeal_id == appeal_id,
                ReportAppealEvidence.sha256 == sha256,
            )
        )
        assert evidence is not None
        return evidence, inserted is not None

    async def appeal_evidence_ids(self, appeal_id: UUID) -> list[UUID]:
        return list(
            await self.session.scalars(
                select(ReportAppealEvidence.id)
                .where(ReportAppealEvidence.appeal_id == appeal_id)
                .order_by(ReportAppealEvidence.created_at, ReportAppealEvidence.id)
            )
        )

    async def get_appeal_evidence(self, evidence_id: UUID) -> ReportAppealEvidence | None:
        return cast(
            ReportAppealEvidence | None,
            await self.session.get(ReportAppealEvidence, evidence_id),
        )

    async def list_appeals(
        self, status: str = "pending", *, page: int, page_size: int
    ) -> tuple[Sequence[ReportAppeal], int]:
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(ReportAppeal).where(ReportAppeal.status == status)
            )
            or 0
        )
        items = list(
            await self.session.scalars(
                select(ReportAppeal)
                .where(ReportAppeal.status == status)
                .order_by(ReportAppeal.created_at.desc(), ReportAppeal.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    async def notify_report_user(
        self,
        *,
        user_id: UUID,
        report_id: UUID,
        event_key: str,
        title: str,
        summary: str,
        target_type: str = "report",
    ) -> None:
        enabled = await self.session.scalar(
            select(NotificationPreference.enabled).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.category == "report",
            )
        )
        if enabled is False:
            return
        notification_id = uuid4()
        inserted = await self.session.scalar(
            insert(Notification)
            .values(
                id=notification_id,
                user_id=user_id,
                event_key=event_key,
                category="report",
                title=title,
                summary=summary,
                target_type=target_type,
                target_id=report_id,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_event_key")
            .returning(Notification.id)
        )
        if inserted is not None:
            self.session.add(
                NotificationDeliveryAttempt(
                    id=uuid4(),
                    notification_id=notification_id,
                    attempt_no=1,
                    status="pending",
                    next_retry_at=datetime.now(UTC),
                )
            )
