from app.repositories.market import MarketRepository
from app.schemas.market import (
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
