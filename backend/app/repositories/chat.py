from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.catalog import Category, Product, ProductStatus
from app.models.identity import Campus, School, User, UserStatus
from app.models.messaging import Conversation, ConversationReadState, Message


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


class ChatRepository(Protocol):
    async def visible_product_for_chat(self, product_id: UUID) -> Product | None: ...

    async def create_or_get_conversation(
        self, *, product: Product, buyer_id: UUID
    ) -> Conversation: ...

    async def list_conversations(
        self, user_id: UUID, limit: int
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
    ) -> Message: ...

    async def mark_read(
        self, *, conversation_id: UUID, user_id: UUID, message: Message
    ) -> ConversationReadState: ...


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

    async def list_conversations(self, user_id: UUID, limit: int) -> Sequence[ConversationRecord]:
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
        result = await self.session.execute(
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
            .order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.updated_at.desc(),
                Conversation.id,
            )
            .limit(limit)
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
    ) -> Message:
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
        return message

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
