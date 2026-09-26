import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.models.trade import CreditEventType
from app.repositories.credit import SqlAlchemyCreditRepository


def test_credit_sequence_follows_append_order_across_transactions() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_credit(database_url_for_sqlalchemy(database_url)))


async def _exercise_credit(database_url: str) -> None:
    schema = f"test_credit_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    user_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, login_email, password_hash, display_name, login_email_verified_at, "
                    "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                    "VALUES (:id, 'credit-order@example.com', 'hash', '流水测试', now(), "
                    "'test', 'test', now())"
                ),
                {"id": user_id},
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as earlier_session:
            await earlier_session.execute(text("SELECT now()"))
            async with factory.begin() as later_session:
                repository = SqlAlchemyCreditRepository(later_session)
                first, _ = await repository.append(
                    user_id=user_id,
                    event_type=CreditEventType.MODERATION_ADJUSTMENT,
                    source_type="test",
                    reference_id=uuid4(),
                    delta=2,
                    reason="第一次调整",
                )
                assert first.sequence_no == 1
            repository = SqlAlchemyCreditRepository(earlier_session)
            second, _ = await repository.append(
                user_id=user_id,
                event_type=CreditEventType.MODERATION_ADJUSTMENT,
                source_type="test",
                reference_id=uuid4(),
                delta=-1,
                reason="第二次调整",
            )
            assert second.sequence_no == 2
            await earlier_session.commit()
        async with factory.begin() as session:
            repository = SqlAlchemyCreditRepository(session)
            assert await repository.summary(user_id) == 101
            assert await repository.recompute(user_id) == (101, True)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
