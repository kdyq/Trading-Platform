import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import create_database_engine, create_session_factory, transaction_scope
from app.db.url import require_project_database


def test_transaction_scope_commits_and_rolls_back_on_postgres() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")

    require_project_database(database_url)
    asyncio.run(_exercise_transaction_scope(database_url))


async def _exercise_transaction_scope(database_url: str) -> None:
    schema = f"test_session_{uuid4().hex}"
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    rollback_events: list[str] = []
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            await connection.execute(
                text("CREATE TABLE transaction_probe (value integer NOT NULL)")
            )

        async with transaction_scope(session_factory) as session:
            session.info.setdefault("rollback_callbacks", []).append(
                lambda: rollback_events.append("committed")
            )
            await session.execute(text(f'SET search_path TO "{schema}"'))
            await session.execute(text("INSERT INTO transaction_probe VALUES (1)"))

        with pytest.raises(RuntimeError, match="rollback probe"):
            async with transaction_scope(session_factory) as session:
                session.info.setdefault("rollback_callbacks", []).append(
                    lambda: rollback_events.append("rolled-back")
                )
                await session.execute(text(f'SET search_path TO "{schema}"'))
                await session.execute(text("INSERT INTO transaction_probe VALUES (2)"))
                raise RuntimeError("rollback probe")

        assert rollback_events == ["rolled-back"]

        async with engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            values = (
                await connection.execute(text("SELECT value FROM transaction_probe"))
            ).scalars()
            assert list(values) == [1]
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
