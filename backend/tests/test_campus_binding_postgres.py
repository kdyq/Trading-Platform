import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base


def test_concurrent_campus_email_binding_has_one_winner() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_concurrent_binding(database_url_for_sqlalchemy(database_url)))


async def _exercise_concurrent_binding(database_url: str) -> None:
    schema = f"test_campus_binding_{uuid4().hex}"
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"timezone": "UTC"}}
    )
    school_id = uuid4()
    campus_id = uuid4()
    first_user_id = uuid4()
    second_user_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'TEST', '测试学校')"),
                {"id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school_id, 'MAIN', '主校区')"
                ),
                {"id": campus_id, "school_id": school_id},
            )
            for user_id, email in (
                (first_user_id, "first@example.com"),
                (second_user_id, "second@example.com"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, "
                        "login_email_verified_at, user_agreement_version, "
                        "privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'hash', '测试用户', now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email},
                )

        first = await engine.connect()
        second = await engine.connect()
        first_transaction = await first.begin()
        second_transaction = await second.begin()
        try:
            await first.execute(text(f'SET search_path TO "{schema}"'))
            await second.execute(text(f'SET search_path TO "{schema}"'))
            statement = text(
                "INSERT INTO campus_verifications "
                "(id, user_id, campus_id, campus_email, status) "
                "VALUES (:id, :user_id, :campus_id, 'same@campus.edu', 'pending')"
            )
            await first.execute(
                statement,
                {"id": uuid4(), "user_id": first_user_id, "campus_id": campus_id},
            )
            contender = asyncio.create_task(
                second.execute(
                    statement,
                    {"id": uuid4(), "user_id": second_user_id, "campus_id": campus_id},
                )
            )
            await asyncio.sleep(0.05)
            assert not contender.done()
            await first_transaction.commit()
            with pytest.raises(IntegrityError):
                await contender
            await second_transaction.rollback()
        finally:
            await first.close()
            await second.close()

        async with engine.connect() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM campus_verifications "
                    "WHERE campus_email = 'same@campus.edu'"
                )
            )
            assert count == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
