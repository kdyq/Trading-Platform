import asyncio
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_order_service, get_seller_product_service
from app.api.v1.routes.auth import get_auth_context
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.feature_switches import require_publishing, require_trading
from app.main import create_app
from app.models.catalog import Product, ProductStatus
from app.models.moderation import ModerationTargetType, Report
from app.repositories.moderation import SqlAlchemyModerationRepository


def test_publishing_and_trading_can_pause_without_changing_data() -> None:
    settings = Settings(
        database_url=None,
        redis_url=None,
        publishing_enabled=False,
        trading_enabled=False,
    )
    with pytest.raises(AppError) as publishing:
        require_publishing(settings)
    assert publishing.value.code == "publishing_paused"
    assert publishing.value.status_code == 503
    with pytest.raises(AppError) as trading:
        require_trading(settings)
    assert trading.value.code == "trading_paused"
    assert trading.value.status_code == 503


def test_default_switches_are_open() -> None:
    settings = Settings(database_url=None, redis_url=None)
    require_publishing(settings)
    require_trading(settings)


def test_paused_routes_reject_new_publications_and_orders_before_service_call() -> None:
    app = create_app(
        Settings(
            database_url=None,
            redis_url=None,
            publishing_enabled=False,
            trading_enabled=False,
        )
    )
    account = SimpleNamespace(
        user=SimpleNamespace(id=uuid4()), campus_verification_status="verified"
    )
    app.dependency_overrides[get_auth_context] = lambda: account
    app.dependency_overrides[get_seller_product_service] = lambda: SimpleNamespace()
    app.dependency_overrides[get_order_service] = lambda: SimpleNamespace()
    with TestClient(app) as client:
        submitted = client.post(f"/api/v1/seller/products/{uuid4()}/submit", json={"version": 1})
        assert submitted.status_code == 503
        assert submitted.json()["code"] == "publishing_paused"
        order = client.post(
            "/api/v1/orders",
            json={"product_id": str(uuid4()), "idempotency_key": "stage10-pause-test"},
        )
        assert order.status_code == 503
        assert order.json()["code"] == "trading_paused"


def test_reversed_product_appeal_stays_hidden_while_publishing_paused() -> None:
    report_id, product_id = uuid4(), uuid4()
    product = Product(
        id=product_id,
        status=ProductStatus.HIDDEN,
        hidden_from_status=ProductStatus.ON_SALE.value,
        moderation_source_report_id=report_id,
    )
    report = Report(
        id=report_id,
        target_type=ModerationTargetType.PRODUCT,
        target_id=product_id,
        public_result="申诉成立",
    )
    repository = SqlAlchemyModerationRepository(cast(AsyncSession, None))

    async def get_product(product_id: UUID, *, lock: bool = False) -> Product | None:
        assert lock
        assert product_id == product.id
        return product

    repository.get_product = get_product  # type: ignore[method-assign]
    asyncio.run(repository.restore_report_product(report, publish_allowed=False))
    assert product.status == ProductStatus.HIDDEN
    assert product.hidden_from_status == ProductStatus.ON_SALE.value
    assert product.moderation_source_report_id is None
