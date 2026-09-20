import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from app.core.exceptions import AppError
from app.models.messaging import Conversation, Message
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    ChatMessageResponse,
    ConversationListResponse,
    ConversationSummary,
    MessagePageResponse,
    ReadPositionResponse,
)


class ChatService:
    def __init__(self, repository: ChatRepository) -> None:
        self.repository = repository

    async def create_conversation(
        self, *, user_id: UUID, campus_verified: bool, product_id: UUID
    ) -> ConversationSummary:
        self._require_verified(campus_verified)
        product = await self.repository.visible_product_for_chat(product_id)
        if product is None:
            raise AppError(
                status_code=404, code="product_not_found", message="商品不存在或不可联系"
            )
        if product.seller_id == user_id:
            raise AppError(
                status_code=409,
                code="cannot_message_own_product",
                message="不能以买家身份联系自己的商品",
            )
        conversation = await self.repository.create_or_get_conversation(
            product=product, buyer_id=user_id
        )
        records = await self.repository.list_conversations(user_id, 50)
        record = next(item for item in records if item.id == conversation.id)
        return ConversationSummary.model_validate(record, from_attributes=True)

    async def list_conversations(self, user_id: UUID) -> ConversationListResponse:
        records = await self.repository.list_conversations(user_id, 50)
        return ConversationListResponse(
            items=[
                ConversationSummary.model_validate(item, from_attributes=True) for item in records
            ]
        )

    async def list_messages(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        cursor: str | None,
        page_size: int,
    ) -> MessagePageResponse:
        await self._member(user_id, conversation_id)
        created_at, message_id = self._decode_cursor(cursor) if cursor else (None, None)
        records = await self.repository.list_messages(
            conversation_id,
            before_created_at=created_at,
            before_id=message_id,
            limit=page_size + 1,
        )
        has_more = len(records) > page_size
        page_records = list(records[-page_size:])
        return MessagePageResponse(
            items=[self._message(item) for item in page_records],
            next_cursor=self._encode_cursor(page_records[0]) if has_more and page_records else None,
        )

    async def send_message(
        self,
        *,
        user_id: UUID,
        campus_verified: bool,
        conversation_id: UUID,
        client_message_id: str,
        body: str,
    ) -> ChatMessageResponse:
        self._require_verified(campus_verified)
        conversation = await self._member(user_id, conversation_id, for_update=True)
        cleaned = body.strip()
        if not cleaned:
            raise AppError(status_code=422, code="empty_message", message="消息内容不能为空")
        existing = await self.repository.get_message_by_client_key(user_id, client_message_id)
        if existing is not None:
            if existing.conversation_id != conversation.id or existing.body != cleaned:
                raise AppError(
                    status_code=409,
                    code="message_idempotency_conflict",
                    message="消息幂等键已用于其他内容",
                )
            return self._message(existing)
        message = await self.repository.create_message(
            conversation_id=conversation.id,
            sender_id=user_id,
            client_message_id=client_message_id,
            body=cleaned,
        )
        if message.conversation_id != conversation.id or message.body != cleaned:
            raise AppError(
                status_code=409,
                code="message_idempotency_conflict",
                message="消息幂等键已用于其他内容",
            )
        return self._message(message)

    async def mark_read(
        self, *, user_id: UUID, conversation_id: UUID, message_id: UUID
    ) -> ReadPositionResponse:
        await self._member(user_id, conversation_id)
        message = await self.repository.get_message(conversation_id, message_id)
        if message is None:
            raise AppError(status_code=404, code="message_not_found", message="消息不存在")
        state = await self.repository.mark_read(
            conversation_id=conversation_id, user_id=user_id, message=message
        )
        assert state.last_read_message_id is not None and state.last_read_at is not None
        return ReadPositionResponse(
            conversation_id=conversation_id,
            last_read_message_id=state.last_read_message_id,
            last_read_at=state.last_read_at,
        )

    async def _member(
        self, user_id: UUID, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation:
        conversation = await self.repository.get_member_conversation(
            user_id, conversation_id, for_update=for_update
        )
        if conversation is None:
            raise AppError(status_code=404, code="conversation_not_found", message="会话不存在")
        return conversation

    @staticmethod
    def _message(message: Message) -> ChatMessageResponse:
        return ChatMessageResponse.model_validate(message, from_attributes=True)

    @staticmethod
    def _require_verified(campus_verified: bool) -> None:
        if not campus_verified:
            raise AppError(
                status_code=403,
                code="campus_verification_required",
                message="请先完成校园认证",
            )

    @staticmethod
    def _encode_cursor(message: Message) -> str:
        values = {"created_at": message.created_at.isoformat(), "id": str(message.id)}
        return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> tuple[datetime, UUID]:
        try:
            padded = value + "=" * (-len(value) % 4)
            values = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True).decode())
            return datetime.fromisoformat(values["created_at"]), UUID(values["id"])
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise AppError(status_code=422, code="invalid_cursor", message="消息游标无效") from exc
