from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.catalog import Product, ProductStatus
from app.models.identity import Role, User, user_roles
from app.models.moderation import AuditLog, ModerationAction, ModerationRecord, ModerationTargetType
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
