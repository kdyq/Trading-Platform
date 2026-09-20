from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.api.dependencies import get_market_service, get_settings_from_request
from app.core.config import Settings
from app.core.exceptions import AppError
from app.models.catalog import ProductCondition, ProductStatus
from app.repositories.market import PublicProductFilters
from app.schemas.market import (
    PublicCampusResponse,
    PublicCategoryResponse,
    PublicMarketSummaryResponse,
    PublicProductDetailResponse,
    PublicProductListResponse,
)
from app.services.market import MarketService
from app.services.product_storage import PublicProductStorage

router = APIRouter()


@router.get("/categories", response_model=list[PublicCategoryResponse])
async def categories(
    service: Annotated[MarketService, Depends(get_market_service)],
) -> list[PublicCategoryResponse]:
    return await service.categories()


@router.get("/campuses", response_model=list[PublicCampusResponse])
async def campuses(
    service: Annotated[MarketService, Depends(get_market_service)],
) -> list[PublicCampusResponse]:
    return await service.campuses()


@router.get("/products", response_model=PublicProductListResponse)
async def products(
    service: Annotated[MarketService, Depends(get_market_service)],
    limit: Annotated[int | None, Query(ge=1, le=24)] = None,
    keyword: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    campus: UUID | None = None,
    min_price: Annotated[Decimal | None, Query(ge=0)] = None,
    max_price: Annotated[Decimal | None, Query(ge=0)] = None,
    condition: ProductCondition | None = None,
    negotiable: bool | None = None,
    status: Literal[ProductStatus.ON_SALE, ProductStatus.RESERVED, ProductStatus.SOLD]
    | None = None,
    sort: Literal["newest", "price_asc", "price_desc"] = "newest",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=24)] = 12,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1000)] = None,
) -> PublicProductListResponse:
    if limit is not None:
        return await service.latest_products(limit=limit)
    if min_price is not None and max_price is not None and min_price > max_price:
        raise AppError(
            status_code=422,
            code="invalid_price_range",
            message="最低价不能高于最高价",
        )
    if page > 1 and cursor is None:
        raise AppError(status_code=422, code="cursor_required", message="后续分页需要游标")
    return await service.search(
        filters=PublicProductFilters(
            keyword=keyword,
            category=category,
            campus_id=campus,
            min_price=min_price,
            max_price=max_price,
            condition=condition,
            negotiable=negotiable,
            status=ProductStatus(status) if status else None,
            sort=sort,
        ),
        page=page,
        page_size=page_size,
        cursor=cursor,
    )


@router.get("/products/{product_id}", response_model=PublicProductDetailResponse)
async def product_detail(
    product_id: UUID,
    service: Annotated[MarketService, Depends(get_market_service)],
) -> PublicProductDetailResponse:
    return await service.product_detail(product_id)


@router.get("/product-images/{image_id}", response_class=FileResponse)
async def product_image(
    image_id: UUID,
    service: Annotated[MarketService, Depends(get_market_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> FileResponse:
    image = await service.product_image(image_id)
    stored = PublicProductStorage(settings.resolved_public_product_storage_root).resolve(
        image.object_key
    )
    return FileResponse(
        stored.path,
        media_type=stored.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/product-image-thumbnails/{image_id}", response_class=FileResponse)
async def product_image_thumbnail(
    image_id: UUID,
    service: Annotated[MarketService, Depends(get_market_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> FileResponse:
    image = await service.product_image(image_id)
    stored = PublicProductStorage(settings.resolved_public_product_storage_root).resolve(
        image.thumbnail_object_key
    )
    return FileResponse(
        stored.path,
        media_type=stored.media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/summary", response_model=PublicMarketSummaryResponse)
async def summary(
    service: Annotated[MarketService, Depends(get_market_service)],
) -> PublicMarketSummaryResponse:
    return await service.summary()
