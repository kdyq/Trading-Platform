from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models import Base, OrderStatus, ProductStatus


def test_commerce_tables_are_registered() -> None:
    assert {
        "categories",
        "products",
        "product_images",
        "favorites",
        "conversations",
        "messages",
        "orders",
        "order_events",
        "reviews",
        "credit_ledgers",
        "reports",
        "moderation_records",
        "audit_logs",
    } <= set(Base.metadata.tables)


def test_product_image_position_is_unique_only_while_active() -> None:
    index = next(
        item
        for item in Base.metadata.tables["product_images"].indexes
        if item.name == "uq_product_images_active_position"
    )
    assert index.unique is True
    assert str(index.dialect_options["postgresql"]["where"]) == "deleted_at IS NULL"


def test_required_product_states_exist() -> None:
    assert {status.value for status in ProductStatus} == {
        "draft",
        "pending_review",
        "on_sale",
        "reserved",
        "sold",
        "rejected",
        "hidden",
        "deleted",
    }


def test_required_order_states_exist() -> None:
    assert {status.value for status in OrderStatus} == {
        "pending_seller_confirmation",
        "accepted",
        "scheduled",
        "seller_delivered",
        "completed",
        "cancelled",
        "expired",
        "disputed",
    }


def test_money_columns_use_exact_precision() -> None:
    assert str(Base.metadata.tables["products"].c.price.type) == "NUMERIC(12, 2)"
    assert str(Base.metadata.tables["orders"].c.amount.type) == "NUMERIC(12, 2)"


def test_critical_deduplication_constraints_exist() -> None:
    expected = {
        "favorites": "uq_favorites_user_product",
        "messages": "uq_messages_sender_client_message",
        "reviews": "uq_reviews_order_reviewer",
        "reports": "uq_reports_key",
    }
    for table_name, constraint_name in expected.items():
        assert any(
            isinstance(item, UniqueConstraint) and item.name == constraint_name
            for item in Base.metadata.tables[table_name].constraints
        )


def test_money_and_rating_checks_exist() -> None:
    for table_name in ("products", "orders", "reviews"):
        assert any(
            isinstance(item, CheckConstraint)
            for item in Base.metadata.tables[table_name].constraints
        )
