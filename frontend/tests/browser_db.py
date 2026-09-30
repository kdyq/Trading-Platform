"""Connect browser fixture scripts to the same isolated schema as the API."""

import os

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.url import database_url_for_sqlalchemy, require_test_schema


def browser_engine(database_url: str) -> AsyncEngine:
    schema = os.getenv("DATABASE_SCHEMA")
    if schema:
        require_test_schema(schema)
        return create_async_engine(
            database_url_for_sqlalchemy(database_url),
            connect_args={
                "server_settings": {"search_path": schema, "timezone": "UTC"}
            },
        )
    return create_async_engine(database_url_for_sqlalchemy(database_url))
