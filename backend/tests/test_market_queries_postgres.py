import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.db.seed import seed_categories
from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.repositories.market import (
    PublicProductCursor,
    PublicProductFilters,
    SqlAlchemyMarketRepository,
)


def test_public_market_queries_keep_status_and_seller_trust_boundaries() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_market_queries(database_url_for_sqlalchemy(database_url)))


async def _exercise_market_queries(database_url: str) -> None:
    schema = f"test_market_{uuid4().hex}"
    admin_engine = create_async_engine(
        database_url, connect_args={"server_settings": {"timezone": "UTC"}}
    )
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    seller_id = uuid4()
    other_seller_id = uuid4()
    buyer_id = uuid4()
    product_id = uuid4()
    similar_id = uuid4()
    hidden_id = uuid4()
    school_id = uuid4()
    campus_id = uuid4()
    order_id = uuid4()
    cancelled_order_id = uuid4()
    unrelated_order_id = uuid4()
    first_image_id = uuid4()
    second_image_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await seed_categories(connection)
            category_id = await connection.scalar(
                text("SELECT id FROM categories WHERE code = 'books'")
            )
            assert category_id is not None
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
                    "(:seller, 'seller@example.com', 'hash', '认证卖家', now(), "
                    "'test', 'test', now()), "
                    "(:other, 'other@example.com', 'hash', '普通卖家', now(), "
                    "'test', 'test', now()), "
                    "(:buyer, 'buyer@example.com', 'hash', '买家', now(), 'test', 'test', now())"
                ),
                {"seller": seller_id, "other": other_seller_id, "buyer": buyer_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campus_verifications "
                    "(id, user_id, campus_id, campus_email, status, verified_at, expires_at) "
                    "VALUES (:id, :seller, :campus, 'seller@campus.edu', "
                    "'verified', now(), :expires)"
                ),
                {
                    "id": uuid4(),
                    "seller": seller_id,
                    "campus": campus_id,
                    "expires": datetime.now(UTC) + timedelta(days=30),
                },
            )
            product_statement = text(
                "INSERT INTO products "
                "(id, seller_id, campus_id, category_id, title, description, price, status, "
                "published_at) VALUES "
                "(:id, :seller, :campus, :category, :title, :description, 18.50, :status, now())"
            )
            for item_id, seller, title, status in (
                (product_id, seller_id, "公开教材", "on_sale"),
                (similar_id, other_seller_id, "相似教材", "reserved"),
                (hidden_id, seller_id, "隐藏教材", "hidden"),
            ):
                await connection.execute(
                    product_statement,
                    {
                        "id": item_id,
                        "seller": seller,
                        "campus": campus_id,
                        "category": category_id,
                        "title": title,
                        "description": "仅用于查询测试",
                        "status": status,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO product_images "
                    "(id, product_id, object_key, thumbnail_object_key, alt_text, display_order) "
                    "VALUES "
                    "(:first, :product, 'products/first.jpg', 'products/first.webp', '第一张', 0), "
                    "(:second, :product, 'products/second.png', "
                    "'products/second.webp', '第二张', 1)"
                ),
                {"first": first_image_id, "second": second_image_id, "product": product_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO orders "
                    "(id, product_id, buyer_id, seller_id, idempotency_key, amount, status, "
                    "product_title_snapshot, campus_name_snapshot, buyer_display_name_snapshot, "
                    "seller_display_name_snapshot, completed_at) VALUES "
                    "(:id, :product, :buyer, :seller, 'market-test', 18.50, 'completed', "
                    "'查询商品', '主校区', '买家', '卖家', now())"
                ),
                {
                    "id": order_id,
                    "product": product_id,
                    "buyer": buyer_id,
                    "seller": seller_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO orders "
                    "(id, product_id, buyer_id, seller_id, idempotency_key, amount, status, "
                    "product_title_snapshot, campus_name_snapshot, buyer_display_name_snapshot, "
                    "seller_display_name_snapshot, completed_at) "
                    "VALUES (:id, :product, :buyer, :seller, "
                    "'market-unrelated', 18.50, 'completed', "
                    "'无关商品', '主校区', '买家', '其他卖家', now())"
                ),
                {
                    "id": unrelated_order_id,
                    "product": similar_id,
                    "buyer": buyer_id,
                    "seller": other_seller_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO reviews (id, order_id, reviewer_id, reviewee_id, rating) "
                    "VALUES (:id, :order, :buyer, :wrong_seller, 1)"
                ),
                {
                    "id": uuid4(),
                    "order": unrelated_order_id,
                    "buyer": buyer_id,
                    "wrong_seller": seller_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO reviews (id, order_id, reviewer_id, reviewee_id, rating) "
                    "VALUES (:id, :order, :buyer, :seller, 5)"
                ),
                {"id": uuid4(), "order": order_id, "buyer": buyer_id, "seller": seller_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO orders "
                    "(id, product_id, buyer_id, seller_id, idempotency_key, amount, status, "
                    "product_title_snapshot, campus_name_snapshot, buyer_display_name_snapshot, "
                    "seller_display_name_snapshot) "
                    "VALUES (:id, :product, :buyer, :seller, "
                    "'market-cancelled', 18.50, 'cancelled', "
                    "'取消商品', '主校区', '买家', '卖家')"
                ),
                {
                    "id": cancelled_order_id,
                    "product": product_id,
                    "buyer": buyer_id,
                    "seller": seller_id,
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO reviews (id, order_id, reviewer_id, reviewee_id, rating) "
                    "VALUES (:id, :order, :buyer, :seller, 1)"
                ),
                {
                    "id": uuid4(),
                    "order": cancelled_order_id,
                    "buyer": buyer_id,
                    "seller": seller_id,
                },
            )

        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            repository = SqlAlchemyMarketRepository(session)
            detail = await repository.get_product(product_id)
            assert detail is not None
            assert detail.seller_verified is True
            assert detail.seller_review_count == 1
            assert detail.seller_average_rating == 5
            assert detail.seller_completed_orders == 1
            images = await repository.list_product_images(product_id)
            assert [image.id for image in images] == [first_image_id, second_image_id]
            assert await repository.get_product_image(first_image_id) == images[0]
            assert await repository.get_product(hidden_id) is None

            items, total = await repository.search_products(
                filters=PublicProductFilters(), cursor=None, limit=12
            )
            assert total == 2
            assert all(item.favorite_count == 0 for item in items)
            verification_by_id = {item.id: item.seller_verified for item in items}
            assert verification_by_id == {product_id: True, similar_id: False}

            first_page, _ = await repository.search_products(
                filters=PublicProductFilters(sort="price_asc"), cursor=None, limit=1
            )
            inserted_id = uuid4()
            await session.execute(
                product_statement,
                {
                    "id": inserted_id,
                    "seller": seller_id,
                    "campus": campus_id,
                    "category": category_id,
                    "title": "翻页间新增商品",
                    "description": "用于验证游标分页稳定性",
                    "status": "on_sale",
                },
            )
            await session.execute(
                text("UPDATE products SET price = 1 WHERE id = :id"), {"id": inserted_id}
            )
            second_page, _ = await repository.search_products(
                filters=PublicProductFilters(sort="price_asc"),
                cursor=PublicProductCursor(
                    product_id=first_page[0].id,
                    price=first_page[0].price,
                ),
                limit=1,
            )
            assert second_page[0].id in {product_id, similar_id} - {first_page[0].id}

            null_published_id = uuid4()
            await session.execute(
                product_statement,
                {
                    "id": null_published_id,
                    "seller": seller_id,
                    "campus": campus_id,
                    "category": category_id,
                    "title": "空发布时间商品",
                    "description": "用于验证空值游标分区",
                    "status": "on_sale",
                },
            )
            await session.execute(
                text("UPDATE products SET published_at = NULL WHERE id IN (:first, :second)"),
                {"first": similar_id, "second": null_published_id},
            )
            newest_page, _ = await repository.search_products(
                filters=PublicProductFilters(sort="newest"), cursor=None, limit=2
            )
            assert all(item.published_at is not None for item in newest_page)
            first_null_page, _ = await repository.search_products(
                filters=PublicProductFilters(sort="newest"),
                cursor=PublicProductCursor(
                    product_id=newest_page[-1].id,
                    published_at=newest_page[-1].published_at,
                    created_at=newest_page[-1].created_at,
                ),
                limit=1,
            )
            assert first_null_page[0].published_at is None
            second_null_page, _ = await repository.search_products(
                filters=PublicProductFilters(sort="newest"),
                cursor=PublicProductCursor(
                    product_id=first_null_page[0].id,
                    published_at=None,
                    created_at=first_null_page[0].created_at,
                ),
                limit=1,
            )
            assert second_null_page[0].published_at is None
            assert second_null_page[0].id != first_null_page[0].id

            similar = await repository.list_similar_products(
                product_id=product_id, category_id=detail.category_id, limit=4
            )
            assert {item.id for item in similar} == {
                inserted_id,
                null_published_id,
                similar_id,
            }

            assert await repository.add_favorite(buyer_id, product_id) is True
            assert await repository.add_favorite(buyer_id, product_id) is True
            assert await repository.favorite_status(buyer_id, product_id) == (True, 1)
            favorites = await repository.list_favorites(buyer_id)
            assert [item.id for item in favorites] == [product_id]
            assert favorites[0].image_url == (
                f"/api/v1/market/product-image-thumbnails/{first_image_id}"
            )
            assert favorites[0].image_alt == "第一张"
            await session.execute(
                text("UPDATE product_images SET deleted_at = now() WHERE id = :id"),
                {"id": first_image_id},
            )
            favorites = await repository.list_favorites(buyer_id)
            assert favorites[0].image_url == (
                f"/api/v1/market/product-image-thumbnails/{second_image_id}"
            )
            assert favorites[0].image_alt == "第二张"
            await session.execute(
                text("UPDATE product_images SET deleted_at = now() WHERE id = :id"),
                {"id": second_image_id},
            )
            favorites = await repository.list_favorites(buyer_id)
            assert favorites[0].image_url is None and favorites[0].image_alt is None
            await repository.remove_favorite(buyer_id, product_id)
            assert await repository.favorite_status(buyer_id, product_id) == (False, 0)

            await session.execute(
                text("UPDATE campuses SET is_active = false WHERE id = :id"),
                {"id": campus_id},
            )
            assert await repository.get_product(product_id) is None
            hidden_items, hidden_total = await repository.search_products(
                filters=PublicProductFilters(), cursor=None, limit=12
            )
            assert hidden_items == [] and hidden_total == 0
            assert await repository.add_favorite(buyer_id, product_id) is False
            with pytest.raises(AppError) as hidden_status:
                await repository.favorite_status(buyer_id, product_id)
            assert getattr(hidden_status.value, "code", None) == "product_not_found"
            await session.execute(
                text("UPDATE campuses SET is_active = true WHERE id = :id"),
                {"id": campus_id},
            )

            plan = await session.execute(
                text(
                    "EXPLAIN SELECT id FROM products "
                    "WHERE deleted_at IS NULL AND status IN ('on_sale', 'reserved', 'sold') "
                    "AND category_id = :category ORDER BY price, id LIMIT 12"
                ),
                {"category": detail.category_id},
            )
            assert "Limit" in "\n".join(str(row[0]) for row in plan)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
