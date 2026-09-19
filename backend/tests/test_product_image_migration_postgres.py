import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from app.db.url import require_project_database

BACKEND_ROOT = Path(__file__).parents[1]


def test_product_image_replacement_survives_migration_round_trip() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")

    require_project_database(database_url)
    asyncio.run(_exercise_migration(database_url))


def _run_alembic(database_url: str, schema: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["DATABASE_SCHEMA"] = schema
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
    )


async def _exercise_migration(database_url: str) -> None:
    schema = f"test_gate_{uuid4().hex}"
    connection_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(connection_url)
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        _run_alembic(database_url, schema, "upgrade", "head")
        await connection.execute(f'SET search_path TO "{schema}"')

        school_id = uuid4()
        campus_id = uuid4()
        seller_id = uuid4()
        category_id = uuid4()
        product_id = uuid4()
        await connection.execute(
            "INSERT INTO schools (id, code, name) VALUES ($1, 'TEST', '测试学校')",
            school_id,
        )
        await connection.execute(
            "INSERT INTO campuses (id, school_id, code, name) VALUES ($1, $2, 'MAIN', '测试校区')",
            campus_id,
            school_id,
        )
        await connection.execute(
            "INSERT INTO users "
            "(id, login_email, password_hash, display_name, login_email_verified_at, "
            "user_agreement_version, privacy_policy_version, terms_agreed_at) "
            "VALUES ($1, 'seller@example.com', 'hash', '测试卖家', now(), 'test', 'test', now())",
            seller_id,
        )
        await connection.execute(
            "UPDATE users SET deleted_at = now() WHERE id = $1",
            seller_id,
        )
        replacement_seller_id = uuid4()
        await connection.execute(
            "INSERT INTO users "
            "(id, login_email, password_hash, display_name, login_email_verified_at, "
            "user_agreement_version, privacy_policy_version, terms_agreed_at) "
            "VALUES ($1, 'seller@example.com', 'hash', '替代卖家', "
            "now(), 'test', 'test', now())",
            replacement_seller_id,
        )
        await connection.execute(
            "INSERT INTO categories (id, code, slug, name) VALUES ($1, 'test', 'test', '测试分类')",
            category_id,
        )
        await connection.execute(
            "INSERT INTO products "
            "(id, seller_id, campus_id, category_id, title, description, price) "
            "VALUES ($1, $2, $3, $4, '测试商品', '迁移测试', 1.00)",
            product_id,
            replacement_seller_id,
            campus_id,
            category_id,
        )
        await connection.execute(
            "INSERT INTO product_images "
            "(id, product_id, object_key, display_order, deleted_at) VALUES "
            "($1, $3, 'test/deleted.jpg', 0, now()), "
            "($2, $3, 'test/active.jpg', 0, NULL)",
            uuid4(),
            uuid4(),
            product_id,
        )

        _run_alembic(database_url, schema, "downgrade", "f0342e63c26a")
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM users WHERE login_email = 'seller@example.com'"
            )
            == 2
        )
        rows = await connection.fetch(
            "SELECT object_key, display_order FROM product_images ORDER BY object_key"
        )
        assert len(rows) == 2
        assert len({row["display_order"] for row in rows}) == 2

        _run_alembic(database_url, schema, "upgrade", "head")
        assert await connection.fetchval("SELECT count(*) FROM product_images") == 2
    finally:
        await connection.execute("RESET search_path")
        await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await connection.close()
