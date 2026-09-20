import base64
import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.core.exceptions import AppError
from app.repositories.market import (
    MarketRepository,
    PublicProductCursor,
    PublicProductFilters,
    PublicProductImageRecord,
    PublicProductRecord,
)
from app.schemas.market import (
    FavoriteStatusResponse,
    PublicCampusResponse,
    PublicCategoryResponse,
    PublicMarketSummaryResponse,
    PublicProductDetailResponse,
    PublicProductImageResponse,
    PublicProductListResponse,
    PublicProductSummary,
    PublicSellerTrustSummary,
)


class MarketService:
    def __init__(self, repository: MarketRepository) -> None:
        self.repository = repository

    async def categories(self) -> list[PublicCategoryResponse]:
        categories = await self.repository.list_categories()
        return [
            PublicCategoryResponse(id=item.id, code=item.code, name=item.name)
            for item in categories
        ]

    async def campuses(self) -> list[PublicCampusResponse]:
        records = await self.repository.list_campuses()
        return [
            PublicCampusResponse(id=campus_id, name=name, school_name=school_name)
            for campus_id, name, school_name in records
        ]

    async def latest_products(self, *, limit: int) -> PublicProductListResponse:
        records = await self.repository.list_latest_products(limit=limit)
        return PublicProductListResponse(
            items=[
                PublicProductSummary.model_validate(record, from_attributes=True)
                for record in records
            ],
            total=await self.repository.count_latest_products(),
            page=1,
            page_size=limit,
        )

    async def summary(self) -> PublicMarketSummaryResponse:
        counts = await self.repository.get_summary()
        return PublicMarketSummaryResponse.model_validate(counts, from_attributes=True)

    async def search(
        self,
        *,
        filters: PublicProductFilters,
        page: int,
        page_size: int,
        cursor: str | None = None,
    ) -> PublicProductListResponse:
        decoded_cursor: PublicProductCursor | None = None
        if cursor:
            decoded_cursor = self._decode_cursor(cursor, filters.sort)
        records, total = await self.repository.search_products(
            filters=filters, cursor=decoded_cursor, limit=page_size
        )
        return PublicProductListResponse(
            items=[
                PublicProductSummary.model_validate(record, from_attributes=True)
                for record in records
            ],
            total=total,
            page=page,
            page_size=page_size,
            next_cursor=self._encode_cursor(records[-1], filters.sort)
            if len(records) == page_size and page * page_size < total
            else None,
        )

    @staticmethod
    def _encode_cursor(record: PublicProductRecord, sort: str) -> str:
        values: dict[str, object] = {
            "id": str(record.id),
            "sort": sort,
            "price": str(record.price) if sort.startswith("price_") else None,
            "published_at": record.published_at.isoformat()
            if sort == "newest" and record.published_at is not None
            else None,
            "created_at": record.created_at.isoformat() if sort == "newest" else None,
        }
        return MarketService._encode_cursor_values(values)

    @staticmethod
    def _decode_cursor(value: str, sort: str) -> PublicProductCursor:
        try:
            values = MarketService._cursor_values(value)
            if values["sort"] != sort:
                raise ValueError
            product_id = values["id"]
            price = values.get("price")
            published_at = values.get("published_at")
            created_at = values.get("created_at")
            if not isinstance(product_id, str):
                raise ValueError
            if price is not None and not isinstance(price, str):
                raise ValueError
            if published_at is not None and not isinstance(published_at, str):
                raise ValueError
            if created_at is not None and not isinstance(created_at, str):
                raise ValueError
            return PublicProductCursor(
                product_id=UUID(product_id),
                price=Decimal(price) if price is not None else None,
                published_at=datetime.fromisoformat(published_at)
                if published_at is not None
                else None,
                created_at=datetime.fromisoformat(created_at) if created_at is not None else None,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AppError(status_code=422, code="invalid_cursor", message="分页游标无效") from exc

    @staticmethod
    def _cursor_values(value: str) -> dict[str, object]:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(decoded, dict):
            raise ValueError
        return decoded

    @staticmethod
    def _encode_cursor_values(values: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")

    async def product_detail(self, product_id: UUID) -> PublicProductDetailResponse:
        record = await self.repository.get_product(product_id)
        if record is None:
            raise AppError(status_code=404, code="product_not_found", message="商品不存在或不可见")
        similar = await self.repository.list_similar_products(
            product_id=record.id, category_id=record.category_id, limit=4
        )
        images = await self.repository.list_product_images(record.id)
        summary = PublicProductSummary.model_validate(record, from_attributes=True)
        return PublicProductDetailResponse(
            **summary.model_dump(),
            description=record.description,
            seller=PublicSellerTrustSummary(
                id=record.seller_id,
                display_name=record.seller_name,
                campus_verified=record.seller_verified,
                review_count=record.seller_review_count,
                average_rating=record.seller_average_rating,
                completed_orders=record.seller_completed_orders,
            ),
            images=[
                PublicProductImageResponse(
                    id=image.id,
                    url=f"/api/v1/market/product-images/{image.id}",
                    alt_text=image.alt_text,
                )
                for image in images
            ],
            similar_products=[
                PublicProductSummary.model_validate(item, from_attributes=True) for item in similar
            ],
        )

    async def product_image(self, image_id: UUID) -> PublicProductImageRecord:
        image = await self.repository.get_product_image(image_id)
        if image is None:
            raise AppError(
                status_code=404, code="product_image_not_found", message="商品图片不存在"
            )
        return image

    async def add_favorite(self, user_id: UUID, product_id: UUID) -> FavoriteStatusResponse:
        if not await self.repository.add_favorite(user_id, product_id):
            raise AppError(
                status_code=404, code="product_not_found", message="商品不存在或不可收藏"
            )
        return await self.favorite_status(user_id, product_id)

    async def remove_favorite(self, user_id: UUID, product_id: UUID) -> None:
        await self.repository.remove_favorite(user_id, product_id)

    async def favorite_status(self, user_id: UUID, product_id: UUID) -> FavoriteStatusResponse:
        favorited, count = await self.repository.favorite_status(user_id, product_id)
        return FavoriteStatusResponse(favorited=favorited, favorite_count=count)

    async def favorites(self, user_id: UUID) -> PublicProductListResponse:
        records = await self.repository.list_favorites(user_id)
        return PublicProductListResponse(
            items=[
                PublicProductSummary.model_validate(record, from_attributes=True)
                for record in records
            ],
            total=len(records),
            page=1,
            page_size=max(1, len(records)),
        )
