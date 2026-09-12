from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.url import (
    database_url_for_sqlalchemy,
    require_project_database,
    require_test_schema,
)


def create_database_engine(database_url: str, *, schema: str | None = None) -> AsyncEngine:
    require_project_database(database_url)
    server_settings = {"timezone": "UTC"}
    if schema is not None:
        require_test_schema(schema)
        server_settings["search_path"] = schema
    return create_async_engine(
        database_url_for_sqlalchemy(database_url),
        pool_pre_ping=True,
        connect_args={"server_settings": server_settings},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        async with session.begin():
            yield session


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with transaction_scope(session_factory) as session:
        yield session


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if session_factory is None:
        raise RuntimeError("Database is not configured")
    async for session in session_scope(session_factory):
        yield session
