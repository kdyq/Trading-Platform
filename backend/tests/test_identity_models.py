from sqlalchemy import CheckConstraint, Index

from app.models import Base, CampusVerificationStatus


def test_identity_tables_are_registered() -> None:
    assert {
        "schools",
        "campuses",
        "users",
        "campus_verifications",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        "user_sessions",
    } <= set(Base.metadata.tables)


def test_login_and_campus_email_are_separate_columns() -> None:
    users = Base.metadata.tables["users"]
    verifications = Base.metadata.tables["campus_verifications"]

    assert "login_email" in users.c
    assert "campus_email" not in users.c
    assert "campus_email" in verifications.c
    assert "login_email" not in verifications.c


def test_active_campus_email_has_a_partial_unique_index() -> None:
    table = Base.metadata.tables["campus_verifications"]
    index = next(
        item for item in table.indexes if item.name == "uq_campus_verifications_active_email"
    )

    assert isinstance(index, Index)
    assert index.unique is True
    assert "verified" in str(index.dialect_options["postgresql"]["where"])


def test_required_verification_states_exist() -> None:
    assert {status.value for status in CampusVerificationStatus} == {
        "unapplied",
        "pending",
        "verified",
        "rejected",
        "expired",
        "appealing",
    }


def test_email_columns_have_lowercase_checks() -> None:
    for table_name in ("users", "campus_verifications"):
        constraints = Base.metadata.tables[table_name].constraints
        assert any(isinstance(item, CheckConstraint) for item in constraints)
