from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreditLedgerResponse(BaseModel):
    id: UUID
    event_type: str
    source_type: str
    reference_id: UUID
    delta: int
    balance_after: int
    reason: str
    rule_version: str
    created_at: datetime


class CreditSummaryResponse(BaseModel):
    balance: int
    level: str
    rule_version: str


class PublicCreditSummaryResponse(BaseModel):
    level: str
    range_label: str


class CreditLedgerListResponse(BaseModel):
    items: list[CreditLedgerResponse]
    next_cursor: str | None = None


class CreditAdjustmentRequest(BaseModel):
    user_id: UUID
    delta: int = Field(ge=-50, le=50)
    reason: str = Field(min_length=5, max_length=255)
    request_id: UUID
