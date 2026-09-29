import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text, update

from app.core.exceptions import AppError
from app.db.seed import seed_categories
from app.db.session import create_database_engine, create_session_factory, transaction_scope
from app.models.catalog import Product, ProductImage, ProductStatus
from app.models.identity import CampusAppealStatus, CampusVerificationAppeal, User, UserSession
from app.models.trade import Order, OrderStatus
from app.repositories.identity import SqlAlchemyIdentityRepository
from app.services.private_storage import PrivateAppealStorage
from app.services.product_storage import LocalObjectStorage
from app.services.retention import (
    cleanup_closed_account_images,
    cleanup_expired_campus_appeals,
    cleanup_inactive_session_metadata,
)


def test_closure_guards_and_private_material_cleanup(tmp_path: Path) -> None:
    database_url = os.getenv("DATABASE_URL")
    schema = os.getenv("DATABASE_SCHEMA")
    if not database_url or not schema:
        pytest.skip("PostgreSQL gate schema is required")
    asyncio.run(exercise(database_url, schema, tmp_path))


async def exercise(database_url: str, schema: str, root: Path) -> None:
    engine = create_database_engine(database_url, schema=schema)
    factory = create_session_factory(engine)
    user, seller, school, campus, category, product, order, appeal, image = (
        uuid4() for _ in range(9)
    )
    material_key = f"campus-appeals/{user}/{appeal}.pdf"
    pending_appeal = uuid4()
    old_session = uuid4()
    material_path = root / material_key
    material_path.parent.mkdir(parents=True)
    material_path.write_bytes(b"%PDF-test-private-material")
    image_root = root / "public"
    image_path = image_root / "products" / "privacy.jpg"
    thumbnail_path = image_root / "products" / "privacy.webp"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"original")
    thumbnail_path.write_bytes(b"thumbnail")
    try:
        async with engine.begin() as connection:
            await seed_categories(connection)
            await connection.execute(
                text("INSERT INTO schools (id, code, name) VALUES (:id, :code, '隐私测试学校')"),
                {"id": school, "code": f"P{school.hex[:8]}"},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'MAIN', '隐私测试校区')"
                ),
                {"id": campus, "school": school},
            )
            category = await connection.scalar(text("SELECT id FROM categories WHERE code='books'"))
            for user_id in (user, seller):
                await connection.execute(
                    text(
                        "INSERT INTO users (id, login_email, password_hash, display_name, "
                        "login_email_verified_at, user_agreement_version, privacy_policy_version, "
                        "terms_agreed_at) VALUES (:id, :email, 'hash', '测试用户', now(), "
                        "'test', 'test', now())"
                    ),
                    {"id": user_id, "email": f"{user_id}@example.invalid"},
                )
            await connection.execute(
                text(
                    "INSERT INTO campus_verifications (id, user_id, campus_id, campus_email, "
                    "status, verified_at, expires_at) VALUES (:id, :user, :campus, :email, "
                    "'verified', now(), :expires)"
                ),
                {
                    "id": uuid4(),
                    "user": user,
                    "campus": campus,
                    "email": f"{user}@campus.invalid",
                    "expires": datetime.now(UTC) + timedelta(days=30),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO products (id, seller_id, campus_id, category_id, title, "
                    "description, price, status) VALUES (:id, :seller, :campus, :category, "
                    "'待隐藏商品', '仅测试', 18.50, 'on_sale')"
                ),
                {"id": product, "seller": user, "campus": campus, "category": category},
            )
            await connection.execute(
                text(
                    "INSERT INTO orders (id, product_id, buyer_id, seller_id, idempotency_key, "
                    "amount, status, product_title_snapshot, campus_name_snapshot, "
                    "buyer_display_name_snapshot, seller_display_name_snapshot) "
                    "VALUES (:id, :product, :buyer, :seller, 'privacy-test', 18.50, "
                    "'pending_seller_confirmation', '测试商品', '测试校区', '买家', '卖家')"
                ),
                {"id": order, "product": product, "buyer": seller, "seller": user},
            )
            await connection.execute(
                text(
                    "INSERT INTO product_images (id, product_id, object_key, thumbnail_object_key, "
                    "display_order) VALUES (:id, :product, 'products/privacy.jpg', "
                    "'products/privacy.webp', 0)"
                ),
                {"id": image, "product": product},
            )
            await connection.execute(
                text(
                    "INSERT INTO user_sessions (id, user_id, family_id, refresh_token_digest, "
                    "expires_at, authenticated_at, ip_address, user_agent) "
                    "VALUES (:id, :user, :family, :digest, :expires, now(), :ip, :agent)"
                ),
                {
                    "id": uuid4(),
                    "user": user,
                    "family": uuid4(),
                    "digest": uuid4().hex,
                    "expires": datetime.now(UTC) + timedelta(days=1),
                    "ip": "127.0.0.1",
                    "agent": "test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO user_sessions (id, user_id, family_id, refresh_token_digest, "
                    "expires_at, authenticated_at, ip_address, user_agent) "
                    "VALUES (:id, :user, :family, :digest, :expires, now(), :ip, :agent)"
                ),
                {
                    "id": old_session,
                    "user": seller,
                    "family": uuid4(),
                    "digest": uuid4().hex,
                    "expires": datetime.now(UTC) - timedelta(days=31),
                    "ip": "127.0.0.2",
                    "agent": "old-test",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO campus_verification_appeals (id, user_id, campus_id, "
                    "status, reason, material_key, original_filename, media_type, size_bytes, "
                    "retention_until) VALUES (:id, :user, :campus, 'approved', 'private reason', "
                    ":key, 'private.pdf', 'application/pdf', 26, :retention)"
                ),
                {
                    "id": appeal,
                    "user": user,
                    "campus": campus,
                    "key": material_key,
                    "retention": datetime.now(UTC) + timedelta(days=30),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO campus_verification_appeals (id, user_id, campus_id, "
                    "status, reason, material_key, original_filename, media_type, size_bytes, "
                    "retention_until) VALUES (:id, :user, :campus, 'pending', 'private reason', "
                    ":key, 'private.pdf', 'application/pdf', 26, :retention)"
                ),
                {
                    "id": pending_appeal,
                    "user": seller,
                    "campus": campus,
                    "key": f"campus-appeals/{seller}/{pending_appeal}.pdf",
                    "retention": datetime.now(UTC) - timedelta(days=1),
                },
            )
        with pytest.raises(AppError) as guarded:
            async with transaction_scope(factory) as session:
                await SqlAlchemyIdentityRepository(session).close_account(
                    user, at=datetime.now(UTC)
                )
        assert guarded.value.code == "account_has_open_cases"
        async with transaction_scope(factory) as session:
            await session.execute(
                update(Order).where(Order.id == order).values(status=OrderStatus.CANCELLED)
            )
        async with transaction_scope(factory) as session:
            await SqlAlchemyIdentityRepository(session).close_account(user, at=datetime.now(UTC))
        async with transaction_scope(factory) as session:
            storage = PrivateAppealStorage(root, max_bytes=1024)
            assert await cleanup_expired_campus_appeals(session, storage) == 2
            assert await cleanup_closed_account_images(session, LocalObjectStorage(image_root)) == 1
            assert await cleanup_inactive_session_metadata(session) == 1
        async with factory() as session:
            closed = await session.get(User, user)
            assert closed is not None
            assert closed.login_email is None and closed.deleted_at is not None
            assert closed.display_name == "已注销用户"
            assert (
                await session.scalar(
                    select(UserSession.revoked_at).where(UserSession.user_id == user)
                )
            ) is not None
            assert (await session.get(Product, product)).status == ProductStatus.DELETED  # type: ignore[union-attr]
            stored_appeal = await session.get(CampusVerificationAppeal, appeal)
            assert stored_appeal is not None
            assert stored_appeal.material_key == f"removed/{appeal}"
            assert stored_appeal.reason == ""
            pending = await session.get(CampusVerificationAppeal, pending_appeal)
            assert pending is not None
            assert pending.status == CampusAppealStatus.PENDING
            assert pending.material_key == f"removed/{pending_appeal}"
            stale = await session.get(UserSession, old_session)
            assert stale is not None
            assert stale.ip_address is None and stale.user_agent is None
            assert not material_path.exists()
            stored_image = await session.get(ProductImage, image)
            assert stored_image is not None
            assert stored_image.object_key == f"removed/{image}/original"
            assert not image_path.exists() and not thumbnail_path.exists()
            stored_order = await session.get(Order, order)
            assert stored_order is not None
            assert stored_order.seller_display_name_snapshot == "已注销用户"
    finally:
        await engine.dispose()
