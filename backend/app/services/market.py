from uuid import UUID

from app.core.exceptions import AppError
from app.repositories.market import (
    MarketRepository,
    PublicProductFilters,
    PublicProductImageRecord,
)
from app.schemas.market import (
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
        self, *, filters: PublicProductFilters, page: int, page_size: int
    ) -> PublicProductListResponse:
        records, total = await self.repository.search_products(
            filters=filters, offset=(page - 1) * page_size, limit=page_size
        )
        return PublicProductListResponse(
            items=[
                PublicProductSummary.model_validate(record, from_attributes=True)
                for record in records
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

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
