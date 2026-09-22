import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.models.catalog import Product, ProductStatus
from app.models.identity import CampusVerificationStatus
from app.models.trade import Order, OrderEvent, OrderStatus, Review
from app.repositories.market import SqlAlchemyMarketRepository
from app.repositories.orders import SqlAlchemyOrderRepository
from app.schemas.orders import OrderCancel, OrderCreate, OrderResponse, ReviewCreate
from app.services.orders import OrderService
from app.workers.order_expiration import OrderExpirationCoordinator


def test_only_one_concurrent_order_can_reserve_a_product() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_concurrent_accept(database_url_for_sqlalchemy(database_url)))


async def _exercise_concurrent_accept(database_url: str) -> None:
    schema = f"test_orders_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    school_id, campus_id, category_id, product_id = uuid4(), uuid4(), uuid4(), uuid4()
    seller_id, first_buyer_id, second_buyer_id = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'ORD', '订单测试学校')"),
                {"id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school_id, 'MAIN', '订单测试校区')"
                ),
                {"id": campus_id, "school_id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO categories (id, code, slug, name) "
                    "VALUES (:id, 'order-test', 'order-test', '订单测试')"
                ),
                {"id": category_id},
            )
            for user_id, email, display_name in (
                (seller_id, "order-seller@example.com", "测试卖家"),
                (first_buyer_id, "order-buyer-1@example.com", "买家甲"),
                (second_buyer_id, "order-buyer-2@example.com", "买家乙"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, login_email_verified_at, "
                        "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'hash', :display_name, now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email, "display_name": display_name},
                )
            for buyer_id, campus_email in (
                (first_buyer_id, "order-buyer-1@campus.example"),
                (second_buyer_id, "order-buyer-2@campus.example"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO campus_verifications "
                        "(id, user_id, campus_id, campus_email, status, verified_at) "
                        "VALUES (:id, :user_id, :campus_id, :campus_email, 'verified', now())"
                    ),
                    {
                        "id": uuid4(),
                        "user_id": buyer_id,
                        "campus_id": campus_id,
                        "campus_email": campus_email,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, seller_id, campus_id, category_id, title, description, price, status, "
                    "published_at) VALUES "
                    "(:id, :seller_id, :campus_id, :category_id, '并发预留商品', "
                    "'验证两个买家并发接受时只有一个成功', 66.00, 'on_sale', now())"
                ),
                {
                    "id": product_id,
                    "seller_id": seller_id,
                    "campus_id": campus_id,
                    "category_id": category_id,
                },
            )

        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def create_order(buyer_id: UUID, key: str) -> OrderResponse:
            async with factory.begin() as session:
                return await OrderService(SqlAlchemyOrderRepository(session)).create(
                    user_id=buyer_id,
                    campus_status=CampusVerificationStatus.VERIFIED,
                    payload=OrderCreate(product_id=product_id, idempotency_key=key),
                )

        first = await create_order(first_buyer_id, "concurrent_create_1")
        repeated = await create_order(first_buyer_id, "concurrent_create_1")
        second = await create_order(second_buyer_id, "concurrent_create_2")
        assert repeated.id == first.id
        assert first.amount == second.amount
        assert first.product_title == "并发预留商品"

        async def accept(order_id: UUID, action_id: str) -> str:
            try:
                async with factory.begin() as session:
                    result = await OrderService(SqlAlchemyOrderRepository(session)).accept(
                        user_id=seller_id,
                        campus_status=CampusVerificationStatus.VERIFIED,
                        order_id=order_id,
                        client_action_id=action_id,
                    )
                return result.status
            except AppError as error:
                return error.code

        outcomes = await asyncio.wait_for(
            asyncio.gather(
                accept(first.id, "concurrent_accept_1"),
                accept(second.id, "concurrent_accept_2"),
            ),
            timeout=10,
        )
        assert outcomes.count(OrderStatus.ACCEPTED.value) == 1
        assert outcomes.count("invalid_order_state") == 1

        async with factory() as session:
            product = await session.get(Product, product_id)
            orders = list(
                await session.scalars(select(Order).where(Order.product_id == product_id))
            )
            assert product is not None and product.status == ProductStatus.RESERVED
            assert sorted(order.status.value for order in orders) == ["accepted", "cancelled"]
            accepted_order = next(order for order in orders if order.status == OrderStatus.ACCEPTED)

        async with factory.begin() as session:
            cancelled = await OrderService(SqlAlchemyOrderRepository(session)).cancel(
                user_id=seller_id,
                campus_status=CampusVerificationStatus.VERIFIED,
                order_id=accepted_order.id,
                payload=OrderCancel(
                    client_action_id="postgres_cancel_1",
                    reason_code="schedule_failed",
                    note="并发测试完成后恢复商品",
                ),
            )
            assert cancelled.status == OrderStatus.CANCELLED.value

        expiring = await create_order(first_buyer_id, "postgres_expiring_1")
        async with factory.begin() as session:
            await session.execute(
                update(Order)
                .where(Order.id == expiring.id)
                .values(expires_at=func.now() - text("interval '1 second'"))
            )
        first_worker = OrderExpirationCoordinator(factory)
        second_worker = OrderExpirationCoordinator(factory)
        expired_counts = await asyncio.gather(first_worker.expire_due(), second_worker.expire_due())
        assert sum(expired_counts) == 1
        assert await first_worker.expire_due() == 0
        async with factory() as session:
            expired = await session.get(Order, expiring.id)
            expiration_events = await session.scalar(
                select(func.count(OrderEvent.id)).where(
                    OrderEvent.order_id == expiring.id,
                    OrderEvent.to_status == OrderStatus.EXPIRED,
                )
            )
            product = await session.get(Product, product_id)
            assert expired is not None and expired.status == OrderStatus.EXPIRED
            assert expiration_events == 1
            assert product is not None and product.status == ProductStatus.ON_SALE

        completed_candidate = await create_order(second_buyer_id, "postgres_complete_1")
        async with factory.begin() as session:
            await OrderService(SqlAlchemyOrderRepository(session)).accept(
                user_id=seller_id,
                campus_status=CampusVerificationStatus.VERIFIED,
                order_id=completed_candidate.id,
                client_action_id="postgres_complete_accept_1",
            )
        async with factory.begin() as session:
            delivered = await OrderService(SqlAlchemyOrderRepository(session)).mark_delivered(
                user_id=seller_id,
                campus_status=CampusVerificationStatus.VERIFIED,
                order_id=completed_candidate.id,
                client_action_id="postgres_deliver_1",
            )
            assert delivered.status == OrderStatus.SELLER_DELIVERED.value
        async with factory.begin() as session:
            completed = await OrderService(SqlAlchemyOrderRepository(session)).complete(
                user_id=second_buyer_id,
                campus_status=CampusVerificationStatus.VERIFIED,
                order_id=completed_candidate.id,
                client_action_id="postgres_complete_1",
            )
            assert completed.status == OrderStatus.COMPLETED.value
        async with factory() as session:
            final_order = await session.get(Order, completed_candidate.id)
            final_product = await session.get(Product, product_id)
            assert final_order is not None and final_order.status == OrderStatus.COMPLETED
            assert final_order.completed_at is not None
            assert final_product is not None and final_product.status == ProductStatus.SOLD
            assert final_product.sold_at is not None

        async with factory.begin() as session:
            order_service = OrderService(SqlAlchemyOrderRepository(session))
            buying = await order_service.list_orders(
                user_id=second_buyer_id,
                role="buying",
                status=OrderStatus.COMPLETED,
                cursor=None,
                limit=1,
            )
            assert [item.id for item in buying.items] == [completed_candidate.id]
            assert buying.items[0].image_url is None
            buyer_review = await order_service.create_review(
                user_id=second_buyer_id,
                campus_status=CampusVerificationStatus.VERIFIED,
                order_id=completed_candidate.id,
                payload=ReviewCreate(
                    rating=5,
                    tags=["item_as_described"],
                    content="商品与描述一致",
                ),
            )
            await order_service.create_review(
                user_id=seller_id,
                campus_status=CampusVerificationStatus.VERIFIED,
                order_id=completed_candidate.id,
                payload=ReviewCreate(rating=4, tags=["good_communication"]),
            )
            detail = await order_service.detail(
                user_id=second_buyer_id, order_id=completed_candidate.id
            )
            assert not detail.can_review
            assert len(detail.reviews) == 2
            assert all(not hasattr(item, "location_text") for item in buying.items)

        async with factory() as session:
            public_product = await SqlAlchemyMarketRepository(session).get_product(product_id)
            assert public_product is not None
            assert public_product.seller_review_count == 1
            assert public_product.seller_average_rating == 5
        async with factory.begin() as session:
            await session.execute(
                update(Review)
                .where(Review.id == buyer_review.id)
                .values(is_visible=False, hidden_at=func.now())
            )
        async with factory() as session:
            moderated_product = await SqlAlchemyMarketRepository(session).get_product(product_id)
            assert moderated_product is not None
            assert moderated_product.seller_review_count == 0
            assert moderated_product.seller_average_rating is None
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
