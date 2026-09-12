import pytest

from app.db.url import database_url_for_sqlalchemy, require_project_database, require_test_schema


def test_database_url_normalizes_async_driver() -> None:
    assert (
        database_url_for_sqlalchemy("postgresql://user:secret@localhost/campus_trading_platform")
        == "postgresql+asyncpg://user:secret@localhost/campus_trading_platform"
    )


def test_database_guard_rejects_another_project() -> None:
    with pytest.raises(RuntimeError, match="Refusing database target"):
        require_project_database("postgresql://user:secret@localhost/another_project")


def test_test_schema_guard_accepts_only_generated_gate_names() -> None:
    require_test_schema("test_gate_0123456789abcdef0123456789abcdef")
    with pytest.raises(RuntimeError, match="unsafe test schema"):
        require_test_schema("public")
