from datetime import datetime
from uuid import UUID

from app.core.exceptions import AppError
from app.models.trade import CreditEventType, CreditLedger
from app.repositories.credit import CreditRepository
from app.schemas.credit import (
    CreditLedgerListResponse,
    CreditLedgerResponse,
    CreditSummaryResponse,
)

RULE_VERSION = "v1"


def credit_level(balance: int) -> str:
    if balance >= 120:
        return "excellent"
    if balance >= 90:
        return "good"
    if balance >= 70:
        return "caution"
    return "restricted"


def ledger_response(ledger: CreditLedger) -> CreditLedgerResponse:
    return CreditLedgerResponse(
        id=ledger.id,
        event_type=ledger.event_type.value,
        source_type=ledger.source_type,
        reference_id=ledger.reference_id,
        delta=ledger.delta,
        balance_after=ledger.balance_after,
        reason=ledger.reason,
        rule_version=ledger.rule_version,
        created_at=ledger.created_at,
    )


class CreditService:
    def __init__(self, repository: CreditRepository) -> None:
        self.repository = repository

    async def summary(self, user_id: UUID) -> CreditSummaryResponse:
        balance = await self.repository.summary(user_id)
        return CreditSummaryResponse(
            balance=balance,
            level=credit_level(balance),
            rule_version=RULE_VERSION,
        )

    async def list(
        self,
        *,
        user_id: UUID,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> CreditLedgerListResponse:
        ledgers = list(
            await self.repository.list_for_user(
                user_id=user_id,
                before_created_at=before_created_at,
                before_id=before_id,
                limit=limit + 1,
            )
        )
        has_more = len(ledgers) > limit
        items = ledgers[:limit]
        cursor = None
        if has_more and items:
            last = items[-1]
            cursor = f"{last.created_at.isoformat()}|{last.id}"
        return CreditLedgerListResponse(
            items=[ledger_response(item) for item in items], next_cursor=cursor
        )

    async def adjust(
        self,
        *,
        actor_id: UUID,
        user_id: UUID,
        delta: int,
        reason: str,
        request_id: UUID,
    ) -> CreditLedgerResponse:
        if not await self.repository.has_any_role(actor_id, {"ADMIN", "SUPER_ADMIN"}):
            raise AppError(
                status_code=403, code="credit_adjustment_forbidden", message="无权纠正信用"
            )
        if delta == 0:
            raise AppError(status_code=422, code="credit_delta_invalid", message="信用变动不能为零")
        ledger, created = await self.repository.append(
            user_id=user_id,
            event_type=CreditEventType.MODERATION_ADJUSTMENT,
            source_type="admin_adjustment",
            reference_id=request_id,
            delta=delta,
            reason=reason.strip(),
            actor_id=actor_id,
        )
        if not created and (
            ledger.delta != delta or ledger.reason != reason.strip() or ledger.actor_id != actor_id
        ):
            raise AppError(
                status_code=409,
                code="credit_adjustment_conflict",
                message="该纠正请求已用于不同内容",
            )
        return ledger_response(ledger)

    async def reverse(
        self, *, actor_id: UUID, ledger_id: UUID, reason: str, reference_id: UUID
    ) -> CreditLedgerResponse:
        original = await self.repository.get(ledger_id)
        if original is None:
            raise AppError(
                status_code=404, code="credit_ledger_not_found", message="信用流水不存在"
            )
        ledger, _ = await self.repository.append(
            user_id=original.user_id,
            event_type=CreditEventType.PENALTY_REVERSAL,
            source_type="penalty_reversal",
            reference_id=reference_id,
            delta=-original.delta,
            reason=reason,
            actor_id=actor_id,
            reversal_of_id=original.id,
        )
        return ledger_response(ledger)
