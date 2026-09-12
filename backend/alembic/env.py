import os
from asyncio import run
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app import models  # noqa: F401
from app.core.config import get_settings
from app.db.url import database_url_for_sqlalchemy, require_project_database, require_test_schema
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_test_schema() -> str | None:
    schema = os.getenv("DATABASE_SCHEMA")
    if schema is not None:
        require_test_schema(schema)
    return schema


def get_database_url() -> str:
    database_url = get_settings().database_url
    if database_url is None:
        raise RuntimeError("DATABASE_URL is required for migrations")
    require_project_database(database_url)
    return database_url_for_sqlalchemy(database_url)


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_database_url()
    server_settings = {"timezone": "UTC"}
    test_schema = get_test_schema()
    if test_schema is not None:
        server_settings["search_path"] = test_schema
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        pool_pre_ping=True,
        connect_args={"server_settings": server_settings},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(configure)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run(run_migrations_online())
