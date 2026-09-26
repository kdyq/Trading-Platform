import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.models.moderation import ModerationTargetType, Report, ReportEvent, ReportStatus
from app.repositories.reports import SqlAlchemyReportRepository


def test_duplicate_reports_merge_and_events_remain_append_only() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_reports(database_url_for_sqlalchemy(database_url)))


async def _exercise_reports(database_url: str) -> None:
    schema = f"test_reports_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    reporter_id, target_id = uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            for user_id, email in (
                (reporter_id, "reporter@example.com"),
                (target_id, "target@example.com"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, login_email_verified_at, "
                        "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'hash', '测试用户', now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email},
                )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as session:
            repository = SqlAlchemyReportRepository(session)
            assert await repository.target_visible(
                reporter_id=reporter_id,
                target_type=ModerationTargetType.USER,
                target_id=target_id,
            )
            first, created = await repository.create_or_get(
                reporter_id=reporter_id,
                target_type=ModerationTargetType.USER,
                target_id=target_id,
                reason_code="fraud",
                details="疑似诱导转账，请核查",
            )
            repeated, repeated_created = await repository.create_or_get(
                reporter_id=reporter_id,
                target_type=ModerationTargetType.USER,
                target_id=target_id,
                reason_code="fraud",
                details="重复提交不应生成第二条",
            )
            assert created is True
            assert repeated_created is False
            assert repeated.id == first.id
            first.status = ReportStatus.WITHDRAWN
            await session.flush()
            renewed, renewed_created = await repository.create_or_get(
                reporter_id=reporter_id,
                target_type=ModerationTargetType.USER,
                target_id=target_id,
                reason_code="fraud",
                details="撤回后出现的新事实",
            )
            assert renewed_created is True
            assert renewed.id != first.id

        async with factory() as session:
            assert await session.scalar(select(func.count(Report.id))) == 2
            assert await session.scalar(select(func.count(ReportEvent.id))) == 2
            assert (
                await session.scalar(
                    select(func.count(Report.id)).where(Report.status == ReportStatus.OPEN)
                )
                == 1
            )
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
