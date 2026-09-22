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

    async def list_products(self, status: ProductStatus) -> Sequence[tuple[Product, str]]:
        rows = await self.session.execute(
            select(Product, User.display_name)
            .join(User, User.id == Product.seller_id)
            .where(Product.status == status, Product.deleted_at.is_(None))
            .options(selectinload(Product.images))
            .order_by(Product.updated_at, Product.id)
        )
        return [(row[0], row[1]) for row in rows]

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

    async def list_reports(self, status: ReportStatus | None) -> Sequence[Report]:
        query = select(Report)
        if status is not None:
            query = query.where(Report.status == status)
        return list(await self.session.scalars(query.order_by(Report.created_at, Report.id)))

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

    async def suspend_user(self, user_id: UUID) -> None:
        user = await self.session.get(User, user_id, with_for_update=True)
        if user is not None:
            user.status = UserStatus.SUSPENDED

    async def activate_user(self, user_id: UUID) -> None:
        user = await self.session.get(User, user_id, with_for_update=True)
        if user is not None and user.status == UserStatus.SUSPENDED:
            user.status = UserStatus.ACTIVE

    async def hide_report_product(self, report: Report) -> None:
        if report.target_type != ModerationTargetType.PRODUCT:
            return
        product = await self.get_product(report.target_id, lock=True)
        if product is None or product.status == ProductStatus.HIDDEN:
            return
        product.hidden_from_status = product.status.value
        product.status = ProductStatus.HIDDEN
        product.moderation_reason_code = "report_violation"
        product.moderation_public_note = report.public_result

    async def restore_report_product(self, report: Report) -> None:
        if report.target_type != ModerationTargetType.PRODUCT:
            return
        product = await self.get_product(report.target_id, lock=True)
        if product is None or product.status != ProductStatus.HIDDEN:
            return
        try:
            restored = ProductStatus(product.hidden_from_status or "")
        except ValueError:
            restored = ProductStatus.PENDING_REVIEW
        if restored not in {ProductStatus.ON_SALE, ProductStatus.RESERVED, ProductStatus.SOLD}:
            restored = ProductStatus.PENDING_REVIEW
        product.status = restored
        product.hidden_from_status = None
        product.moderation_reason_code = "penalty_reversed"
        product.moderation_public_note = report.public_result

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

    async def list_appeals(self, status: str = "pending") -> Sequence[ReportAppeal]:
        return list(
            await self.session.scalars(
                select(ReportAppeal)
                .where(ReportAppeal.status == status)
                .order_by(ReportAppeal.created_at, ReportAppeal.id)
            )
        )

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
