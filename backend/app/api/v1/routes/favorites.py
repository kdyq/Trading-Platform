from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_market_service
from app.api.v1.routes.auth import get_auth_context
from app.schemas.market import FavoriteStatusResponse, PublicProductListResponse
from app.services.auth import AuthContext
from app.services.market import MarketService

router = APIRouter()


@router.get("", response_model=PublicProductListResponse)
async def favorites(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[MarketService, Depends(get_market_service)],
) -> PublicProductListResponse:
    return await service.favorites(context.user.id)


@router.get("/{product_id}", response_model=FavoriteStatusResponse)
async def favorite_status(
    product_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[MarketService, Depends(get_market_service)],
) -> FavoriteStatusResponse:
    return await service.favorite_status(context.user.id, product_id)


@router.put("/{product_id}", response_model=FavoriteStatusResponse)
async def add_favorite(
    product_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[MarketService, Depends(get_market_service)],
) -> FavoriteStatusResponse:
    return await service.add_favorite(context.user.id, product_id)


@router.delete("/{product_id}", status_code=204)
async def remove_favorite(
    product_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[MarketService, Depends(get_market_service)],
) -> Response:
    await service.remove_favorite(context.user.id, product_id)
    return Response(status_code=204)
