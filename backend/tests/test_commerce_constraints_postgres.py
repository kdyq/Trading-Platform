import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.db.seed import DEFAULT_CATEGORIES, seed_categories
from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base


def test_commerce_constraints_and_seed_on_postgres() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")

    require_project_database(database_url)
    asyncio.run(_exercise_commerce_constraints(database_url_for_sqlalchemy(database_url)))


async def _expect_integrity_error(
    connection: AsyncConnection, statement: str, parameters: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        async with connection.begin_nested():
            await connection.execute(text(statement), parameters)


async def _exercise_commerce_constraints(database_url: str) -> None:
    schema = f"test_commerce_{uuid4().hex}"
    engine = create_async_engine(
        database_url, connect_args={"server_settings": {"timezone": "UTC"}}
    )
    school_id = uuid4()
    campus_id = uuid4()
    buyer_id = uuid4()
    seller_id = uuid4()
    product_id = uuid4()
    conversation_id = uuid4()
    order_id = uuid4()

    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
            await seed_categories(connection)
            await seed_categories(connection)
            category_count = await connection.scalar(text("SELECT count(*) FROM categories"))
            assert category_count == len(DEFAULT_CATEGORIES)
            category_id = await connection.scalar(
                text("SELECT id FROM categories WHERE code = 'digital'")
            )
            assert category_id is not None

        async with engine.begin() as connection:
            await connection.execute(text(f'SET search_path TO "{schema}"'))
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'TEST', '测试学校')"),
                {"id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'MAIN', '测试校区')"
                ),
                {"id": campus_id, "school": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, login_email, password_hash, display_name, login_email_verified_at, "
                    "user_agreement_version, privacy_policy_version, terms_agreed_at) VALUES "
                    "(:buyer, 'buyer@example.com', 'hash', '测试买家', now(), "
                    "'test', 'test', now()), "
                    "(:seller, 'seller@example.com', 'hash', '测试卖家', now(), "
                    "'test', 'test', now())"
                ),
                {"buyer": buyer_id, "seller": seller_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, seller_id, campus_id, category_id, title, description, price, status) "
                    "VALUES (:id, :seller, :campus, :category, '测试商品', '仅用于约束测试', "
                    "12.34, 'on_sale')"
                ),
                {
                    "id": product_id,
                    "seller": seller_id,
                    "campus": campus_id,
                    "category": category_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO conversations (id, product_id, buyer_id, seller_id) "
                    "VALUES (:id, :product, :buyer, :seller)"
                ),
                {
                    "id": conversation_id,
                    "product": product_id,
                    "buyer": buyer_id,
                    "seller": seller_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO orders "
                    "(id, product_id, buyer_id, seller_id, idempotency_key, amount, status) "
                    "VALUES (:id, :product, :buyer, :seller, 'order-1', 12.34, 'completed')"
                ),
                {
                    "id": order_id,
                    "product": product_id,
                    "buyer": buyer_id,
                    "seller": seller_id,
                },
            )

            await _expect_integrity_error(
                connection,
                "INSERT INTO products "
                "(id, seller_id, campus_id, category_id, title, description, price) "
                "VALUES (:id, :seller, :campus, :category, '非法价格', '测试', -0.01)",
                {
                    "id": uuid4(),
                    "seller": seller_id,
                    "campus": campus_id,
                    "category": category_id,
                },
            )

            first_image_id = uuid4()
            await connection.execute(
                text(
                    "INSERT INTO product_images "
                    "(id, product_id, object_key, thumbnail_object_key, display_order) "
                    "VALUES (:id, :product, 'test/first.jpg', 'test/first.webp', 0)"
                ),
                {"id": first_image_id, "product": product_id},
            )
            await _expect_integrity_error(
                connection,
                "INSERT INTO product_images "
                "(id, product_id, object_key, thumbnail_object_key, display_order) "
                "VALUES (:id, :product, 'test/duplicate.jpg', 'test/duplicate.webp', 0)",
                {"id": uuid4(), "product": product_id},
            )
            await connection.execute(
                text("UPDATE product_images SET deleted_at = now() WHERE id = :id"),
                {"id": first_image_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO product_images "
                    "(id, product_id, object_key, thumbnail_object_key, display_order) "
                    "VALUES (:id, :product, 'test/replacement.jpg', 'test/replacement.webp', 0)"
                ),
                {"id": uuid4(), "product": product_id},
            )

            await connection.execute(
                text(
                    "INSERT INTO favorites (id, user_id, product_id) VALUES (:id, :user, :product)"
                ),
                {"id": uuid4(), "user": buyer_id, "product": product_id},
            )
            await _expect_integrity_error(
                connection,
                "INSERT INTO favorites (id, user_id, product_id) VALUES (:id, :user, :product)",
                {"id": uuid4(), "user": buyer_id, "product": product_id},
            )

            await connection.execute(
                text(
                    "INSERT INTO messages "
                    "(id, conversation_id, sender_id, client_message_id, body) "
                    "VALUES (:id, :conversation, :sender, 'client-1', '测试消息')"
                ),
                {"id": uuid4(), "conversation": conversation_id, "sender": buyer_id},
            )
            await _expect_integrity_error(
                connection,
                "INSERT INTO messages "
                "(id, conversation_id, sender_id, client_message_id, body) "
                "VALUES (:id, :conversation, :sender, 'client-1', '重复消息')",
                {"id": uuid4(), "conversation": conversation_id, "sender": buyer_id},
            )

            await connection.execute(
                text(
                    "INSERT INTO reviews "
                    "(id, order_id, reviewer_id, reviewee_id, rating) "
                    "VALUES (:id, :order, :reviewer, :reviewee, 5)"
                ),
                {
                    "id": uuid4(),
                    "order": order_id,
                    "reviewer": buyer_id,
                    "reviewee": seller_id,
                },
            )
            await _expect_integrity_error(
                connection,
                "INSERT INTO reviews "
                "(id, order_id, reviewer_id, reviewee_id, rating) "
                "VALUES (:id, :order, :reviewer, :reviewee, 4)",
                {
                    "id": uuid4(),
                    "order": order_id,
                    "reviewer": buyer_id,
                    "reviewee": seller_id,
                },
            )

            await connection.execute(
                text(
                    "INSERT INTO reports "
                    "(id, reporter_id, target_type, target_id, reason_code) "
                    "VALUES (:id, :reporter, 'product', :target, 'prohibited')"
                ),
                {"id": uuid4(), "reporter": buyer_id, "target": product_id},
            )
            await _expect_integrity_error(
                connection,
                "INSERT INTO reports "
                "(id, reporter_id, target_type, target_id, reason_code) "
                "VALUES (:id, :reporter, 'product', :target, 'prohibited')",
                {"id": uuid4(), "reporter": buyer_id, "target": product_id},
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
