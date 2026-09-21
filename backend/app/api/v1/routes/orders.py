from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import get_order_service
from app.api.v1.routes.auth import get_auth_context
from app.schemas.orders import (
    MeetingProposalCreate,
    MeetingProposalResponse,
    OrderAction,
    OrderCancel,
    OrderCreate,
    OrderResponse,
)
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


@router.post(
    "/{order_id}/meeting-proposals", response_model=MeetingProposalResponse, status_code=201
)
async def propose_meeting(
    order_id: UUID,
    payload: MeetingProposalCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> MeetingProposalResponse:
    return await service.propose_meeting(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        payload=payload,
    )


@router.post(
    "/{order_id}/meeting-proposals/{proposal_id}/confirm",
    response_model=MeetingProposalResponse,
)
async def confirm_meeting(
    order_id: UUID,
    proposal_id: UUID,
    payload: OrderAction,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> MeetingProposalResponse:
    return await service.confirm_meeting(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        proposal_id=proposal_id,
        client_action_id=payload.client_action_id,
    )


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    payload: OrderCancel,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    return await service.cancel(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        payload=payload,
    )
