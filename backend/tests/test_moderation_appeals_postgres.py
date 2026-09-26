import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.models.identity import User, UserStatus
from app.models.moderation import ModerationTargetType, Report, ReportAppeal, ReportStatus
from app.models.trade import CreditLedger
from app.repositories.credit import SqlAlchemyCreditRepository
from app.repositories.moderation import SqlAlchemyModerationRepository
from app.repositories.reports import SqlAlchemyReportRepository
from app.services.moderation import ModerationService


def test_violation_appeal_reversal_keeps_audit_and_reverses_credit() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_appeal(database_url_for_sqlalchemy(database_url)))


async def _exercise_appeal(database_url: str) -> None:
    schema = f"test_appeal_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    reporter_id, subject_id, first_reviewer, second_reviewer = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    role_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            for user_id, email in (
                (reporter_id, "appeal-reporter@example.com"),
                (subject_id, "appeal-subject@example.com"),
                (first_reviewer, "appeal-reviewer-1@example.com"),
                (second_reviewer, "appeal-reviewer-2@example.com"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, login_email_verified_at, "
                        "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'hash', '申诉测试用户', now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email},
                )
            await connection.execute(
                text("INSERT INTO roles (id, code, name) VALUES (:id, 'REVIEWER', '审核员')"),
                {"id": role_id},
            )
            for reviewer_id in (first_reviewer, second_reviewer):
                await connection.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:user, :role)"),
                    {"user": reviewer_id, "role": role_id},
                )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as session:
            reports = SqlAlchemyReportRepository(session)
            report, _ = await reports.create_or_get(
                reporter_id=reporter_id,
                target_type=ModerationTargetType.USER,
                target_id=subject_id,
                reason_code="fraud",
                details="提供了完整的违规事实说明",
                subject_user_id=subject_id,
            )
            evidence, _ = await reports.add_evidence(
                report_id=report.id,
                uploader_id=reporter_id,
                object_key=f"test/{uuid4()}.png",
                original_filename="evidence.png",
                media_type="image/png",
                size_bytes=16,
                sha256="a" * 64,
            )
            report_id, evidence_id = report.id, evidence.id

        def service(session: AsyncSession) -> ModerationService:
            return ModerationService(
                SqlAlchemyModerationRepository(session),
                SqlAlchemyCreditRepository(session),
                SqlAlchemyReportRepository(session),
            )

        async with factory.begin() as session:
            decided = await service(session).decide_report(
                moderator_id=first_reviewer,
                report_id=report_id,
                action="violate",
                expected_version=1,
                penalty_code="warn",
                penalty_points=5,
                public_result="核实存在违规，给予警告并扣减信用",
                internal_reason="证据与举报事实相互印证",
                evidence_ids=[evidence_id],
                request_id="appeal_violation_decision",
            )
            assert decided.status == ReportStatus.RESOLVED.value

        async with factory.begin() as session:
            appeal = await service(session).create_appeal(
                appellant_id=subject_id,
                report_id=report_id,
                details="原决定忽略了关键上下文，请求独立复核",
            )
            appeal_id = appeal.id

        async with factory.begin() as session:
            subject = await session.get(User, subject_id)
            assert subject is not None
            subject.status = UserStatus.SUSPENDED
            subject.suspension_source_report_id = None

        async with factory.begin() as session:
            with pytest.raises(AppError) as same_reviewer:
                await service(session).review_appeal(
                    reviewer_id=first_reviewer,
                    appeal_id=appeal_id,
                    action="reverse",
                    reason="尝试由原审核员复核",
                    override_reason=None,
                    request_id="appeal_same_reviewer",
                )
            assert same_reviewer.value.code == "independent_review_required"

        async with factory.begin() as session:
            reviewed = await service(session).review_appeal(
                reviewer_id=second_reviewer,
                appeal_id=appeal_id,
                action="reverse",
                reason="复核发现原证据不足以支持处罚",
                override_reason=None,
                request_id="appeal_reverse_decision",
            )
            assert reviewed.status == "reversed"

        async with factory() as session:
            stored_report = await session.get(Report, report_id)
            stored_appeal = await session.get(ReportAppeal, appeal_id)
            credit_sum = await session.scalar(
                select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                    CreditLedger.user_id == subject_id
                )
            )
            credit_count = await session.scalar(
                select(func.count(CreditLedger.id)).where(CreditLedger.user_id == subject_id)
            )
            assert stored_report is not None and stored_report.status == ReportStatus.DISMISSED
            assert stored_appeal is not None and stored_appeal.status == "reversed"
            assert credit_sum == 0
            assert credit_count == 2
            subject = await session.get(User, subject_id)
            assert subject is not None and subject.status == UserStatus.SUSPENDED
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
