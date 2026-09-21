from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_order_service
from app.api.v1.routes.auth import get_auth_context
from app.schemas.orders import OrderAction, OrderCreate, OrderResponse
from app.services.auth import AuthContext
from app.services.orders import OrderService

router = APIRouter()


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    payload: OrderCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    return await service.create(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        payload=payload,
    )


@router.post("/{order_id}/accept", response_model=OrderResponse)
async def accept_order(
    order_id: UUID,
    payload: OrderAction,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    return await service.accept(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        client_action_id=payload.client_action_id,
    )
