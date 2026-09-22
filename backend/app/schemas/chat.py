import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ConversationCreate(BaseModel):
    product_id: UUID


class ConversationSummary(BaseModel):
    id: UUID
    product_id: UUID
    product_title: str
    product_price: Decimal
    product_status: str
    other_user_id: UUID
    other_display_name: str
    last_message_at: datetime | None
    last_message_preview: str | None
    unread_count: int = Field(ge=0)
    is_buyer: bool


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]


class MessageSend(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(
            unicodedata.category(character) == "Cc" and character not in "\n\r\t"
            for character in value
        ):
            raise ValueError("消息包含不支持的控制字符")
        if len(re.findall(r"(?i)(?:https?://|www\.)", value)) > 5:
            raise ValueError("单条消息最多包含 5 个链接")
        return value


class ChatMessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_id: UUID
    client_message_id: str
    body: str
    created_at: datetime


class MessagePageResponse(BaseModel):
    items: list[ChatMessageResponse]
    next_cursor: str | None = None


class ReadPositionUpdate(BaseModel):
    message_id: UUID


class ReadPositionResponse(BaseModel):
    conversation_id: UUID
    last_read_message_id: UUID
    last_read_at: datetime


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int = Field(gt=0)


class BlockedUsersResponse(BaseModel):
    user_ids: list[UUID]


class ChatReportCreate(BaseModel):
    message_id: UUID
    reason_code: Literal["harassment", "fraud", "spam", "unsafe", "other"]
    details: str | None = Field(default=None, max_length=1000)


class ChatReportResponse(BaseModel):
    id: UUID
    status: str


class NotificationResponse(BaseModel):
    id: UUID
    category: str
    title: str
    summary: str
    target_type: str
    target_id: UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int = Field(ge=0)


class NotificationReadAllResponse(BaseModel):
    updated_count: int = Field(ge=0)


class NotificationPreferencesResponse(BaseModel):
    chat: bool
    order: bool
    moderation: bool
    report: bool


class NotificationPreferenceUpdate(BaseModel):
    category: Literal["chat", "order", "moderation", "report"]
    enabled: bool
