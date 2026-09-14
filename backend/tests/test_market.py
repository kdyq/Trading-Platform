from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_market_service
from app.core.config import Settings
from app.main import create_app
from app.repositories.market import PublicMarketCounts, PublicProductRecord
from app.services.market import MarketService


class FakeMarketRepository:
    def __init__(self) -> None:
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.seller_id = uuid4()

    async def list_categories(self):  # type: ignore[no-untyped-def]
        return [SimpleNamespace(id=self.category_id, code="books", name="教材书籍")]

    async def list_latest_products(self, *, limit: int):  # type: ignore[no-untyped-def]
        assert limit == 4
        return [
            PublicProductRecord(
                id=self.product_id,
                seller_id=self.seller_id,
                title="高等数学教材",
                price=Decimal("18.50"),
                status="on_sale",
                published_at=datetime(2026, 9, 14, tzinfo=UTC),
                campus_name="东校区",
                school_name="测试学校",
                seller_name="小林",
                seller_verified=True,
                category_code="books",
                category_name="教材书籍",
            )
        ]

    async def count_latest_products(self) -> int:
        return 1

    async def get_summary(self) -> PublicMarketCounts:
        return PublicMarketCounts(available_products=1, active_campuses=1, verified_sellers=1)


def test_public_market_routes_return_only_public_contract() -> None:
    repository = FakeMarketRepository()
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(repository)

    with TestClient(app) as client:
        categories = client.get("/api/v1/market/categories")
        products = client.get("/api/v1/market/products?limit=4")
        summary = client.get("/api/v1/market/summary")

    assert categories.status_code == 200
    assert categories.json() == [
        {"id": str(repository.category_id), "code": "books", "name": "教材书籍"}
    ]
    assert products.status_code == 200
    assert products.json()["total"] == 1
    assert products.json()["items"][0]["title"] == "高等数学教材"
    assert "seller_id" not in products.json()["items"][0]
    assert "login_email" not in products.text
    assert summary.json() == {
        "available_products": 1,
        "active_campuses": 1,
        "verified_sellers": 1,
    }


def test_public_market_product_limit_is_bounded() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(FakeMarketRepository())
    with TestClient(app) as client:
        response = client.get("/api/v1/market/products?limit=25")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
