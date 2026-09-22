import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.exceptions import AppError
from app.models.trade import CreditEventType, CreditLedger
from app.services.credit import CreditService, credit_level


class MemoryCreditRepository:
    def __init__(self) -> None:
        self.ledgers: list[CreditLedger] = []
        self.admins: set[UUID] = set()

    async def append(
        self,
        *,
        user_id: UUID,
        event_type: CreditEventType,
        source_type: str,
        reference_id: UUID,
        delta: int,
        reason: str,
        actor_id: UUID | None = None,
        reversal_of_id: UUID | None = None,
        rule_version: str = "v1",
    ) -> tuple[CreditLedger, bool]:
        existing = next(
            (
                item
                for item in self.ledgers
                if item.user_id == user_id
                and item.event_type == event_type
                and item.reference_id == reference_id
            ),
            None,
        )
        if existing:
            return existing, False
        balance = next(
            (item.balance_after for item in reversed(self.ledgers) if item.user_id == user_id),
            100,
        )
        ledger = CreditLedger(
            id=uuid4(),
            user_id=user_id,
            event_type=event_type,
            source_type=source_type,
            reference_id=reference_id,
            rule_version=rule_version,
            delta=delta,
            balance_after=balance + delta,
            reason=reason,
            actor_id=actor_id,
            reversal_of_id=reversal_of_id,
            created_at=datetime.now(UTC),
        )
        self.ledgers.append(ledger)
        return ledger, True

    async def summary(self, user_id: UUID) -> int:
        return next(
            (item.balance_after for item in reversed(self.ledgers) if item.user_id == user_id),
            100,
        )

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        before_created_at: datetime | None,
        before_id: UUID | None,
        limit: int,
    ) -> list[CreditLedger]:
        del before_created_at, before_id
        return [item for item in reversed(self.ledgers) if item.user_id == user_id][:limit]

    async def recompute(self, user_id: UUID) -> tuple[int, bool]:
        balance = 100
        consistent = True
        for ledger in (item for item in self.ledgers if item.user_id == user_id):
            balance += ledger.delta
            consistent = consistent and ledger.balance_after == balance
        return balance, consistent

    async def has_any_role(self, user_id: UUID, role_codes: set[str]) -> bool:
        return user_id in self.admins and bool(role_codes & {"ADMIN", "SUPER_ADMIN"})

    async def get(self, ledger_id: UUID) -> CreditLedger | None:
        return next((item for item in self.ledgers if item.id == ledger_id), None)


def test_credit_starts_at_100_and_adjustments_are_idempotent() -> None:
    asyncio.run(_exercise_idempotent_adjustment())


async def _exercise_idempotent_adjustment() -> None:
    repository = MemoryCreditRepository()
    service = CreditService(repository)
    admin_id, user_id, request_id = uuid4(), uuid4(), uuid4()
    repository.admins.add(admin_id)

    initial = await service.summary(user_id)
    first = await service.adjust(
        actor_id=admin_id,
        user_id=user_id,
        delta=-5,
        reason="确认一次有效违规",
        request_id=request_id,
    )
    repeated = await service.adjust(
        actor_id=admin_id,
        user_id=user_id,
        delta=-5,
        reason="确认一次有效违规",
        request_id=request_id,
    )

    assert initial.balance == 100
    assert first.id == repeated.id
    assert len(repository.ledgers) == 1
    assert (await repository.recompute(user_id)) == (95, True)


def test_non_admin_cannot_adjust_credit() -> None:
    asyncio.run(_exercise_non_admin_rejected())


async def _exercise_non_admin_rejected() -> None:
    service = CreditService(MemoryCreditRepository())
    try:
        await service.adjust(
            actor_id=uuid4(),
            user_id=uuid4(),
            delta=3,
            reason="人工纠正测试记录",
            request_id=uuid4(),
        )
    except AppError as raised:
        assert raised.code == "credit_adjustment_forbidden"
    else:
        raise AssertionError("non-admin adjustment should be rejected")


def test_credit_levels_are_explainable_ranges() -> None:
    assert credit_level(120) == "excellent"
    assert credit_level(100) == "good"
    assert credit_level(70) == "caution"
    assert credit_level(69) == "restricted"
