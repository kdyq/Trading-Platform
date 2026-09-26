import asyncio
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import asyncpg

BACKEND_ROOT = Path(__file__).parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
POSTGRES_TESTS = (
    "tests/test_identity_constraints_postgres.py",
    "tests/test_commerce_constraints_postgres.py",
    "tests/test_session_transactions_postgres.py",
    "tests/test_auth_rotation_postgres.py",
    "tests/test_product_image_migration_postgres.py",
    "tests/test_campus_binding_postgres.py",
    "tests/test_market_queries_postgres.py",
    "tests/test_orders_postgres.py",
    "tests/test_reports_postgres.py",
    "tests/test_credit_postgres.py",
    "tests/test_moderation_postgres.py",
    "tests/test_moderation_appeals_postgres.py",
)


def load_database_url() -> str:
    if database_url := os.getenv("DATABASE_URL"):
        return database_url
    config_path = PROJECT_ROOT / ".codex/config.toml"
    if not config_path.exists():
        raise RuntimeError("DATABASE_URL or the ignored project MCP config is required")
    config = tomllib.loads(config_path.read_text("utf-8"))
    return config["mcp_servers"]["postgres"]["env"]["DATABASE_URI"]


def asyncpg_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def execute_schema(database_url: str, statement: str) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


async def verify_seed(database_url: str, schema: str) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        count = await connection.fetchval("SELECT count(*) FROM categories")
        distinct_codes = await connection.fetchval("SELECT count(DISTINCT code) FROM categories")
        if (count, distinct_codes) != (8, 8):
            raise RuntimeError("Category seed is not idempotent")
        print("PostgreSQL gate: 8 unique categories after two seed runs")
    finally:
        await connection.close()


def run(environment: dict[str, str], *arguments: str) -> None:
    subprocess.run(
        [sys.executable, *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
    )


def main() -> None:
    database_url = load_database_url()
    if urlparse(asyncpg_url(database_url)).path.lstrip("/") != "campus_trading_platform":
        raise RuntimeError("Refusing unexpected database target")
    schema = f"test_gate_{uuid4().hex}"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["DATABASE_SCHEMA"] = schema

    asyncio.run(execute_schema(database_url, f'CREATE SCHEMA "{schema}"'))
    try:
        run(environment, "-m", "alembic", "upgrade", "head")
        run(environment, "-m", "alembic", "check")
        run(environment, "-m", "pytest", "-q", *POSTGRES_TESTS)
        run(environment, "-m", "alembic", "downgrade", "base")
        run(environment, "-m", "alembic", "upgrade", "head")
        run(environment, "-m", "app.db.seed")
        run(environment, "-m", "app.db.seed")
        asyncio.run(verify_seed(database_url, schema))
    finally:
        asyncio.run(execute_schema(database_url, f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


if __name__ == "__main__":
    main()
