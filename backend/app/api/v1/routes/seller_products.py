from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.dependencies import get_seller_product_service, get_settings_from_request
from app.api.v1.routes.auth import get_auth_context
from app.core.config import Settings
from app.schemas.seller_products import (
    ProductTransitionRequest,
    SellerProductCreate,
    SellerProductListResponse,
    SellerProductResponse,
    SellerProductUpdate,
)
from app.services.auth import AuthContext
from app.services.product_storage import PublicProductStorage
from app.services.seller_products import SellerProductService

router = APIRouter()


@router.post("", response_model=SellerProductResponse, status_code=201)
async def create_product(
    payload: SellerProductCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.create(context.user.id, payload)


@router.get("", response_model=SellerProductListResponse)
async def list_products(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductListResponse:
    return await service.list_owned(context.user.id)


@router.get("/{product_id}", response_model=SellerProductResponse)
async def get_product(
    product_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.get_owned(context.user.id, product_id)


@router.get("/{product_id}/images/{image_id}", response_class=FileResponse)
async def get_product_image(
    product_id: UUID,
    image_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> FileResponse:
    image = await service.owned_image(context.user.id, product_id, image_id)
    stored = PublicProductStorage(settings.resolved_public_product_storage_root).resolve(
        image.object_key
    )
    return FileResponse(
        stored.path, media_type=stored.media_type, headers={"Cache-Control": "private, no-store"}
    )


@router.get("/{product_id}/images/{image_id}/thumbnail", response_class=FileResponse)
async def get_product_image_thumbnail(
    product_id: UUID,
    image_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
    settings: Annotated[Settings, Depends(get_settings_from_request)],
) -> FileResponse:
    image = await service.owned_image(context.user.id, product_id, image_id)
    stored = PublicProductStorage(settings.resolved_public_product_storage_root).resolve(
        image.thumbnail_object_key
    )
    return FileResponse(
        stored.path, media_type=stored.media_type, headers={"Cache-Control": "private, no-store"}
    )


@router.patch("/{product_id}", response_model=SellerProductResponse)
async def update_product(
    product_id: UUID,
    payload: SellerProductUpdate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.update(context.user.id, product_id, payload)


@router.post("/{product_id}/submit", response_model=SellerProductResponse)
async def submit_product(
    product_id: UUID,
    payload: ProductTransitionRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.submit(context.user.id, product_id, payload.version)


@router.post("/{product_id}/withdraw", response_model=SellerProductResponse)
async def withdraw_product(
    product_id: UUID,
    payload: ProductTransitionRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.withdraw(context.user.id, product_id, payload.version)


@router.post("/{product_id}/hide", response_model=SellerProductResponse)
async def hide_product(
    product_id: UUID,
    payload: ProductTransitionRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.hide(context.user.id, product_id, payload.version)


@router.post("/{product_id}/sold", response_model=SellerProductResponse)
async def mark_product_sold(
    product_id: UUID,
    payload: ProductTransitionRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[SellerProductService, Depends(get_seller_product_service)],
) -> SellerProductResponse:
    return await service.mark_sold(context.user.id, product_id, payload.version)
