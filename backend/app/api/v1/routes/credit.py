from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_credit_service
from app.api.v1.routes.auth import get_auth_context
from app.core.exceptions import AppError
from app.schemas.credit import (
    CreditAdjustmentRequest,
    CreditLedgerListResponse,
    CreditLedgerResponse,
    CreditSummaryResponse,
    PublicCreditSummaryResponse,
)
from app.services.auth import AuthContext
from app.services.credit import CreditService

router = APIRouter()


def parse_cursor(cursor: str | None) -> tuple[int | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        sequence, raw_id = cursor.rsplit("|", 1)
        parsed_sequence = int(sequence)
        if parsed_sequence < 1:
            raise ValueError
        return parsed_sequence, UUID(raw_id)
    except (ValueError, TypeError) as exc:
        raise AppError(
            status_code=422, code="credit_cursor_invalid", message="信用流水游标无效"
        ) from exc


@router.get("/me", response_model=CreditSummaryResponse)
async def my_credit(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> CreditSummaryResponse:
    return await service.summary(context.user.id)


@router.get("/users/{user_id}/summary", response_model=PublicCreditSummaryResponse)
async def public_credit_summary(
    user_id: UUID,
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> PublicCreditSummaryResponse:
    return await service.public_summary(user_id)


@router.get("/me/ledgers", response_model=CreditLedgerListResponse)
async def my_credit_ledgers(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CreditService, Depends(get_credit_service)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CreditLedgerListResponse:
    before_sequence, before_id = parse_cursor(cursor)
    return await service.list(
        user_id=context.user.id,
        before_sequence=before_sequence,
        before_id=before_id,
        limit=limit,
    )


@router.post("/adjustments", response_model=CreditLedgerResponse)
async def create_adjustment(
    payload: CreditAdjustmentRequest,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CreditService, Depends(get_credit_service)],
) -> CreditLedgerResponse:
    return await service.adjust(
        actor_id=context.user.id,
        user_id=payload.user_id,
        delta=payload.delta,
        reason=payload.reason,
        request_id=payload.request_id,
    )
