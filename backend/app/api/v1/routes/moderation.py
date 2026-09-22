from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_moderation_service
from app.api.v1.routes.auth import get_auth_context
from app.models.catalog import ProductStatus
from app.schemas.moderation import (
    ModerationProductList,
    ModerationProductSummary,
    ProductModerationDecision,
)
from app.services.auth import AuthContext
from app.services.moderation import ModerationService

router = APIRouter()


@router.get("/products", response_model=ModerationProductList)
async def moderation_products(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
    status: ProductStatus = ProductStatus.PENDING_REVIEW,
) -> ModerationProductList:
    return await service.list_products(moderator_id=context.user.id, status=status)


@router.post("/products/{product_id}/decisions", response_model=ModerationProductSummary)
async def decide_product(
    product_id: UUID,
    payload: ProductModerationDecision,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[ModerationService, Depends(get_moderation_service)],
) -> ModerationProductSummary:
    return await service.decide_product(
        moderator_id=context.user.id,
        product_id=product_id,
        action=payload.action,
        expected_version=payload.version,
        reason_code=payload.reason_code,
        public_note=payload.public_note,
        request_id=payload.request_id,
    )
