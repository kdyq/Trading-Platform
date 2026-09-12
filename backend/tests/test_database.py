import pytest

from app.db.url import database_url_for_sqlalchemy, require_project_database


def test_database_url_normalizes_async_driver() -> None:
    assert (
        database_url_for_sqlalchemy("postgresql://user:secret@localhost/campus_trading_platform")
        == "postgresql+asyncpg://user:secret@localhost/campus_trading_platform"
    )


def test_database_guard_rejects_another_project() -> None:
    with pytest.raises(RuntimeError, match="Refusing database target"):
        require_project_database("postgresql://user:secret@localhost/another_project")
