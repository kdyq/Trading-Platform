from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_order_service
from app.api.v1.routes.auth import get_auth_context
from app.models.trade import OrderStatus
from app.schemas.orders import (
    MeetingProposalCreate,
    MeetingProposalResponse,
    OrderAction,
    OrderCancel,
    OrderCreate,
    OrderDetailResponse,
    OrderDispute,
    OrderListResponse,
    OrderResponse,
    ReviewCreate,
    ReviewResponse,
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


@router.post("/{order_id}/deliver", response_model=OrderResponse)
async def mark_order_delivered(
    order_id: UUID,
    payload: OrderAction,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    return await service.mark_delivered(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        client_action_id=payload.client_action_id,
    )


@router.post("/{order_id}/complete", response_model=OrderResponse)
async def complete_order(
    order_id: UUID,
    payload: OrderAction,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    return await service.complete(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        client_action_id=payload.client_action_id,
    )


@router.post("/{order_id}/dispute", response_model=OrderResponse)
async def dispute_order(
    order_id: UUID,
    payload: OrderDispute,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderResponse:
    return await service.dispute(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        payload=payload,
    )


@router.get("", response_model=OrderListResponse)
async def list_orders(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
    role: Literal["buying", "selling"] = "buying",
    status: OrderStatus | None = None,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> OrderListResponse:
    return await service.list_orders(
        user_id=context.user.id,
        role=role,
        status=status,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{order_id}", response_model=OrderDetailResponse)
async def order_detail(
    order_id: UUID,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> OrderDetailResponse:
    return await service.detail(user_id=context.user.id, order_id=order_id)


@router.post("/{order_id}/reviews", response_model=ReviewResponse, status_code=201)
async def create_review(
    order_id: UUID,
    payload: ReviewCreate,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[OrderService, Depends(get_order_service)],
) -> ReviewResponse:
    return await service.create_review(
        user_id=context.user.id,
        campus_status=context.campus_verification_status,
        order_id=order_id,
        payload=payload,
    )
