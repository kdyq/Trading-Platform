from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_market_service
from app.schemas.market import (
    PublicCategoryResponse,
    PublicMarketSummaryResponse,
    PublicProductListResponse,
)
from app.services.market import MarketService

router = APIRouter()


@router.get("/categories", response_model=list[PublicCategoryResponse])
async def categories(
    service: Annotated[MarketService, Depends(get_market_service)],
) -> list[PublicCategoryResponse]:
    return await service.categories()


@router.get("/products", response_model=PublicProductListResponse)
async def products(
    service: Annotated[MarketService, Depends(get_market_service)],
    limit: Annotated[int, Query(ge=1, le=24)] = 8,
) -> PublicProductListResponse:
    return await service.latest_products(limit=limit)


@router.get("/summary", response_model=PublicMarketSummaryResponse)
async def summary(
    service: Annotated[MarketService, Depends(get_market_service)],
) -> PublicMarketSummaryResponse:
    return await service.summary()
