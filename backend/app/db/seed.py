import asyncio
import os
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.permissions import ROLE_PERMISSIONS
from app.db.session import create_database_engine
from app.db.url import require_project_database
from app.models.catalog import Category
from app.models.identity import Permission, Role, role_permissions

DEFAULT_CATEGORIES: Sequence[tuple[str, str]] = (
    ("digital", "数码电子"),
    ("books", "教材书籍"),
    ("home", "生活家居"),
    ("sports", "运动户外"),
    ("fashion", "服饰鞋包"),
    ("creative", "乐器文创"),
    ("beauty", "美妆个护"),
    ("wanted", "求购专区"),
)


async def seed_categories(connection: AsyncConnection) -> None:
    statement = insert(Category).values(
        [
            {
                "code": code,
                "slug": code,
                "name": name,
                "level": 0,
                "display_order": position,
            }
            for position, (code, name) in enumerate(DEFAULT_CATEGORIES)
        ]
    )
    await connection.execute(
        statement.on_conflict_do_update(
            index_elements=[Category.code],
            set_={
                "name": statement.excluded.name,
                "slug": statement.excluded.slug,
                "level": statement.excluded.level,
                "display_order": statement.excluded.display_order,
                "is_active": True,
                "deleted_at": None,
            },
        )
    )


async def seed_roles_and_permissions(connection: AsyncConnection) -> None:
    """Synchronize the fixed matrix; never grant roles to users implicitly."""
    role_names = {
        "USER": "普通用户",
        "SUPPORT": "客服",
        "REVIEWER": "审核员",
        "ADMIN": "管理员",
        "SUPER_ADMIN": "超级管理员",
    }
    for code, name in role_names.items():
        await connection.execute(
            insert(Role)
            .values(code=code, name=name, description=None, deleted_at=None)
            .on_conflict_do_update(
                index_elements=[Role.code], set_={"name": name, "deleted_at": None}
            )
        )
    codes = sorted(set().union(*ROLE_PERMISSIONS.values()))
    for code in codes:
        await connection.execute(
            insert(Permission)
            .values(code=code, name=code.replace(":", " · "), description=None)
            .on_conflict_do_nothing(index_elements=[Permission.code])
        )
    roles: dict[str, UUID] = {
        code: role_id for code, role_id in (await connection.execute(select(Role.code, Role.id)))
    }
    permissions: dict[str, UUID] = {
        code: permission_id
        for code, permission_id in (
            await connection.execute(select(Permission.code, Permission.id))
        )
    }
    for role_code, role_permissions_set in ROLE_PERMISSIONS.items():
        await connection.execute(
            delete(role_permissions).where(role_permissions.c.role_id == roles[role_code])
        )
        for permission_code in sorted(role_permissions_set):
            await connection.execute(
                insert(role_permissions)
                .values(role_id=roles[role_code], permission_id=permissions[permission_code])
                .on_conflict_do_nothing()
            )


async def main() -> None:
    database_url = get_settings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL is required for seeding")
    require_project_database(database_url)

    engine = create_database_engine(database_url, schema=os.getenv("DATABASE_SCHEMA"))
    try:
        async with engine.begin() as connection:
            await seed_categories(connection)
            await seed_roles_and_permissions(connection)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
