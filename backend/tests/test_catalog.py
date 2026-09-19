from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_catalog_service
from app.core.config import Settings
from app.core.exceptions import AppError
from app.main import create_app
from app.schemas.catalog import CatalogItemUpdate
from app.services.catalog import CatalogCache, CatalogService


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.root_id = uuid4()
        self.child_id = uuid4()
        self.school_id = uuid4()
        self.campus_id = uuid4()
        self.calls = 0
        self.allowed_users: set[UUID] = set()
        self.root = SimpleNamespace(
            id=self.root_id,
            parent_id=None,
            code="books",
            slug="books",
            name="教材书籍",
            level=0,
            display_order=0,
            is_active=True,
            deleted_at=None,
            version=1,
        )
        self.child = SimpleNamespace(
            id=self.child_id,
            parent_id=self.root_id,
            code="textbooks",
            slug="textbooks",
            name="专业教材",
            level=1,
            display_order=0,
            is_active=True,
            deleted_at=None,
            version=1,
        )
        self.campus = SimpleNamespace(
            id=self.campus_id,
            school_id=self.school_id,
            code="east",
            name="东校区",
            display_order=0,
            is_active=True,
            deleted_at=None,
            version=1,
        )
        self.school = SimpleNamespace(
            id=self.school_id,
            code="demo",
            name="示例学校",
            campuses=[self.campus],
        )

    async def list_public_categories(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        return [self.root, self.child]

    async def list_public_schools(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        return [self.school]

    async def list_all_categories(self):  # type: ignore[no-untyped-def]
        return [self.root, self.child]

    async def list_all_campuses(self):  # type: ignore[no-untyped-def]
        return [(self.campus, self.school.name)]

    async def has_permission(self, user_id, permission_code):  # type: ignore[no-untyped-def]
        return permission_code == "catalog:read" and user_id in self.allowed_users

    async def update_category(  # type: ignore[no-untyped-def]
        self, category_id, *, version, display_order, is_active
    ):
        if category_id != self.root.id:
            raise AssertionError("unexpected category")
        if version != self.root.version:
            raise AppError(409, "catalog_version_conflict", "conflict")
        if display_order is not None:
            self.root.display_order = display_order
        if is_active is not None:
            self.root.is_active = is_active
        self.root.version += 1
        return self.root

    async def update_campus(  # type: ignore[no-untyped-def]
        self, campus_id, *, version, display_order, is_active
    ):
        assert campus_id == self.campus.id and version == self.campus.version
        if display_order is not None:
            self.campus.display_order = display_order
        if is_active is not None:
            self.campus.is_active = is_active
        self.campus.version += 1
        return self.campus


def test_public_catalog_routes_return_tree_and_only_active_campuses() -> None:
    repository = FakeCatalogRepository()
    service = CatalogService(repository, CatalogCache())
    app = create_app(Settings(database_url=None, redis_url=None))
    app.dependency_overrides[get_catalog_service] = lambda: service

    with TestClient(app) as client:
        categories = client.get("/api/v1/catalog/categories")
        schools = client.get("/api/v1/catalog/schools")
        cached = client.get("/api/v1/catalog/categories")

    assert categories.status_code == 200
    assert categories.json()[0]["children"][0]["slug"] == "textbooks"
    assert schools.status_code == 200
    assert schools.json()[0]["campuses"][0]["code"] == "east"
    assert cached.json() == categories.json()
    assert repository.calls == 2


@pytest.mark.anyio
async def test_admin_catalog_requires_permission_and_invalidates_cache() -> None:
    repository = FakeCatalogRepository()
    cache = CatalogCache()
    service = CatalogService(repository, cache)
    user_id = uuid4()
    await service.public_categories()

    with pytest.raises(AppError) as denied:
        await service.admin_categories(user_id)
    assert denied.value.status_code == 403

    repository.allowed_users.add(user_id)
    updated = await service.update_category(
        user_id,
        repository.root_id,
        CatalogItemUpdate(version=1, display_order=3, is_active=False),
    )
    assert updated.display_order == 3
    assert updated.is_active is False
    assert cache.get("categories") is None
