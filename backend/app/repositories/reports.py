from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Product
from app.models.identity import User
from app.models.messaging import Conversation, Message
from app.models.moderation import (
    ModerationTargetType,
    Report,
    ReportEvent,
    ReportEvidence,
    ReportStatus,
)
from app.models.trade import Order


class SqlAlchemyReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def target_visible(
        self, *, reporter_id: UUID, target_type: ModerationTargetType, target_id: UUID
    ) -> bool:
        if target_type == ModerationTargetType.PRODUCT:
            return bool(
                await self.session.scalar(
                    select(func.count())
                    .select_from(Product)
                    .where(Product.id == target_id, Product.deleted_at.is_(None))
                )
            )
        if target_type == ModerationTargetType.USER:
            if target_id == reporter_id:
                return False
            return bool(
                await self.session.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.id == target_id, User.deleted_at.is_(None))
                )
            )
        if target_type == ModerationTargetType.ORDER:
            return bool(
                await self.session.scalar(
                    select(func.count())
                    .select_from(Order)
                    .where(
                        Order.id == target_id,
                        or_(Order.buyer_id == reporter_id, Order.seller_id == reporter_id),
                    )
                )
            )
        if target_type == ModerationTargetType.MESSAGE:
            return bool(
                await self.session.scalar(
                    select(func.count())
                    .select_from(Message)
                    .join(Conversation, Conversation.id == Message.conversation_id)
                    .where(
                        Message.id == target_id,
                        or_(
                            Conversation.buyer_id == reporter_id,
                            Conversation.seller_id == reporter_id,
                        ),
                    )
                )
            )
        return False

    async def target_subject(
        self, *, reporter_id: UUID, target_type: ModerationTargetType, target_id: UUID
    ) -> UUID | None:
        if not await self.target_visible(
            reporter_id=reporter_id, target_type=target_type, target_id=target_id
        ):
            return None
        if target_type == ModerationTargetType.PRODUCT:
            subject = await self.session.scalar(
                select(Product.seller_id).where(Product.id == target_id)
            )
        elif target_type == ModerationTargetType.USER:
            subject = target_id
        elif target_type == ModerationTargetType.MESSAGE:
            subject = await self.session.scalar(
                select(Message.sender_id).where(Message.id == target_id)
            )
        elif target_type == ModerationTargetType.ORDER:
            order = await self.session.get(Order, target_id)
            subject = (
                order.seller_id
                if order is not None and order.buyer_id == reporter_id
                else (order.buyer_id if order is not None else None)
            )
        else:
            subject = None
        return subject if subject != reporter_id else None

    async def recent_count(self, reporter_id: UUID) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(Report)
            .where(
                Report.reporter_id == reporter_id,
                Report.created_at >= datetime.now(UTC) - timedelta(hours=1),
            )
        )
        return int(count or 0)

    async def lock_reporter(self, reporter_id: UUID) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:report_key, 0))"),
            {"report_key": f"report-rate:{reporter_id}"},
        )

    async def create_or_get(
        self,
        *,
        reporter_id: UUID,
        target_type: ModerationTargetType,
        target_id: UUID,
        reason_code: str,
        details: str,
        subject_user_id: UUID | None = None,
    ) -> tuple[Report, bool]:
        report_id = uuid4()
        inserted = await self.session.scalar(
            insert(Report)
            .values(
                id=report_id,
                reporter_id=reporter_id,
                target_type=target_type,
                target_id=target_id,
                reason_code=reason_code,
                details=details,
                subject_user_id=subject_user_id,
                status=ReportStatus.OPEN,
                version=1,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    Report.reporter_id,
                    Report.target_type,
                    Report.target_id,
                    Report.reason_code,
                ],
                index_where=text("status IN ('open', 'reviewing')"),
            )
            .returning(Report.id)
        )
        report = await self.session.scalar(
            select(Report)
            .where(
                Report.reporter_id == reporter_id,
                Report.target_type == target_type,
                Report.target_id == target_id,
                Report.reason_code == reason_code,
                Report.status.in_((ReportStatus.OPEN, ReportStatus.REVIEWING)),
            )
            .order_by(Report.created_at.desc(), Report.id.desc())
        )
        assert report is not None
        if inserted is not None:
            self.add_event(
                report=report,
                actor_id=reporter_id,
                from_status=None,
                to_status=ReportStatus.OPEN,
                public_note="举报已提交",
            )
        return report, inserted is not None

    async def find_key(
        self,
        *,
        reporter_id: UUID,
        target_type: ModerationTargetType,
        target_id: UUID,
        reason_code: str,
    ) -> Report | None:
        return cast(
            Report | None,
            await self.session.scalar(
                select(Report)
                .where(
                    Report.reporter_id == reporter_id,
                    Report.target_type == target_type,
                    Report.target_id == target_id,
                    Report.reason_code == reason_code,
                    Report.status.in_((ReportStatus.OPEN, ReportStatus.REVIEWING)),
                )
                .order_by(Report.created_at.desc(), Report.id.desc())
            ),
        )

    async def get_owned(
        self, report_id: UUID, reporter_id: UUID, *, lock: bool = False
    ) -> Report | None:
        query = select(Report).where(Report.id == report_id, Report.reporter_id == reporter_id)
        if lock:
            query = query.with_for_update()
        return cast(Report | None, await self.session.scalar(query))

    async def list_owned(self, reporter_id: UUID) -> Sequence[Report]:
        return list(
            await self.session.scalars(
                select(Report)
                .where(Report.reporter_id == reporter_id)
                .order_by(Report.updated_at.desc(), Report.id.desc())
            )
        )

    async def evidence(self, report_id: UUID) -> Sequence[ReportEvidence]:
        return list(
            await self.session.scalars(
                select(ReportEvidence)
                .where(ReportEvidence.report_id == report_id)
                .order_by(ReportEvidence.created_at, ReportEvidence.id)
            )
        )

    async def events(self, report_id: UUID) -> Sequence[ReportEvent]:
        return list(
            await self.session.scalars(
                select(ReportEvent)
                .where(ReportEvent.report_id == report_id)
                .order_by(ReportEvent.created_at, ReportEvent.id)
            )
        )

    async def add_evidence(
        self,
        *,
        report_id: UUID,
        uploader_id: UUID,
        object_key: str,
        original_filename: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
    ) -> tuple[ReportEvidence, bool]:
        evidence_id = uuid4()
        inserted = await self.session.scalar(
            insert(ReportEvidence)
            .values(
                id=evidence_id,
                report_id=report_id,
                uploader_id=uploader_id,
                object_key=object_key,
                original_filename=original_filename,
                media_type=media_type,
                size_bytes=size_bytes,
                sha256=sha256,
            )
            .on_conflict_do_nothing(constraint="uq_report_evidence_content")
            .returning(ReportEvidence.id)
        )
        evidence = await self.session.scalar(
            select(ReportEvidence).where(
                ReportEvidence.report_id == report_id, ReportEvidence.sha256 == sha256
            )
        )
        assert evidence is not None
        return evidence, inserted is not None

    async def get_evidence(self, evidence_id: UUID) -> ReportEvidence | None:
        return cast(ReportEvidence | None, await self.session.get(ReportEvidence, evidence_id))

    def add_event(
        self,
        *,
        report: Report,
        actor_id: UUID | None,
        from_status: ReportStatus | None,
        to_status: ReportStatus,
        public_note: str | None,
        event_data: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            ReportEvent(
                id=uuid4(),
                report_id=report.id,
                actor_id=actor_id,
                from_status=from_status,
                to_status=to_status,
                public_note=public_note,
                event_data=event_data or {},
            )
        )
