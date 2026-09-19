from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PublicCategoryResponse(BaseModel):
    id: UUID
    code: str
    name: str


class PublicCampusResponse(BaseModel):
    id: UUID
    name: str
    school_name: str


class PublicProductSummary(BaseModel):
    id: UUID
    title: str
    price: Decimal
    status: str
    published_at: datetime | None
    campus_name: str
    school_name: str
    seller_name: str
    seller_verified: bool
    category_code: str
    category_name: str
    condition: str
    is_negotiable: bool
    view_count: int = Field(ge=0)
    favorite_count: int = Field(ge=0)
    image_url: str | None = None
    image_alt: str | None = None


class PublicSellerTrustSummary(BaseModel):
    id: UUID
    display_name: str
    campus_verified: bool
    review_count: int = Field(ge=0)
    average_rating: Decimal | None
    completed_orders: int = Field(ge=0)


class PublicProductImageResponse(BaseModel):
    id: UUID
    url: str
    alt_text: str | None


class PublicProductDetailResponse(PublicProductSummary):
    description: str
    seller: PublicSellerTrustSummary
    images: list[PublicProductImageResponse]
    similar_products: list[PublicProductSummary]


class PublicProductListResponse(BaseModel):
    items: list[PublicProductSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class PublicMarketSummaryResponse(BaseModel):
    available_products: int = Field(ge=0)
    active_campuses: int = Field(ge=0)
    verified_sellers: int = Field(ge=0)


class FavoriteStatusResponse(BaseModel):
    favorited: bool
    favorite_count: int = Field(ge=0)
