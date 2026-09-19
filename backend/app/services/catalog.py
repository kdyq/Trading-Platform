from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from app.core.exceptions import AppError
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    AdminCampusResponse,
    AdminCategoryResponse,
    CampusCatalogResponse,
    CatalogItemUpdate,
    CategoryNodeResponse,
    SchoolCatalogResponse,
)


@dataclass
class _CacheEntry:
    expires_at: float
    value: object


class CatalogCache:
    def __init__(self, ttl_seconds: float = 60.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._values: dict[str, _CacheEntry] = {}

    def get(self, key: str) -> object | None:
        entry = self._values.get(key)
        if entry is None or entry.expires_at <= monotonic():
            self._values.pop(key, None)
            return None
        return entry.value

    def put(self, key: str, value: object) -> None:
        self._values[key] = _CacheEntry(monotonic() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._values.clear()


class CatalogService:
    def __init__(self, repository: CatalogRepository, cache: CatalogCache) -> None:
        self.repository = repository
        self.cache = cache

    async def public_categories(self) -> list[CategoryNodeResponse]:
        cached = self.cache.get("categories")
        if isinstance(cached, list):
            return cached
        records = await self.repository.list_public_categories()
        children: dict[UUID, list[CategoryNodeResponse]] = {}
        roots: list[CategoryNodeResponse] = []
        for record in records:
            node = CategoryNodeResponse(
                id=record.id,
                code=record.code,
                slug=record.slug,
                name=record.name,
                display_order=record.display_order,
            )
            if record.parent_id is None:
                roots.append(node)
            else:
                children.setdefault(record.parent_id, []).append(node)
        for root in roots:
            root.children = children.get(root.id, [])
        self.cache.put("categories", roots)
        return roots

    async def public_schools(self) -> list[SchoolCatalogResponse]:
        cached = self.cache.get("schools")
        if isinstance(cached, list):
            return cached
        schools = await self.repository.list_public_schools()
        response = [
            SchoolCatalogResponse(
                id=school.id,
                code=school.code,
                name=school.name,
                campuses=[
                    CampusCatalogResponse(
                        id=campus.id,
                        code=campus.code,
                        name=campus.name,
                        display_order=campus.display_order,
                    )
                    for campus in sorted(
                        (
                            campus
                            for campus in school.campuses
                            if campus.deleted_at is None and campus.is_active
                        ),
                        key=lambda item: (item.display_order, item.name, item.id),
                    )
                ],
            )
            for school in schools
        ]
        self.cache.put("schools", response)
        return response

    async def admin_categories(self, user_id: UUID) -> list[AdminCategoryResponse]:
        await self._require_admin(user_id)
        return [
            AdminCategoryResponse.model_validate(item, from_attributes=True)
            for item in await self.repository.list_all_categories()
        ]

    async def admin_campuses(self, user_id: UUID) -> list[AdminCampusResponse]:
        await self._require_admin(user_id)
        return [
            AdminCampusResponse(
                id=item.id,
                school_id=item.school_id,
                school_name=school_name,
                code=item.code,
                name=item.name,
                display_order=item.display_order,
                is_active=item.is_active,
                deleted_at=item.deleted_at,
                version=item.version,
            )
            for item, school_name in await self.repository.list_all_campuses()
        ]

    async def update_category(
        self, user_id: UUID, category_id: UUID, payload: CatalogItemUpdate
    ) -> AdminCategoryResponse:
        await self._require_admin(user_id)
        item = await self.repository.update_category(
            category_id,
            version=payload.version,
            display_order=payload.display_order,
            is_active=payload.is_active,
        )
        self.cache.clear()
        return AdminCategoryResponse.model_validate(item, from_attributes=True)

    async def update_campus(
        self, user_id: UUID, campus_id: UUID, payload: CatalogItemUpdate
    ) -> AdminCampusResponse:
        await self._require_admin(user_id)
        item = await self.repository.update_campus(
            campus_id,
            version=payload.version,
            display_order=payload.display_order,
            is_active=payload.is_active,
        )
        self.cache.clear()
        campuses = await self.repository.list_all_campuses()
        school_name = next(name for campus, name in campuses if campus.id == item.id)
        return AdminCampusResponse(
            id=item.id,
            school_id=item.school_id,
            school_name=school_name,
            code=item.code,
            name=item.name,
            display_order=item.display_order,
            is_active=item.is_active,
            deleted_at=item.deleted_at,
            version=item.version,
        )

    async def _require_admin(self, user_id: UUID) -> None:
        if not await self.repository.has_permission(user_id, "catalog:read"):
            raise AppError(status_code=403, code="permission_denied", message="无权管理基础数据")
