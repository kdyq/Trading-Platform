import asyncio
import os
from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.db.session import create_database_engine
from app.db.url import require_project_database
from app.models.catalog import Category

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


async def main() -> None:
    database_url = get_settings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL is required for seeding")
    require_project_database(database_url)

    engine = create_database_engine(database_url, schema=os.getenv("DATABASE_SCHEMA"))
    try:
        async with engine.begin() as connection:
            await seed_categories(connection)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
