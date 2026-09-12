import re
from urllib.parse import urlsplit

PROJECT_DATABASE = "campus_trading_platform"
TEST_SCHEMA_PATTERN = re.compile(r"test_gate_[0-9a-f]{32}")


def database_url_for_sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def require_project_database(url: str) -> None:
    normalized = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    database_name = urlsplit(normalized).path.lstrip("/")
    if database_name != PROJECT_DATABASE:
        raise RuntimeError(f"Refusing database target: {database_name or 'missing'}")


def require_test_schema(schema: str) -> None:
    if TEST_SCHEMA_PATTERN.fullmatch(schema) is None:
        raise RuntimeError("Refusing unsafe test schema")
