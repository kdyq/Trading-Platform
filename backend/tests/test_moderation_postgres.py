import asyncio
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import AppError
from app.db.url import database_url_for_sqlalchemy, require_project_database
from app.models import Base
from app.models.catalog import Product, ProductStatus
from app.models.moderation import AuditLog, ModerationRecord
from app.repositories.moderation import SqlAlchemyModerationRepository
from app.services.moderation import ModerationService


def test_product_moderation_is_role_guarded_and_concurrency_safe() -> None:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    require_project_database(database_url)
    asyncio.run(_exercise_moderation(database_url_for_sqlalchemy(database_url)))


async def _exercise_moderation(database_url: str) -> None:
    schema = f"test_moderation_{uuid4().hex}"
    admin_engine = create_async_engine(database_url)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(
        database_url,
        connect_args={"server_settings": {"timezone": "UTC", "search_path": schema}},
    )
    seller_id, first_reviewer, second_reviewer, ordinary_user = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    school_id, campus_id, category_id, product_id, role_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, 'MOD', '审核测试学校')"),
                {"id": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'MAIN', '主校区')"
                ),
                {"id": campus_id, "school": school_id},
            )
            await connection.execute(
                text(
                    "INSERT INTO categories (id, code, slug, name) "
                    "VALUES (:id, 'moderation', 'moderation', '审核测试')"
                ),
                {"id": category_id},
            )
            for user_id, email in (
                (seller_id, "mod-seller@example.com"),
                (first_reviewer, "mod-reviewer-1@example.com"),
                (second_reviewer, "mod-reviewer-2@example.com"),
                (ordinary_user, "mod-user@example.com"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, login_email_verified_at, "
                        "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'hash', '审核测试用户', now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email},
                )
            await connection.execute(
                text("INSERT INTO roles (id, code, name) VALUES (:id, 'REVIEWER', '审核员')"),
                {"id": role_id},
            )
            for reviewer_id in (first_reviewer, second_reviewer):
                await connection.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                    {"user_id": reviewer_id, "role_id": role_id},
                )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, seller_id, campus_id, category_id, title, description, price, status) "
                    "VALUES (:id, :seller, :campus, :category, '待审核商品', "
                    "'用于验证并发审核不会覆盖', 29.90, 'pending_review')"
                ),
                {
                    "id": product_id,
                    "seller": seller_id,
                    "campus": campus_id,
                    "category": category_id,
                },
            )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as session:
            service = ModerationService(SqlAlchemyModerationRepository(session))
            with pytest.raises(AppError) as denied:
                await service.list_products(
                    moderator_id=ordinary_user, status=ProductStatus.PENDING_REVIEW
                )
            assert denied.value.code == "moderation_forbidden"

        async def decide(reviewer_id: UUID, action: str, request_id: str) -> str:
            try:
                async with factory.begin() as session:
                    service = ModerationService(SqlAlchemyModerationRepository(session))
                    result = await service.decide_product(
                        moderator_id=reviewer_id,
                        product_id=product_id,
                        action=action,
                        expected_version=1,
                        reason_code="content_review",
                        public_note=f"并发审核测试结论 {action}",
                        request_id=request_id,
                    )
                    return result.status
            except AppError as error:
                return error.code

        outcomes = await asyncio.gather(
            decide(first_reviewer, "approve", "moderation_concurrent_approve"),
            decide(second_reviewer, "reject", "moderation_concurrent_reject"),
        )
        assert outcomes.count("product_version_conflict") == 1
        assert len({value for value in outcomes if value != "product_version_conflict"}) == 1
        async with factory() as session:
            product = await session.get(Product, product_id)
            assert product is not None and product.version == 2
            assert product.status in {ProductStatus.ON_SALE, ProductStatus.REJECTED}
            assert await session.scalar(select(func.count(ModerationRecord.id))) == 1
            assert await session.scalar(select(func.count(AuditLog.id))) == 1
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin_engine.dispose()
