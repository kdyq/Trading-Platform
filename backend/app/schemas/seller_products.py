from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.catalog import ProductCondition


class ProductImageReference(BaseModel):
    kind: Literal["existing", "upload"]
    id: UUID


class SellerProductCreate(BaseModel):
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=3000)
    price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    original_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    category_id: UUID | None = None
    campus_id: UUID | None = None
    condition: ProductCondition = ProductCondition.GOOD
    is_negotiable: bool = False
    delivery_notes: str | None = Field(default=None, max_length=500)


class SellerProductUpdate(BaseModel):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=3000)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    original_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    category_id: UUID | None = None
    campus_id: UUID | None = None
    condition: ProductCondition | None = None
    is_negotiable: bool | None = None
    delivery_notes: str | None = Field(default=None, max_length=500)
    images: list[ProductImageReference] | None = Field(default=None, max_length=8)


class ProductTransitionRequest(BaseModel):
    version: int = Field(ge=1)


class SellerProductImageResponse(BaseModel):
    id: UUID
    url: str
    thumbnail_url: str
    alt_text: str | None
    display_order: int


class SellerProductResponse(BaseModel):
    id: UUID
    title: str
    description: str
    price: Decimal
    original_price: Decimal | None
    category_id: UUID
    campus_id: UUID
    condition: str
    is_negotiable: bool
    delivery_notes: str | None
    status: str
    appeal_report_id: UUID | None = None
    version: int
    updated_at: datetime
    images: list[SellerProductImageResponse]


class SellerProductListResponse(BaseModel):
    items: list[SellerProductResponse]
