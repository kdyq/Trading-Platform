from app.repositories.market import MarketRepository, PublicProductFilters
from app.schemas.market import (
    PublicCampusResponse,
    PublicCategoryResponse,
    PublicMarketSummaryResponse,
    PublicProductListResponse,
    PublicProductSummary,
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
