import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base


def test_identity_constraints_on_postgres() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")

    require_project_database(database_url)
    asyncio.run(_exercise_identity_constraints(database_url_for_sqlalchemy(database_url)))


async def _exercise_identity_constraints(database_url: str) -> None:
    schema = f"test_identity_{uuid4().hex}"
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

        async with engine.begin() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'TEST', '测试学校')"),
                {"id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school_id, 'MAIN', '测试校区')"
                ),
                {"id": campus_id, "school_id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, login_email, password_hash, display_name, login_email_verified_at, "
                    "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                    "VALUES (:id, :email, 'hash', '测试用户', now(), 'test', 'test', now())"
                ),
                {"id": first_user_id, "email": "login@example.com"},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, login_email, password_hash, display_name, login_email_verified_at, "
                    "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                    "VALUES (:id, :email, 'hash', '另一用户', now(), 'test', 'test', now())"
                ),
                {"id": second_user_id, "email": "other@example.com"},
            )

            await connection.execute(
                text("UPDATE users SET deleted_at = now() WHERE id = :id"),
                {"id": first_user_id},
            )
            replacement_user_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, login_email, password_hash, display_name, login_email_verified_at, "
                    "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                    "VALUES (:id, 'login@example.com', 'hash', '替代用户', "
                    "now(), 'test', 'test', now())"
                ),
                {"id": replacement_user_id},
            )

            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO users "
                            "(id, login_email, password_hash, display_name, "
                            "login_email_verified_at, user_agreement_version, "
                            "privacy_policy_version, terms_agreed_at) "
                            "VALUES (:id, 'Upper@Example.com', 'hash', '非法用户', "
                            "now(), 'test', 'test', now())"
                        ),
                        {"id": uuid4()},
                    )

            await connection.execute(
                text(
                    "INSERT INTO campus_verifications "
                    "(id, user_id, campus_id, campus_email, status) "
                    "VALUES (:id, :user_id, :campus_id, 'student@campus.edu', 'verified')"
                ),
                {"id": uuid4(), "user_id": replacement_user_id, "campus_id": campus_id},
            )
            with pytest.raises(IntegrityError):
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            "INSERT INTO campus_verifications "
                            "(id, user_id, campus_id, campus_email, status) "
                            "VALUES (:id, :user_id, :campus_id, "
                            "'student@campus.edu', 'pending')"
                        ),
                        {
                            "id": uuid4(),
                            "user_id": second_user_id,
                            "campus_id": campus_id,
                        },
                    )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
