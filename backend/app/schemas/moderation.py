from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ModerationProductSummary(BaseModel):
    id: UUID
    seller_id: UUID
    seller_name: str
    title: str
    description: str
    price: Decimal
    status: str
    version: int
    image_urls: list[str]
    moderation_reason_code: str | None
    moderation_public_note: str | None
    created_at: datetime
    updated_at: datetime


class ModerationProductList(BaseModel):
    items: list[ModerationProductSummary]


class ProductModerationDecision(BaseModel):
    action: Literal["approve", "reject", "hide", "restore"]
    version: int = Field(ge=1)
    reason_code: str = Field(min_length=3, max_length=64)
    public_note: str = Field(min_length=5, max_length=500)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
