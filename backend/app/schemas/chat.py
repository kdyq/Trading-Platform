from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


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


class ConversationListResponse(BaseModel):
    items: list[ConversationSummary]


class MessageSend(BaseModel):
    client_message_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    body: str = Field(min_length=1, max_length=2000)


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
