from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AppError
from app.models.catalog import ProductStatus
from app.models.messaging import Message
from app.repositories.chat import ConversationRecord, MessageWriteResult
from app.services.chat import ChatService


class FakeChatRepository:
    def __init__(self) -> None:
        self.buyer_id = uuid4()
        self.seller_id = uuid4()
        self.outsider_id = uuid4()
        self.product_id = uuid4()
        self.conversation_id = uuid4()
        self.product = SimpleNamespace(
            id=self.product_id,
            seller_id=self.seller_id,
            title="高等数学教材",
            price=Decimal("18.50"),
        )
        self.conversation = SimpleNamespace(
            id=self.conversation_id,
            product_id=self.product_id,
            buyer_id=self.buyer_id,
            seller_id=self.seller_id,
        )
        self.messages: list[Message] = []
        self.read_states: dict[UUID, Any] = {}
        self.after_commit_callbacks: list[Any] = []
        self.blocked = False
        self.risk_flags: dict[UUID, list[str]] = {}

    async def visible_product_for_chat(self, product_id):  # type: ignore[no-untyped-def]
        return self.product if product_id == self.product_id else None

    async def create_or_get_conversation(self, *, product, buyer_id):  # type: ignore[no-untyped-def]
        assert product == self.product and buyer_id == self.buyer_id
        return self.conversation

    async def lock_users(self, first_id, second_id):  # type: ignore[no-untyped-def]
        return True

    async def blocked_between(self, first_id, second_id):  # type: ignore[no-untyped-def]
        return self.blocked

    async def block_user(self, blocker_id, blocked_id):  # type: ignore[no-untyped-def]
        self.blocked = True

    async def unblock_user(self, blocker_id, blocked_id):  # type: ignore[no-untyped-def]
        self.blocked = False

    async def list_blocked_user_ids(self, blocker_id):  # type: ignore[no-untyped-def]
        return [self.seller_id] if self.blocked else []

    async def list_conversations(  # type: ignore[no-untyped-def]
        self, user_id, limit, *, conversation_id=None
    ):
        if user_id not in {self.buyer_id, self.seller_id}:
            return []
        records = [
            ConversationRecord(
                id=self.conversation_id,
                product_id=self.product_id,
                product_title=self.product.title,
                product_price=self.product.price,
                product_status=ProductStatus.ON_SALE.value,
                other_user_id=self.seller_id if user_id == self.buyer_id else self.buyer_id,
                other_display_name="对方同学",
                last_message_at=self.messages[-1].created_at if self.messages else None,
                last_message_preview=self.messages[-1].body if self.messages else None,
                unread_count=0,
            )
        ]
        return [item for item in records if conversation_id in {None, item.id}]

    async def get_member_conversation(  # type: ignore[no-untyped-def]
        self, user_id, conversation_id, *, for_update=False
    ):
        if conversation_id == self.conversation_id and user_id in {
            self.buyer_id,
            self.seller_id,
        }:
            return self.conversation
        return None

    async def list_messages(  # type: ignore[no-untyped-def]
        self, conversation_id, *, before_created_at, before_id, limit
    ):
        records = self.messages
        if before_created_at is not None:
            records = [
                item
                for item in records
                if (item.created_at, item.id) < (before_created_at, before_id)
            ]
        return records[-limit:]

    async def get_message(self, conversation_id, message_id):  # type: ignore[no-untyped-def]
        return next(
            (
                item
                for item in self.messages
                if item.conversation_id == conversation_id and item.id == message_id
            ),
            None,
        )

    async def get_message_by_client_key(
        self, sender_id: UUID, client_message_id: str
    ) -> Message | None:
        return next(
            (
                item
                for item in self.messages
                if item.sender_id == sender_id and item.client_message_id == client_message_id
            ),
            None,
        )

    async def create_message(self, **values):  # type: ignore[no-untyped-def]
        existing = await self.get_message_by_client_key(
            values["sender_id"], values["client_message_id"]
        )
        if existing:
            return MessageWriteResult(message=existing, created=False)
        message = Message(id=uuid4(), **values)
        message.created_at = datetime.now(UTC) + timedelta(microseconds=len(self.messages))
        self.messages.append(message)
        return MessageWriteResult(message=message, created=True)

    def after_commit(self, callback):  # type: ignore[no-untyped-def]
        self.after_commit_callbacks.append(callback)

    async def record_risk_flags(self, message_id, flags):  # type: ignore[no-untyped-def]
        self.risk_flags[message_id] = flags

    async def create_chat_notification(self, **values):  # type: ignore[no-untyped-def]
        return None

    async def create_notification_event(self, **values):  # type: ignore[no-untyped-def]
        return None

    async def report_message(self, **values):  # type: ignore[no-untyped-def]
        return SimpleNamespace(id=uuid4(), status=SimpleNamespace(value="open"))

    async def list_notifications(self, user_id, limit):  # type: ignore[no-untyped-def]
        return []

    async def unread_notification_count(self, user_id):  # type: ignore[no-untyped-def]
        return 0

    async def mark_notification_read(self, user_id, notification_id):  # type: ignore[no-untyped-def]
        return None

    async def mark_all_notifications_read(self, user_id):  # type: ignore[no-untyped-def]
        return 0

    async def notification_preferences(self, user_id):  # type: ignore[no-untyped-def]
        return {}

    async def set_notification_preference(  # type: ignore[no-untyped-def]
        self, user_id, category, enabled
    ):
        return None

    async def mark_read(self, *, conversation_id, user_id, message):  # type: ignore[no-untyped-def]
        state = SimpleNamespace(
            conversation_id=conversation_id,
            user_id=user_id,
            last_read_message_id=message.id,
            last_read_at=message.created_at,
        )
        self.read_states[user_id] = state
        return state


@pytest.mark.anyio
async def test_verified_buyer_creates_unique_conversation_and_owner_is_rejected() -> None:
    repository = FakeChatRepository()
    service = ChatService(repository)

    conversation = await service.create_conversation(
        user_id=repository.buyer_id,
        campus_verified=True,
        product_id=repository.product_id,
    )
    assert conversation.id == repository.conversation_id
    assert conversation.other_user_id == repository.seller_id

    with pytest.raises(AppError) as own_product:
        await service.create_conversation(
            user_id=repository.seller_id,
            campus_verified=True,
            product_id=repository.product_id,
        )
    assert own_product.value.code == "cannot_message_own_product"

    with pytest.raises(AppError) as unverified:
        await service.create_conversation(
            user_id=repository.buyer_id,
            campus_verified=False,
            product_id=repository.product_id,
        )
    assert unverified.value.code == "campus_verification_required"


@pytest.mark.anyio
async def test_messages_are_idempotent_private_and_cursor_paginated() -> None:
    repository = FakeChatRepository()
    service = ChatService(repository)

    first = await service.send_message(
        user_id=repository.buyer_id,
        campus_verified=True,
        conversation_id=repository.conversation_id,
        client_message_id="message_001",
        body="你好，教材还在吗？",
    )
    duplicate = await service.send_message(
        user_id=repository.buyer_id,
        campus_verified=True,
        conversation_id=repository.conversation_id,
        client_message_id="message_001",
        body="你好，教材还在吗？",
    )
    assert duplicate.id == first.id and len(repository.messages) == 1

    with pytest.raises(AppError) as conflict:
        await service.send_message(
            user_id=repository.buyer_id,
            campus_verified=True,
            conversation_id=repository.conversation_id,
            client_message_id="message_001",
            body="不同内容",
        )
    assert conflict.value.code == "message_idempotency_conflict"

    for index in range(2, 5):
        await service.send_message(
            user_id=repository.seller_id,
            campus_verified=True,
            conversation_id=repository.conversation_id,
            client_message_id=f"message_{index:03d}",
            body=f"第 {index} 条消息",
        )
    latest = await service.list_messages(
        user_id=repository.buyer_id,
        conversation_id=repository.conversation_id,
        cursor=None,
        page_size=2,
    )
    assert [item.body for item in latest.items] == ["第 3 条消息", "第 4 条消息"]
    assert latest.next_cursor is not None
    older = await service.list_messages(
        user_id=repository.buyer_id,
        conversation_id=repository.conversation_id,
        cursor=latest.next_cursor,
        page_size=2,
    )
    assert [item.body for item in older.items] == ["你好，教材还在吗？", "第 2 条消息"]

    read = await service.mark_read(
        user_id=repository.buyer_id,
        conversation_id=repository.conversation_id,
        message_id=latest.items[-1].id,
    )
    assert read.last_read_message_id == latest.items[-1].id

    with pytest.raises(AppError) as hidden:
        await service.list_messages(
            user_id=repository.outsider_id,
            conversation_id=repository.conversation_id,
            cursor=None,
            page_size=20,
        )
    assert hidden.value.code == "conversation_not_found"


@pytest.mark.anyio
async def test_block_stops_new_messages_and_risk_hook_records_without_exposing_flags() -> None:
    repository = FakeChatRepository()
    service = ChatService(repository)

    flagged = await service.send_message(
        user_id=repository.buyer_id,
        campus_verified=True,
        conversation_id=repository.conversation_id,
        client_message_id="message_risk_001",
        body="不要发送验证码，也不要先付款",
    )
    assert repository.risk_flags[flagged.id] == ["verification_code", "off_platform_payment"]
    assert "risk" not in flagged.model_dump()

    await service.block_user(user_id=repository.buyer_id, blocked_id=repository.seller_id)
    with pytest.raises(AppError) as blocked:
        await service.send_message(
            user_id=repository.seller_id,
            campus_verified=True,
            conversation_id=repository.conversation_id,
            client_message_id="message_blocked_001",
            body="仍然发送",
        )
    assert blocked.value.code == "chat_blocked"


@pytest.mark.anyio
@pytest.mark.parametrize("control", ["\0", "\x7f", "\x85"])
async def test_message_rejects_database_unsafe_control_characters(control: str) -> None:
    repository = FakeChatRepository()
    service = ChatService(repository)

    with pytest.raises(AppError) as invalid:
        await service.send_message(
            user_id=repository.buyer_id,
            campus_verified=True,
            conversation_id=repository.conversation_id,
            client_message_id="message_control_001",
            body=f"包含控制字符{control}的消息",
        )
    assert invalid.value.status_code == 422
    assert invalid.value.code == "invalid_message_body"


@pytest.mark.anyio
async def test_message_rejects_more_than_five_links() -> None:
    repository = FakeChatRepository()
    service = ChatService(repository)

    with pytest.raises(AppError) as invalid:
        await service.send_message(
            user_id=repository.buyer_id,
            campus_verified=True,
            conversation_id=repository.conversation_id,
            client_message_id="message_links_001",
            body=" ".join(f"https://example.com/{index}" for index in range(6)),
        )
    assert invalid.value.status_code == 422
    assert invalid.value.code == "too_many_message_links"

    with pytest.raises(AppError) as punctuation_separated:
        await service.send_message(
            user_id=repository.buyer_id,
            campus_verified=True,
            conversation_id=repository.conversation_id,
            client_message_id="message_links_002",
            body=",".join(f"https://example.com/{index}" for index in range(6)),
        )
    assert punctuation_separated.value.code == "too_many_message_links"
