from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.catalog import Category
from app.models.identity import (
    Campus,
    Permission,
    Role,
    School,
    User,
    role_permissions,
    user_roles,
)


class CatalogRepository(Protocol):
    async def list_public_categories(self) -> Sequence[Category]: ...

    async def list_public_schools(self) -> Sequence[School]: ...

    async def list_all_categories(self) -> Sequence[Category]: ...

    async def list_all_campuses(self) -> Sequence[tuple[Campus, str]]: ...

    async def has_permission(self, user_id: UUID, permission_code: str) -> bool: ...

    async def update_category(
        self,
        category_id: UUID,
        *,
        version: int,
        display_order: int | None,
        is_active: bool | None,
    ) -> Category: ...

    async def update_campus(
        self,
        campus_id: UUID,
        *,
        version: int,
        display_order: int | None,
        is_active: bool | None,
    ) -> Campus: ...


class SqlAlchemyCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_public_categories(self) -> Sequence[Category]:
        result = await self.session.scalars(
            select(Category)
            .where(Category.deleted_at.is_(None), Category.is_active.is_(True))
            .order_by(Category.level, Category.display_order, Category.name, Category.id)
        )
        return result.all()

    async def list_public_schools(self) -> Sequence[School]:
        result = await self.session.scalars(
            select(School)
            .options(selectinload(School.campuses))
            .where(School.deleted_at.is_(None), School.is_active.is_(True))
            .order_by(School.name, School.id)
        )
        return result.unique().all()

    async def list_all_categories(self) -> Sequence[Category]:
        result = await self.session.scalars(
            select(Category).order_by(Category.level, Category.display_order, Category.name)
        )
        return result.all()

    async def list_all_campuses(self) -> Sequence[tuple[Campus, str]]:
        result = await self.session.execute(
            select(Campus, School.name)
            .join(School, School.id == Campus.school_id)
            .order_by(School.name, Campus.display_order, Campus.name)
        )
        return [(row[0], row[1]) for row in result]

    async def has_permission(self, user_id: UUID, permission_code: str) -> bool:
        found = await self.session.scalar(
            select(Permission.id)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .join(Role, Role.id == role_permissions.c.role_id)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .join(User, User.id == user_roles.c.user_id)
            .where(
                user_roles.c.user_id == user_id,
                Permission.code == permission_code,
                Role.deleted_at.is_(None),
                User.must_change_password.is_(False),
            )
            .limit(1)
        )
        return found is not None

    async def update_category(
        self,
        category_id: UUID,
        *,
        version: int,
        display_order: int | None,
        is_active: bool | None,
    ) -> Category:
        item = await self.session.scalar(
            select(Category).where(Category.id == category_id).with_for_update()
        )
        if item is None:
            raise AppError(status_code=404, code="category_not_found", message="分类不存在")
        self._check_version(item.version, version)
        if display_order is not None:
            item.display_order = display_order
        if is_active is not None:
            item.is_active = is_active
        await self.session.flush()
        return item

    async def update_campus(
        self,
        campus_id: UUID,
        *,
        version: int,
        display_order: int | None,
        is_active: bool | None,
    ) -> Campus:
        item = await self.session.scalar(
            select(Campus).where(Campus.id == campus_id).with_for_update()
        )
        if item is None:
            raise AppError(status_code=404, code="campus_not_found", message="校区不存在")
        self._check_version(item.version, version)
        if display_order is not None:
            item.display_order = display_order
        if is_active is not None:
            item.is_active = is_active
        await self.session.flush()
        return item

    @staticmethod
    def _check_version(actual: int, expected: int) -> None:
        if actual != expected:
            raise AppError(
                status_code=409,
                code="catalog_version_conflict",
                message="基础数据已被其他操作更新，请刷新后重试",
            )
