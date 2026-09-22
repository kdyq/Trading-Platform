from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product, ProductImage
from app.models.identity import (
    Campus,
    CampusVerification,
    CampusVerificationStatus,
    User,
)
from app.models.messaging import Conversation
from app.models.moderation import Report
from app.models.notification import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationPreference,
)
from app.models.trade import (
    MeetingProposalStatus,
    Order,
    OrderCommand,
    OrderEvent,
    OrderMeetingProposal,
    OrderStatus,
    Review,
)


class OrderRepository(Protocol):
    async def verified_campus_id(self, user_id: UUID) -> UUID | None: ...

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def lock_product(self, product_id: UUID) -> Product | None: ...

    async def campus_name(self, campus_id: UUID) -> str | None: ...

    async def member_conversation(
        self, conversation_id: UUID, user_id: UUID, product_id: UUID
    ) -> Conversation | None: ...

    async def create_order(self, order: Order) -> tuple[Order, bool]: ...

    async def find_order_by_idempotency(
        self, buyer_id: UUID, idempotency_key: str
    ) -> Order | None: ...

    async def get_order(self, order_id: UUID, *, for_update: bool = False) -> Order | None: ...

    async def refresh_order(self, order: Order) -> None: ...

    def add_meeting_proposal(self, proposal: OrderMeetingProposal) -> None: ...

    async def get_meeting_proposal(
        self, proposal_id: UUID, *, for_update: bool = False
    ) -> OrderMeetingProposal | None: ...

    async def refresh_meeting_proposal(self, proposal: OrderMeetingProposal) -> None: ...

    async def supersede_other_proposals(self, order_id: UUID, proposal_id: UUID) -> None: ...

    async def withdraw_pending_proposals(self, order_id: UUID) -> None: ...

    async def claim_expired_pending(self, limit: int) -> Sequence[Order]: ...

    def add_dispute_report(self, report: Report) -> None: ...

    async def list_orders(
        self,
        *,
        user_id: UUID,
        role: str,
        status: OrderStatus | None,
        before_updated_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[tuple[Order, UUID | None]]: ...

    async def list_order_events(self, order_id: UUID) -> Sequence[OrderEvent]: ...

    async def list_meeting_proposals(self, order_id: UUID) -> Sequence[OrderMeetingProposal]: ...

    async def list_reviews(self, order_id: UUID) -> Sequence[Review]: ...

    async def get_review(self, order_id: UUID, reviewer_id: UUID) -> Review | None: ...

    def add_review(self, review: Review) -> None: ...

    async def refresh_review(self, review: Review) -> None: ...

    async def find_command(self, actor_id: UUID, client_action_id: str) -> OrderCommand | None: ...

    async def lock_command_key(self, actor_id: UUID, client_action_id: str) -> None: ...

    def add_event(
        self,
        *,
        order: Order,
        actor_id: UUID | None,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        note: str | None,
        event_data: dict[str, object] | None = None,
    ) -> OrderEvent: ...

    def add_command(
        self,
        *,
        order_id: UUID,
        actor_id: UUID,
        client_action_id: str,
        command: str,
        payload_hash: str,
        event: OrderEvent | None,
        result_id: UUID | None = None,
    ) -> None: ...

    async def cancel_other_pending(
        self, *, product_id: UUID, accepted_order_id: UUID, actor_id: UUID
    ) -> Sequence[tuple[UUID, UUID]]: ...

    async def create_notification(
        self,
        *,
        recipient_id: UUID,
        event_key: str,
        title: str,
        summary: str,
        order_id: UUID,
    ) -> Notification | None: ...


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def verified_campus_id(self, user_id: UUID) -> UUID | None:
        now = datetime.now(UTC)
        return cast(
            UUID | None,
            await self.session.scalar(
                select(CampusVerification.campus_id)
                .where(
                    CampusVerification.user_id == user_id,
                    CampusVerification.status == CampusVerificationStatus.VERIFIED,
                    CampusVerification.deleted_at.is_(None),
                    or_(
                        CampusVerification.expires_at.is_(None),
                        CampusVerification.expires_at > now,
                    ),
                )
                .order_by(CampusVerification.verified_at.desc())
                .limit(1)
            ),
        )

    async def get_user(self, user_id: UUID) -> User | None:
        return cast(User | None, await self.session.get(User, user_id))

    async def lock_product(self, product_id: UUID) -> Product | None:
        return cast(
            Product | None,
            await self.session.scalar(
                select(Product)
                .where(Product.id == product_id, Product.deleted_at.is_(None))
                .with_for_update()
            ),
        )

    async def campus_name(self, campus_id: UUID) -> str | None:
        return cast(
            str | None, await self.session.scalar(select(Campus.name).where(Campus.id == campus_id))
        )

    async def member_conversation(
        self, conversation_id: UUID, user_id: UUID, product_id: UUID
    ) -> Conversation | None:
        return cast(
            Conversation | None,
            await self.session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.product_id == product_id,
                    Conversation.deleted_at.is_(None),
                    or_(Conversation.buyer_id == user_id, Conversation.seller_id == user_id),
                )
            ),
        )

    async def create_order(self, order: Order) -> tuple[Order, bool]:
        inserted_id = await self.session.scalar(
            insert(Order)
            .values(
                id=order.id,
                product_id=order.product_id,
                conversation_id=order.conversation_id,
                buyer_id=order.buyer_id,
                seller_id=order.seller_id,
                idempotency_key=order.idempotency_key,
                amount=order.amount,
                product_title_snapshot=order.product_title_snapshot,
                campus_name_snapshot=order.campus_name_snapshot,
                buyer_display_name_snapshot=order.buyer_display_name_snapshot,
                seller_display_name_snapshot=order.seller_display_name_snapshot,
                payment_mode=order.payment_mode,
                status=order.status,
                expires_at=order.expires_at,
            )
            .on_conflict_do_nothing()
            .returning(Order.id)
        )
        stored = await self.find_order_by_idempotency(order.buyer_id, order.idempotency_key)
        if stored is None:
            stored = await self.session.scalar(
                select(Order).where(
                    Order.buyer_id == order.buyer_id,
                    Order.product_id == order.product_id,
                    Order.status.in_(
                        (
                            OrderStatus.PENDING_SELLER_CONFIRMATION,
                            OrderStatus.ACCEPTED,
                            OrderStatus.SCHEDULED,
                            OrderStatus.SELLER_DELIVERED,
                            OrderStatus.DISPUTED,
                        )
                    ),
                )
            )
        assert stored is not None
        return stored, inserted_id is not None

    async def find_order_by_idempotency(self, buyer_id: UUID, idempotency_key: str) -> Order | None:
        return cast(
            Order | None,
            await self.session.scalar(
                select(Order).where(
                    Order.buyer_id == buyer_id,
                    Order.idempotency_key == idempotency_key,
                )
            ),
        )

    async def get_order(self, order_id: UUID, *, for_update: bool = False) -> Order | None:
        query = select(Order).where(Order.id == order_id)
        if for_update:
            query = query.with_for_update()
        return cast(Order | None, await self.session.scalar(query))

    async def refresh_order(self, order: Order) -> None:
        await self.session.flush()
        await self.session.refresh(order)

    def add_meeting_proposal(self, proposal: OrderMeetingProposal) -> None:
        self.session.add(proposal)

    async def get_meeting_proposal(
        self, proposal_id: UUID, *, for_update: bool = False
    ) -> OrderMeetingProposal | None:
        query = select(OrderMeetingProposal).where(OrderMeetingProposal.id == proposal_id)
        if for_update:
            query = query.with_for_update()
        return cast(OrderMeetingProposal | None, await self.session.scalar(query))

    async def refresh_meeting_proposal(self, proposal: OrderMeetingProposal) -> None:
        await self.session.flush()
        await self.session.refresh(proposal)

    async def supersede_other_proposals(self, order_id: UUID, proposal_id: UUID) -> None:
        await self.session.execute(
            update(OrderMeetingProposal)
            .where(
                OrderMeetingProposal.order_id == order_id,
                OrderMeetingProposal.id != proposal_id,
                OrderMeetingProposal.status.in_(
                    (MeetingProposalStatus.PENDING, MeetingProposalStatus.ACCEPTED)
                ),
            )
            .values(status=MeetingProposalStatus.SUPERSEDED)
        )

    async def withdraw_pending_proposals(self, order_id: UUID) -> None:
        await self.session.execute(
            update(OrderMeetingProposal)
            .where(
                OrderMeetingProposal.order_id == order_id,
                OrderMeetingProposal.status == MeetingProposalStatus.PENDING,
            )
            .values(status=MeetingProposalStatus.WITHDRAWN)
        )

    async def claim_expired_pending(self, limit: int) -> Sequence[Order]:
        return list(
            await self.session.scalars(
                select(Order)
                .where(
                    Order.status == OrderStatus.PENDING_SELLER_CONFIRMATION,
                    Order.expires_at.is_not(None),
                    Order.expires_at <= datetime.now(UTC),
                )
                .order_by(Order.expires_at, Order.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    def add_dispute_report(self, report: Report) -> None:
        self.session.add(report)

    async def list_orders(
        self,
        *,
        user_id: UUID,
        role: str,
        status: OrderStatus | None,
        before_updated_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[tuple[Order, UUID | None]]:
        image_id = (
            select(ProductImage.id)
            .where(ProductImage.product_id == Order.product_id, ProductImage.deleted_at.is_(None))
            .order_by(ProductImage.display_order, ProductImage.created_at, ProductImage.id)
            .limit(1)
            .correlate(Order)
            .scalar_subquery()
        )
        query = select(Order, image_id.label("image_id")).where(
            Order.buyer_id == user_id if role == "buying" else Order.seller_id == user_id
        )
        if status is not None:
            query = query.where(Order.status == status)
        if before_updated_at is not None and before_id is not None:
            query = query.where(
                or_(
                    Order.updated_at < before_updated_at,
                    (Order.updated_at == before_updated_at) & (Order.id < before_id),
                )
            )
        rows = await self.session.execute(
            query.order_by(Order.updated_at.desc(), Order.id.desc()).limit(limit)
        )
        return [(row[0], row[1]) for row in rows]

    async def list_order_events(self, order_id: UUID) -> Sequence[OrderEvent]:
        return list(
            await self.session.scalars(
                select(OrderEvent)
                .where(OrderEvent.order_id == order_id)
                .order_by(OrderEvent.created_at, OrderEvent.id)
            )
        )

    async def list_meeting_proposals(self, order_id: UUID) -> Sequence[OrderMeetingProposal]:
        return list(
            await self.session.scalars(
                select(OrderMeetingProposal)
                .where(OrderMeetingProposal.order_id == order_id)
                .order_by(OrderMeetingProposal.created_at, OrderMeetingProposal.id)
            )
        )

    async def list_reviews(self, order_id: UUID) -> Sequence[Review]:
        return list(
            await self.session.scalars(
                select(Review)
                .where(Review.order_id == order_id, Review.is_visible.is_(True))
                .order_by(Review.created_at, Review.id)
            )
        )

    async def get_review(self, order_id: UUID, reviewer_id: UUID) -> Review | None:
        return cast(
            Review | None,
            await self.session.scalar(
                select(Review).where(
                    Review.order_id == order_id,
                    Review.reviewer_id == reviewer_id,
                )
            ),
        )

    def add_review(self, review: Review) -> None:
        self.session.add(review)

    async def refresh_review(self, review: Review) -> None:
        await self.session.flush()
        await self.session.refresh(review)

    async def find_command(self, actor_id: UUID, client_action_id: str) -> OrderCommand | None:
        return cast(
            OrderCommand | None,
            await self.session.scalar(
                select(OrderCommand).where(
                    OrderCommand.actor_id == actor_id,
                    OrderCommand.client_action_id == client_action_id,
                )
            ),
        )

    async def lock_command_key(self, actor_id: UUID, client_action_id: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:command_key, 0))"),
            {"command_key": f"{actor_id}:{client_action_id}"},
        )

    def add_event(
        self,
        *,
        order: Order,
        actor_id: UUID | None,
        from_status: OrderStatus | None,
        to_status: OrderStatus,
        note: str | None,
        event_data: dict[str, object] | None = None,
    ) -> OrderEvent:
        order.updated_at = datetime.now(UTC)
        event = OrderEvent(
            id=uuid4(),
            order_id=order.id,
            actor_id=actor_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            event_data=event_data or {},
        )
        self.session.add(event)
        return event

    def add_command(
        self,
        *,
        order_id: UUID,
        actor_id: UUID,
        client_action_id: str,
        command: str,
        payload_hash: str,
        event: OrderEvent | None,
        result_id: UUID | None = None,
    ) -> None:
        self.session.add(
            OrderCommand(
                id=uuid4(),
                order_id=order_id,
                actor_id=actor_id,
                client_action_id=client_action_id,
                command=command,
                payload_hash=payload_hash,
                event=event,
                result_id=result_id,
            )
        )

    async def cancel_other_pending(
        self, *, product_id: UUID, accepted_order_id: UUID, actor_id: UUID
    ) -> Sequence[tuple[UUID, UUID]]:
        now = datetime.now(UTC)
        cancelled = list(
            (
                await self.session.execute(
                    update(Order)
                    .where(
                        Order.product_id == product_id,
                        Order.id != accepted_order_id,
                        Order.status == OrderStatus.PENDING_SELLER_CONFIRMATION,
                    )
                    .values(
                        status=OrderStatus.CANCELLED,
                        cancelled_at=now,
                        cancellation_reason_code="product_reserved_elsewhere",
                        version=Order.version + 1,
                    )
                    .returning(Order.id, Order.buyer_id)
                )
            )
            .tuples()
            .all()
        )
        for order_id, _buyer_id in cancelled:
            self.session.add(
                OrderEvent(
                    id=uuid4(),
                    order_id=order_id,
                    actor_id=actor_id,
                    from_status=OrderStatus.PENDING_SELLER_CONFIRMATION,
                    to_status=OrderStatus.CANCELLED,
                    note="商品已由其他订单预留",
                    event_data={"reason_code": "product_reserved_elsewhere"},
                )
            )
        return cancelled

    async def create_notification(
        self,
        *,
        recipient_id: UUID,
        event_key: str,
        title: str,
        summary: str,
        order_id: UUID,
    ) -> Notification | None:
        enabled = await self.session.scalar(
            select(NotificationPreference.enabled).where(
                NotificationPreference.user_id == recipient_id,
                NotificationPreference.category == "order",
            )
        )
        if enabled is False:
            return None
        notification_id = uuid4()
        inserted_id = await self.session.scalar(
            insert(Notification)
            .values(
                id=notification_id,
                user_id=recipient_id,
                event_key=event_key,
                category="order",
                title=title,
                summary=summary,
                target_type="order",
                target_id=order_id,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_event_key")
            .returning(Notification.id)
        )
        notification = await self.session.scalar(
            select(Notification).where(
                Notification.user_id == recipient_id,
                Notification.event_key == event_key,
            )
        )
        if inserted_id is not None and notification is not None:
            self.session.add(
                NotificationDeliveryAttempt(
                    id=uuid4(),
                    notification_id=notification.id,
                    attempt_no=1,
                    status="pending",
                    next_retry_at=datetime.now(UTC),
                )
            )
        return notification
