from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.catalog import Category, Product, ProductStatus
from app.models.identity import Campus, School, User, UserStatus
from app.models.messaging import (
    Conversation,
    ConversationReadState,
    Message,
    MessageRiskSignal,
    UserBlock,
)
from app.models.moderation import AuditLog, ModerationTargetType, Report
from app.models.notification import (
    Notification,
    NotificationDeliveryAttempt,
    NotificationPreference,
)


@dataclass(frozen=True)
class ConversationRecord:
    id: UUID
    product_id: UUID
    product_title: str
    product_price: Decimal
    product_status: str
    other_user_id: UUID
    other_display_name: str
    last_message_at: datetime | None
    last_message_preview: str | None
    unread_count: int


@dataclass(frozen=True)
class MessageWriteResult:
    message: Message
    created: bool


class ChatRepository(Protocol):
    async def visible_product_for_chat(self, product_id: UUID) -> Product | None: ...

    async def create_or_get_conversation(
        self, *, product: Product, buyer_id: UUID
    ) -> Conversation: ...

    async def list_conversations(
        self, user_id: UUID, limit: int, *, conversation_id: UUID | None = None
    ) -> Sequence[ConversationRecord]: ...

    async def get_member_conversation(
        self, user_id: UUID, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation | None: ...

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[Message]: ...

    async def get_message(self, conversation_id: UUID, message_id: UUID) -> Message | None: ...

    async def get_message_by_client_key(
        self, sender_id: UUID, client_message_id: str
    ) -> Message | None: ...

    async def create_message(
        self,
        *,
        conversation_id: UUID,
        sender_id: UUID,
        client_message_id: str,
        body: str,
    ) -> MessageWriteResult: ...

    def after_commit(self, callback: Callable[[], Awaitable[Any] | None]) -> None: ...

    async def mark_read(
        self, *, conversation_id: UUID, user_id: UUID, message: Message
    ) -> ConversationReadState: ...

    async def lock_users(self, first_id: UUID, second_id: UUID) -> bool: ...

    async def blocked_between(self, first_id: UUID, second_id: UUID) -> bool: ...

    async def block_user(self, blocker_id: UUID, blocked_id: UUID) -> None: ...

    async def unblock_user(self, blocker_id: UUID, blocked_id: UUID) -> None: ...

    async def list_blocked_user_ids(self, blocker_id: UUID) -> Sequence[UUID]: ...

    async def record_risk_flags(self, message_id: UUID, flags: list[str]) -> None: ...

    async def create_chat_notification(
        self, *, recipient_id: UUID, message: Message
    ) -> Notification | None: ...

    async def create_notification_event(
        self,
        *,
        recipient_id: UUID,
        event_key: str,
        category: str,
        title: str,
        summary: str,
        target_type: str,
        target_id: UUID | None,
    ) -> Notification | None: ...

    async def report_message(
        self, *, reporter_id: UUID, message_id: UUID, reason_code: str, details: str | None
    ) -> Report: ...

    async def list_notifications(self, user_id: UUID, limit: int) -> Sequence[Notification]: ...

    async def unread_notification_count(self, user_id: UUID) -> int: ...

    async def mark_notification_read(
        self, user_id: UUID, notification_id: UUID
    ) -> Notification | None: ...

    async def mark_all_notifications_read(self, user_id: UUID) -> int: ...

    async def notification_preferences(self, user_id: UUID) -> dict[str, bool]: ...

    async def set_notification_preference(
        self, user_id: UUID, category: str, enabled: bool
    ) -> None: ...


class SqlAlchemyChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def visible_product_for_chat(self, product_id: UUID) -> Product | None:
        return cast(
            Product | None,
            await self.session.scalar(
                select(Product)
                .join(Campus, Campus.id == Product.campus_id)
                .join(School, School.id == Campus.school_id)
                .join(Category, Category.id == Product.category_id)
                .join(User, User.id == Product.seller_id)
                .where(
                    Product.id == product_id,
                    Product.deleted_at.is_(None),
                    Product.status.in_((ProductStatus.ON_SALE, ProductStatus.RESERVED)),
                    Campus.deleted_at.is_(None),
                    Campus.is_active.is_(True),
                    School.deleted_at.is_(None),
                    School.is_active.is_(True),
                    Category.deleted_at.is_(None),
                    Category.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.status == UserStatus.ACTIVE,
                )
            ),
        )

    async def create_or_get_conversation(self, *, product: Product, buyer_id: UUID) -> Conversation:
        conversation_id = uuid4()
        await self.session.execute(
            insert(Conversation)
            .values(
                id=conversation_id,
                product_id=product.id,
                buyer_id=buyer_id,
                seller_id=product.seller_id,
                product_title_snapshot=product.title,
                product_price_snapshot=product.price,
            )
            .on_conflict_do_nothing(constraint="uq_conversations_product_parties")
        )
        conversation = await self.session.scalar(
            select(Conversation).where(
                Conversation.product_id == product.id,
                Conversation.buyer_id == buyer_id,
                Conversation.seller_id == product.seller_id,
            )
        )
        assert conversation is not None
        return conversation

    async def list_conversations(
        self, user_id: UUID, limit: int, *, conversation_id: UUID | None = None
    ) -> Sequence[ConversationRecord]:
        other_user = aliased(User)
        read_at = (
            select(ConversationReadState.last_read_at)
            .where(
                ConversationReadState.conversation_id == Conversation.id,
                ConversationReadState.user_id == user_id,
            )
            .correlate(Conversation)
            .scalar_subquery()
        )
        read_id = (
            select(ConversationReadState.last_read_message_id)
            .where(
                ConversationReadState.conversation_id == Conversation.id,
                ConversationReadState.user_id == user_id,
            )
            .correlate(Conversation)
            .scalar_subquery()
        )
        unread_count = (
            select(func.count(Message.id))
            .where(
                Message.conversation_id == Conversation.id,
                Message.deleted_at.is_(None),
                Message.sender_id != user_id,
                or_(
                    read_at.is_(None),
                    Message.created_at > read_at,
                    (Message.created_at == read_at) & (Message.id > read_id),
                ),
            )
            .correlate(Conversation)
            .scalar_subquery()
        )
        last_preview = (
            select(Message.body)
            .where(
                Message.conversation_id == Conversation.id,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        other_id = case(
            (Conversation.buyer_id == user_id, Conversation.seller_id),
            else_=Conversation.buyer_id,
        )
        query = (
            select(
                Conversation.id,
                Conversation.product_id,
                Conversation.product_title_snapshot.label("product_title"),
                Conversation.product_price_snapshot.label("product_price"),
                Product.status.label("product_status"),
                other_user.id.label("other_user_id"),
                other_user.display_name.label("other_display_name"),
                Conversation.last_message_at,
                last_preview.label("last_message_preview"),
                unread_count.label("unread_count"),
            )
            .join(Product, Product.id == Conversation.product_id)
            .join(other_user, other_user.id == other_id)
            .where(
                Conversation.deleted_at.is_(None),
                or_(Conversation.buyer_id == user_id, Conversation.seller_id == user_id),
            )
        )
        if conversation_id is not None:
            query = query.where(Conversation.id == conversation_id)
        result = await self.session.execute(
            query.order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.updated_at.desc(),
                Conversation.id,
            ).limit(limit)
        )
        return [ConversationRecord(**dict(row._mapping)) for row in result]

    async def get_member_conversation(
        self, user_id: UUID, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation | None:
        query = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.deleted_at.is_(None),
            or_(Conversation.buyer_id == user_id, Conversation.seller_id == user_id),
        )
        if for_update:
            query = query.with_for_update()
        return cast(Conversation | None, await self.session.scalar(query))

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[Message]:
        query = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
        )
        if before_created_at is not None and before_id is not None:
            query = query.where(
                or_(
                    Message.created_at < before_created_at,
                    (Message.created_at == before_created_at) & (Message.id < before_id),
                )
            )
        result = await self.session.scalars(
            query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
        )
        return list(reversed(result.all()))

    async def get_message(self, conversation_id: UUID, message_id: UUID) -> Message | None:
        return cast(
            Message | None,
            await self.session.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.conversation_id == conversation_id,
                    Message.deleted_at.is_(None),
                )
            ),
        )

    async def get_message_by_client_key(
        self, sender_id: UUID, client_message_id: str
    ) -> Message | None:
        return cast(
            Message | None,
            await self.session.scalar(
                select(Message).where(
                    Message.sender_id == sender_id,
                    Message.client_message_id == client_message_id,
                )
            ),
        )

    async def create_message(
        self,
        *,
        conversation_id: UUID,
        sender_id: UUID,
        client_message_id: str,
        body: str,
    ) -> MessageWriteResult:
        message_id = uuid4()
        inserted_id = await self.session.scalar(
            insert(Message)
            .values(
                id=message_id,
                conversation_id=conversation_id,
                sender_id=sender_id,
                client_message_id=client_message_id,
                body=body,
            )
            .on_conflict_do_nothing(constraint="uq_messages_sender_client_message")
            .returning(Message.id)
        )
        message = await self.get_message_by_client_key(sender_id, client_message_id)
        assert message is not None
        if inserted_id is not None:
            conversation = await self.session.get(Conversation, conversation_id)
            assert conversation is not None
            conversation.last_message_at = message.created_at
            await self.session.flush()
        return MessageWriteResult(message=message, created=inserted_id is not None)

    def after_commit(self, callback: Callable[[], Awaitable[Any] | None]) -> None:
        callbacks = cast(
            list[Callable[[], Awaitable[None] | None]],
            self.session.info.setdefault("after_commit_callbacks", []),
        )
        callbacks.append(callback)

    async def mark_read(
        self, *, conversation_id: UUID, user_id: UUID, message: Message
    ) -> ConversationReadState:
        await self.session.execute(
            insert(ConversationReadState)
            .values(
                id=uuid4(),
                conversation_id=conversation_id,
                user_id=user_id,
                last_read_message_id=message.id,
                last_read_at=message.created_at,
            )
            .on_conflict_do_update(
                constraint="uq_conversation_read_states_member",
                set_={
                    "last_read_message_id": message.id,
                    "last_read_at": message.created_at,
                    "updated_at": datetime.now(UTC),
                },
                where=or_(
                    ConversationReadState.last_read_at.is_(None),
                    ConversationReadState.last_read_at < message.created_at,
                    (ConversationReadState.last_read_at == message.created_at)
                    & (ConversationReadState.last_read_message_id < message.id),
                ),
            )
        )
        state = await self.session.scalar(
            select(ConversationReadState).where(
                ConversationReadState.conversation_id == conversation_id,
                ConversationReadState.user_id == user_id,
            )
        )
        assert state is not None
        return state

    async def lock_users(self, first_id: UUID, second_id: UUID) -> bool:
        users = list(
            await self.session.scalars(
                select(User.id)
                .where(User.id.in_((first_id, second_id)))
                .order_by(User.id)
                .with_for_update()
            )
        )
        return len(users) == len({first_id, second_id})

    async def blocked_between(self, first_id: UUID, second_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.count(UserBlock.id)).where(
                    or_(
                        (UserBlock.blocker_id == first_id) & (UserBlock.blocked_id == second_id),
                        (UserBlock.blocker_id == second_id) & (UserBlock.blocked_id == first_id),
                    )
                )
            )
        )

    async def block_user(self, blocker_id: UUID, blocked_id: UUID) -> None:
        await self.session.execute(
            insert(UserBlock)
            .values(id=uuid4(), blocker_id=blocker_id, blocked_id=blocked_id)
            .on_conflict_do_nothing(constraint="uq_user_blocks_pair")
        )

    async def unblock_user(self, blocker_id: UUID, blocked_id: UUID) -> None:
        await self.session.execute(
            delete(UserBlock).where(
                UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id
            )
        )

    async def list_blocked_user_ids(self, blocker_id: UUID) -> Sequence[UUID]:
        return list(
            await self.session.scalars(
                select(UserBlock.blocked_id)
                .where(UserBlock.blocker_id == blocker_id)
                .order_by(UserBlock.created_at.desc())
            )
        )

    async def record_risk_flags(self, message_id: UUID, flags: list[str]) -> None:
        if not flags:
            return
        await self.session.execute(
            insert(MessageRiskSignal)
            .values(id=uuid4(), message_id=message_id, flags=flags)
            .on_conflict_do_nothing(constraint="uq_message_risk_signals_message")
        )

    async def create_chat_notification(
        self, *, recipient_id: UUID, message: Message
    ) -> Notification | None:
        return await self.create_notification_event(
            recipient_id=recipient_id,
            event_key=f"chat.message:{message.id}:{recipient_id}",
            category="chat",
            title="收到一条新消息",
            summary="你有一条新的校内私信，打开会话查看详情。",
            target_type="conversation",
            target_id=message.conversation_id,
        )

    async def create_notification_event(
        self,
        *,
        recipient_id: UUID,
        event_key: str,
        category: str,
        title: str,
        summary: str,
        target_type: str,
        target_id: UUID | None,
    ) -> Notification | None:
        enabled = await self.session.scalar(
            select(NotificationPreference.enabled).where(
                NotificationPreference.user_id == recipient_id,
                NotificationPreference.category == category,
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
                category=category,
                title=title,
                summary=summary,
                target_type=target_type,
                target_id=target_id,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_event_key")
            .returning(Notification.id)
        )
        notification = await self.session.scalar(
            select(Notification).where(
                Notification.user_id == recipient_id, Notification.event_key == event_key
            )
        )
        assert notification is not None
        if inserted_id is not None:
            await self.session.execute(
                insert(NotificationDeliveryAttempt).values(
                    id=uuid4(),
                    notification_id=notification.id,
                    attempt_no=1,
                    status="pending",
                )
            )
        return notification

    async def report_message(
        self, *, reporter_id: UUID, message_id: UUID, reason_code: str, details: str | None
    ) -> Report:
        report_id = uuid4()
        inserted_id = await self.session.scalar(
            insert(Report)
            .values(
                id=report_id,
                reporter_id=reporter_id,
                target_type=ModerationTargetType.MESSAGE,
                target_id=message_id,
                reason_code=reason_code,
                details=details,
            )
            .on_conflict_do_nothing(constraint="uq_reports_key")
            .returning(Report.id)
        )
        report = await self.session.scalar(
            select(Report).where(
                Report.reporter_id == reporter_id,
                Report.target_type == ModerationTargetType.MESSAGE,
                Report.target_id == message_id,
                Report.reason_code == reason_code,
            )
        )
        assert report is not None
        if inserted_id is not None:
            self.session.add(
                AuditLog(
                    id=uuid4(),
                    actor_id=reporter_id,
                    request_id=f"chat-report:{report.id}",
                    action="chat.report.created",
                    target_type="message",
                    target_id=message_id,
                    audit_data={"reason_code": reason_code},
                )
            )
        return report

    async def list_notifications(self, user_id: UUID, limit: int) -> Sequence[Notification]:
        return list(
            await self.session.scalars(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(limit)
            )
        )

    async def unread_notification_count(self, user_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id, Notification.read_at.is_(None)
                )
            )
            or 0
        )

    async def mark_notification_read(
        self, user_id: UUID, notification_id: UUID
    ) -> Notification | None:
        notification = await self.session.scalar(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        if notification is not None and notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            await self.session.flush()
        return notification

    async def mark_all_notifications_read(self, user_id: UUID) -> int:
        result = await self.session.scalars(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=datetime.now(UTC))
            .returning(Notification.id)
        )
        return len(result.all())

    async def notification_preferences(self, user_id: UUID) -> dict[str, bool]:
        result = await self.session.execute(
            select(NotificationPreference.category, NotificationPreference.enabled).where(
                NotificationPreference.user_id == user_id
            )
        )
        return {category: enabled for category, enabled in result}

    async def set_notification_preference(
        self, user_id: UUID, category: str, enabled: bool
    ) -> None:
        await self.session.execute(
            insert(NotificationPreference)
            .values(id=uuid4(), user_id=user_id, category=category, enabled=enabled)
            .on_conflict_do_update(
                constraint="uq_notification_preferences_user_category",
                set_={"enabled": enabled, "updated_at": datetime.now(UTC)},
            )
        )
