from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_market_service
from app.core.config import Settings
from app.main import create_app
from app.repositories.market import (
    PublicMarketCounts,
    PublicProductDetailRecord,
    PublicProductImageRecord,
    PublicProductRecord,
    SqlAlchemyMarketRepository,
)
from app.services.market import MarketService


class FakeMarketRepository:
    def __init__(self) -> None:
        self.category_id = uuid4()
        self.product_id = uuid4()
        self.seller_id = uuid4()
        self.image_id = uuid4()
        self.favorited = False

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
                created_at=datetime(2026, 9, 14, tzinfo=UTC),
                campus_name="东校区",
                school_name="测试学校",
                seller_name="小林",
                seller_verified=True,
                category_id=self.category_id,
                category_code="books",
                category_name="教材书籍",
                condition="good",
                is_negotiable=True,
                view_count=3,
                favorite_count=2,
            )
        ]

    async def list_campuses(self):  # type: ignore[no-untyped-def]
        return [(uuid4(), "东校区", "测试学校")]

    async def search_products(self, *, filters, cursor, limit):  # type: ignore[no-untyped-def]
        assert cursor is None
        assert limit == 12
        records = await self.list_latest_products(limit=4)
        return records, 1

    async def get_product(self, product_id):  # type: ignore[no-untyped-def]
        if product_id != self.product_id:
            return None
        record = (await self.list_latest_products(limit=4))[0]
        return PublicProductDetailRecord(
            **record.__dict__,
            description="少量笔记，无缺页。",
            seller_review_count=2,
            seller_average_rating=Decimal("4.50"),
            seller_completed_orders=3,
        )

    async def list_similar_products(  # type: ignore[no-untyped-def]
        self, *, product_id, category_id, limit
    ):
        assert product_id == self.product_id
        assert category_id == self.category_id
        assert limit == 4
        return []

    async def list_product_images(self, product_id):  # type: ignore[no-untyped-def]
        assert product_id == self.product_id
        return [
            PublicProductImageRecord(
                id=self.image_id,
                object_key="products/example.jpg",
                thumbnail_object_key="products/example-thumb.webp",
                alt_text="教材封面",
            )
        ]

    async def get_product_image(self, image_id):  # type: ignore[no-untyped-def]
        if image_id != self.image_id:
            return None
        return PublicProductImageRecord(
            id=self.image_id,
            object_key="products/example.jpg",
            thumbnail_object_key="products/example-thumb.webp",
            alt_text="教材封面",
        )

    async def count_latest_products(self) -> int:
        return 1

    async def get_summary(self) -> PublicMarketCounts:
        return PublicMarketCounts(available_products=1, active_campuses=1, verified_sellers=1)

    async def add_favorite(self, user_id, product_id):  # type: ignore[no-untyped-def]
        if product_id != self.product_id:
            return False
        self.favorited = True
        return True

    async def remove_favorite(self, user_id, product_id):  # type: ignore[no-untyped-def]
        self.favorited = False

    async def favorite_status(self, user_id, product_id):  # type: ignore[no-untyped-def]
        return self.favorited and product_id == self.product_id, 3 if self.favorited else 2

    async def list_favorites(self, user_id):  # type: ignore[no-untyped-def]
        return await self.list_latest_products(limit=4)


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
    assert products.json()["items"][0]["favorite_count"] == 2
    assert "seller_id" not in products.json()["items"][0]
    assert "login_email" not in products.text
    assert summary.json() == {
        "available_products": 1,
        "active_campuses": 1,
        "verified_sellers": 1,
    }


def test_public_product_detail_returns_trust_summary_without_private_fields() -> None:
    repository = FakeMarketRepository()
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(repository)
    with TestClient(app) as client:
        response = client.get(f"/api/v1/market/products/{repository.product_id}")

    assert response.status_code == 200
    assert response.json()["description"] == "少量笔记，无缺页。"
    assert response.json()["seller"] == {
        "id": str(repository.seller_id),
        "display_name": "小林",
        "campus_verified": True,
        "review_count": 2,
        "average_rating": "4.50",
        "completed_orders": 3,
    }
    assert response.json()["images"] == [
        {
            "id": str(repository.image_id),
            "url": f"/api/v1/market/product-images/{repository.image_id}",
            "alt_text": "教材封面",
        }
    ]
    assert "login_email" not in response.text
    assert "object_key" not in response.text


def test_public_product_detail_hides_unknown_or_non_public_products() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(FakeMarketRepository())
    with TestClient(app) as client:
        response = client.get(f"/api/v1/market/products/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "product_not_found"


@pytest.mark.anyio
async def test_favorites_are_idempotent_and_return_public_products() -> None:
    repository = FakeMarketRepository()
    service = MarketService(repository)
    user_id = uuid4()

    first = await service.add_favorite(user_id, repository.product_id)
    second = await service.add_favorite(user_id, repository.product_id)
    favorites = await service.favorites(user_id)
    await service.remove_favorite(user_id, repository.product_id)
    removed = await service.favorite_status(user_id, repository.product_id)

    assert first.favorited is True and first.favorite_count == 3
    assert second == first
    assert favorites.total == 1
    assert removed.favorited is False and removed.favorite_count == 2


def test_public_product_image_is_served_by_id_without_exposing_storage_key(tmp_path: Path) -> None:
    repository = FakeMarketRepository()
    image_path = tmp_path / "products" / "example.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\xff\xd8\xfftest")
    app = create_app(
        Settings(database_url=None, redis_url=None, public_product_storage_root=tmp_path)
    )
    app.dependency_overrides[get_market_service] = lambda: MarketService(repository)
    with TestClient(app) as client:
        response = client.get(f"/api/v1/market/product-images/{repository.image_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content == b"\xff\xd8\xfftest"
    assert "products/example.jpg" not in response.text


def test_public_market_product_limit_is_bounded() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(FakeMarketRepository())
    with TestClient(app) as client:
        response = client.get("/api/v1/market/products?limit=25")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.anyio
async def test_market_cursor_stays_fixed_length_across_many_pages() -> None:
    repository = FakeMarketRepository()
    record = (await repository.list_latest_products(limit=4))[0]
    service = MarketService(repository)

    cursors = [service._encode_cursor(record, "newest") for _ in range(10)]

    assert all(len(cursor) < 1000 for cursor in cursors)
    assert len({len(cursor) for cursor in cursors}) == 1


def test_public_market_search_accepts_url_filters() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(FakeMarketRepository())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/market/products?keyword=%E6%95%99%E6%9D%90&category=books"
            "&condition=good&negotiable=true&status=on_sale&sort=price_asc&page=1"
        )
    assert response.status_code == 200
    assert response.json()["items"][0]["condition"] == "good"
    assert response.json()["items"][0]["is_negotiable"] is True


def test_public_market_search_rejects_inverted_price_range() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(FakeMarketRepository())
    with TestClient(app) as client:
        response = client.get("/api/v1/market/products?min_price=20&max_price=10")
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_price_range"


def test_public_market_search_accepts_reserved_status() -> None:
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_market_service] = lambda: MarketService(FakeMarketRepository())
    with TestClient(app) as client:
        response = client.get("/api/v1/market/products?status=reserved")
    assert response.status_code == 200


def test_verified_seller_query_is_correlated_to_current_product() -> None:
    repository = object.__new__(SqlAlchemyMarketRepository)
    query = repository._public_product_query(SqlAlchemyMarketRepository.PUBLIC_STATUSES)
    sql = str(query)
    assert "FROM campus_verifications, products" not in sql
