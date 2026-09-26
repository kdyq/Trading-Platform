from collections.abc import Sequence
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Role, User, user_roles
from app.models.trade import CreditEventType, CreditLedger


class CreditRepository(Protocol):
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
    ) -> tuple[CreditLedger, bool]: ...

    async def summary(self, user_id: UUID) -> int: ...

    async def public_user_exists(self, user_id: UUID) -> bool: ...

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        before_sequence: int | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[CreditLedger]: ...

    async def recompute(self, user_id: UUID) -> tuple[int, bool]: ...

    async def has_any_role(self, user_id: UUID, role_codes: set[str]) -> bool: ...

    async def get(self, ledger_id: UUID) -> CreditLedger | None: ...

    async def find_source(
        self, user_id: UUID, event_type: CreditEventType, reference_id: UUID
    ) -> CreditLedger | None: ...


class SqlAlchemyCreditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:credit_key, 0))"),
            {"credit_key": f"credit:{user_id}"},
        )
        existing = await self.session.scalar(
            select(CreditLedger).where(
                CreditLedger.user_id == user_id,
                CreditLedger.event_type == event_type,
                CreditLedger.reference_id == reference_id,
            )
        )
        if existing is not None:
            return existing, False
        previous = await self.session.scalar(
            select(CreditLedger)
            .where(CreditLedger.user_id == user_id)
            .order_by(CreditLedger.sequence_no.desc())
            .limit(1)
        )
        ledger = CreditLedger(
            id=uuid4(),
            user_id=user_id,
            event_type=event_type,
            source_type=source_type,
            reference_id=reference_id,
            rule_version=rule_version,
            sequence_no=(previous.sequence_no if previous else 0) + 1,
            delta=delta,
            balance_after=(previous.balance_after if previous else 100) + delta,
            reason=reason,
            actor_id=actor_id,
            reversal_of_id=reversal_of_id,
        )
        self.session.add(ledger)
        await self.session.flush()
        return ledger, True

    async def summary(self, user_id: UUID) -> int:
        balance = await self.session.scalar(
            select(CreditLedger.balance_after)
            .where(CreditLedger.user_id == user_id)
            .order_by(CreditLedger.sequence_no.desc())
            .limit(1)
        )
        return int(balance) if balance is not None else 100

    async def public_user_exists(self, user_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.id == user_id, User.deleted_at.is_(None))
            )
        )

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        before_sequence: int | None,
        before_id: UUID | None,
        limit: int,
    ) -> Sequence[CreditLedger]:
        query = select(CreditLedger).where(CreditLedger.user_id == user_id)
        if before_sequence is not None:
            query = query.where(CreditLedger.sequence_no < before_sequence)
        return list(
            await self.session.scalars(query.order_by(CreditLedger.sequence_no.desc()).limit(limit))
        )

    async def recompute(self, user_id: UUID) -> tuple[int, bool]:
        ledgers = list(
            await self.session.scalars(
                select(CreditLedger)
                .where(CreditLedger.user_id == user_id)
                .order_by(CreditLedger.sequence_no)
            )
        )
        balance = 100
        consistent = True
        for ledger in ledgers:
            balance += ledger.delta
            consistent = consistent and ledger.balance_after == balance
        return balance, consistent

    async def has_any_role(self, user_id: UUID, role_codes: set[str]) -> bool:
        count = await self.session.scalar(
            select(func.count())
            .select_from(user_roles.join(Role, user_roles.c.role_id == Role.id))
            .where(
                user_roles.c.user_id == user_id,
                Role.code.in_(role_codes),
                Role.deleted_at.is_(None),
            )
        )
        return bool(count)

    async def get(self, ledger_id: UUID) -> CreditLedger | None:
        return cast(CreditLedger | None, await self.session.get(CreditLedger, ledger_id))

    async def find_source(
        self, user_id: UUID, event_type: CreditEventType, reference_id: UUID
    ) -> CreditLedger | None:
        return cast(
            CreditLedger | None,
            await self.session.scalar(
                select(CreditLedger).where(
                    CreditLedger.user_id == user_id,
                    CreditLedger.event_type == event_type,
                    CreditLedger.reference_id == reference_id,
                )
            ),
        )
