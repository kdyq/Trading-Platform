from datetime import datetime
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
)
from app.services.auth import AuthContext
from app.services.credit import CreditService

router = APIRouter()


def parse_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        timestamp, raw_id = cursor.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), UUID(raw_id)
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


@router.get("/me/ledgers", response_model=CreditLedgerListResponse)
async def my_credit_ledgers(
    context: Annotated[AuthContext, Depends(get_auth_context)],
    service: Annotated[CreditService, Depends(get_credit_service)],
    cursor: Annotated[str | None, Query(min_length=1, max_length=1000)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> CreditLedgerListResponse:
    before_created_at, before_id = parse_cursor(cursor)
    return await service.list(
        user_id=context.user.id,
        before_created_at=before_created_at,
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
