from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OrderCreate(BaseModel):
    product_id: UUID
    conversation_id: UUID | None = None
    idempotency_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class OrderAction(BaseModel):
    client_action_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class MeetingProposalCreate(OrderAction):
    proposed_for: datetime
    location_text: str = Field(min_length=2, max_length=200)


class OrderCancel(OrderAction):
    reason_code: str = Field(pattern=r"^(changed_mind|schedule_failed|item_issue|other)$")
    note: str | None = Field(default=None, max_length=500)


class OrderDispute(OrderAction):
    reason_code: str = Field(pattern=r"^(item_not_as_described|no_show|safety_concern|other)$")
    details: str = Field(min_length=5, max_length=1000)


class MeetingProposalResponse(BaseModel):
    id: UUID
    order_id: UUID
    proposer_id: UUID
    proposed_for: datetime
    location_text: str
    status: str
    buyer_confirmed_at: datetime | None
    seller_confirmed_at: datetime | None
    created_at: datetime


class OrderResponse(BaseModel):
    id: UUID
    product_id: UUID
    conversation_id: UUID | None
    buyer_id: UUID
    seller_id: UUID
    amount: Decimal
    status: str
    product_title: str
    campus_name: str
    buyer_display_name: str
    seller_display_name: str
    payment_mode: str
    expires_at: datetime | None
    scheduled_for: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
