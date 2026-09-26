import base64
import binascii
import json
import re
import unicodedata
from datetime import datetime
from uuid import UUID

from app.core.exceptions import AppError
from app.models.messaging import Conversation, Message
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    BlockedUsersResponse,
    ChatMessageResponse,
    ChatReportResponse,
    ConversationListResponse,
    ConversationSummary,
    MessagePageResponse,
    NotificationListResponse,
    NotificationPreferencesResponse,
    NotificationResponse,
    ReadPositionResponse,
)
from app.services.notifications import NotificationDeliveryCoordinator
from app.services.realtime import (
    ChatMessageLimiter,
    NullChatMessageLimiter,
    NullRealtimePublisher,
    RealtimePublisher,
)

LINK_PATTERN = re.compile(r"(?i)(?:https?://|www\.)")
MAX_MESSAGE_LINKS = 5


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        publisher: RealtimePublisher | None = None,
        limiter: ChatMessageLimiter | None = None,
        notification_delivery: NotificationDeliveryCoordinator | None = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher or NullRealtimePublisher()
        self.limiter = limiter or NullChatMessageLimiter()
        self.notification_delivery = notification_delivery

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
        await self.repository.lock_users(user_id, product.seller_id)
        if await self.repository.blocked_between(user_id, product.seller_id):
            raise AppError(status_code=403, code="chat_blocked", message="当前无法与该用户建立会话")
        conversation = await self.repository.create_or_get_conversation(
            product=product, buyer_id=user_id
        )
        records = await self.repository.list_conversations(
            user_id, 1, conversation_id=conversation.id
        )
        if not records:
            raise AppError(status_code=404, code="conversation_not_found", message="会话不存在")
        record = records[0]
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
        await self.repository.lock_users(conversation.buyer_id, conversation.seller_id)
        if await self.repository.blocked_between(conversation.buyer_id, conversation.seller_id):
            raise AppError(status_code=403, code="chat_blocked", message="当前会话已停止发送")
        await self.limiter.check(user_id, conversation_id)
        cleaned = body.strip()
        if not cleaned:
            raise AppError(status_code=422, code="empty_message", message="消息内容不能为空")
        if any(
            unicodedata.category(character) == "Cc" and character not in "\n\r\t"
            for character in cleaned
        ):
            raise AppError(
                status_code=422,
                code="invalid_message_body",
                message="消息包含不支持的控制字符",
            )
        if len(LINK_PATTERN.findall(cleaned)) > MAX_MESSAGE_LINKS:
            raise AppError(
                status_code=422,
                code="too_many_message_links",
                message=f"单条消息最多包含 {MAX_MESSAGE_LINKS} 个链接",
            )
        existing = await self.repository.get_message_by_client_key(user_id, client_message_id)
        if existing is not None:
            if existing.conversation_id != conversation.id or existing.body != cleaned:
                raise AppError(
                    status_code=409,
                    code="message_idempotency_conflict",
                    message="消息幂等键已用于其他内容",
                )
            return self._message(existing)
        result = await self.repository.create_message(
            conversation_id=conversation.id,
            sender_id=user_id,
            client_message_id=client_message_id,
            body=cleaned,
        )
        message = result.message
        if message.conversation_id != conversation.id or message.body != cleaned:
            raise AppError(
                status_code=409,
                code="message_idempotency_conflict",
                message="消息幂等键已用于其他内容",
            )
        response = self._message(message)
        if result.created:
            await self.repository.record_risk_flags(message.id, self._risk_flags(cleaned))
            recipient_id = (
                conversation.seller_id
                if user_id == conversation.buyer_id
                else conversation.buyer_id
            )
            notification = await self.repository.create_chat_notification(
                recipient_id=recipient_id, message=message
            )
            payload = {
                "type": "chat.message.created",
                "data": response.model_dump(mode="json"),
            }
            recipients = (conversation.buyer_id, conversation.seller_id)
            self.repository.after_commit(lambda: self.publisher.publish(recipients, payload))
            if notification is not None:
                notification_payload = {
                    "type": "notification.created",
                    "data": NotificationResponse.model_validate(
                        notification, from_attributes=True
                    ).model_dump(mode="json"),
                }
                if self.notification_delivery is not None:
                    delivery = self.notification_delivery
                    self.repository.after_commit(
                        lambda: delivery.deliver(
                            notification.id,
                            recipient_id,
                            notification_payload,
                        )
                    )
                else:
                    self.repository.after_commit(
                        lambda: self.publisher.publish((recipient_id,), notification_payload)
                    )
        return response

    async def mark_read(
        self, *, user_id: UUID, conversation_id: UUID, message_id: UUID
    ) -> ReadPositionResponse:
        conversation = await self._member(user_id, conversation_id)
        message = await self.repository.get_message(conversation_id, message_id)
        if message is None:
            raise AppError(status_code=404, code="message_not_found", message="消息不存在")
        state = await self.repository.mark_read(
            conversation_id=conversation_id, user_id=user_id, message=message
        )
        assert state.last_read_message_id is not None and state.last_read_at is not None
        response = ReadPositionResponse(
            conversation_id=conversation_id,
            last_read_message_id=state.last_read_message_id,
            last_read_at=state.last_read_at,
        )
        recipients = (conversation.buyer_id, conversation.seller_id)
        self.repository.after_commit(
            lambda: self.publisher.publish(
                recipients,
                {
                    "type": "chat.read-position.updated",
                    "data": {
                        **response.model_dump(mode="json"),
                        "user_id": str(user_id),
                    },
                },
            )
        )
        return response

    async def _member(
        self, user_id: UUID, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation:
        conversation = await self.repository.get_member_conversation(
            user_id, conversation_id, for_update=for_update
        )
        if conversation is None:
            raise AppError(status_code=404, code="conversation_not_found", message="会话不存在")
        return conversation

    async def block_user(self, *, user_id: UUID, blocked_id: UUID) -> None:
        if user_id == blocked_id:
            raise AppError(status_code=422, code="cannot_block_self", message="不能屏蔽自己")
        if not await self.repository.lock_users(user_id, blocked_id):
            raise AppError(status_code=404, code="user_not_found", message="用户不存在")
        await self.repository.block_user(user_id, blocked_id)

    async def unblock_user(self, *, user_id: UUID, blocked_id: UUID) -> None:
        await self.repository.unblock_user(user_id, blocked_id)

    async def blocked_users(self, user_id: UUID) -> BlockedUsersResponse:
        return BlockedUsersResponse(
            user_ids=list(await self.repository.list_blocked_user_ids(user_id))
        )

    async def report_message(
        self,
        *,
        user_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        reason_code: str,
        details: str | None,
    ) -> ChatReportResponse:
        await self._member(user_id, conversation_id)
        message = await self.repository.get_message(conversation_id, message_id)
        if message is None:
            raise AppError(status_code=404, code="message_not_found", message="消息不存在")
        report = await self.repository.report_message(
            reporter_id=user_id,
            subject_user_id=message.sender_id,
            message_id=message_id,
            reason_code=reason_code,
            details=details.strip() if details and details.strip() else None,
        )
        return ChatReportResponse(id=report.id, status=report.status.value)

    async def notifications(self, user_id: UUID) -> NotificationListResponse:
        records = await self.repository.list_notifications(user_id, 100)
        return NotificationListResponse(
            items=[
                NotificationResponse.model_validate(item, from_attributes=True) for item in records
            ],
            unread_count=await self.repository.unread_notification_count(user_id),
        )

    async def mark_notification_read(
        self, user_id: UUID, notification_id: UUID
    ) -> NotificationResponse:
        notification = await self.repository.mark_notification_read(user_id, notification_id)
        if notification is None:
            raise AppError(status_code=404, code="notification_not_found", message="通知不存在")
        return NotificationResponse.model_validate(notification, from_attributes=True)

    async def mark_all_notifications_read(self, user_id: UUID) -> int:
        return await self.repository.mark_all_notifications_read(user_id)

    async def preferences(self, user_id: UUID) -> NotificationPreferencesResponse:
        values = await self.repository.notification_preferences(user_id)
        return NotificationPreferencesResponse(
            chat=values.get("chat", True),
            order=values.get("order", True),
            moderation=values.get("moderation", True),
            report=values.get("report", True),
        )

    async def set_preference(
        self, user_id: UUID, category: str, enabled: bool
    ) -> NotificationPreferencesResponse:
        await self.repository.set_notification_preference(user_id, category, enabled)
        return await self.preferences(user_id)

    @staticmethod
    def _risk_flags(body: str) -> list[str]:
        keywords = {
            "verification_code": ("验证码", "短信码"),
            "identity_document": ("身份证", "学生证照片"),
            "off_platform_payment": ("先付款", "微信转账", "支付宝转账"),
        }
        return [flag for flag, terms in keywords.items() if any(term in body for term in terms)]

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
