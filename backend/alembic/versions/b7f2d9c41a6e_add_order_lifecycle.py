"""add order lifecycle

Revision ID: b7f2d9c41a6e
Revises: a8d31e7f4b2c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7f2d9c41a6e"
down_revision: str | None = "a8d31e7f4b2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORDER_STATUSES = (
    "pending_seller_confirmation",
    "accepted",
    "scheduled",
    "seller_delivered",
    "completed",
    "cancelled",
    "expired",
    "disputed",
)
LEGACY_ORDER_STATUSES = tuple(value for value in ORDER_STATUSES if value != "seller_delivered")


def status_check(column: str, values: tuple[str, ...]) -> str:
    choices = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({choices})"


def upgrade() -> None:
    op.drop_index("uq_orders_active_product", table_name="orders")
    op.drop_constraint(op.f("ck_orders_order_status"), "orders", type_="check")
    op.drop_constraint(
        op.f("ck_order_events_order_event_from_status"), "order_events", type_="check"
    )
    op.drop_constraint(op.f("ck_order_events_order_event_to_status"), "order_events", type_="check")
    op.create_check_constraint("order_status", "orders", status_check("status", ORDER_STATUSES))
    op.create_check_constraint(
        "order_event_from_status",
        "order_events",
        f"from_status IS NULL OR {status_check('from_status', ORDER_STATUSES)}",
    )
    op.create_check_constraint(
        "order_event_to_status",
        "order_events",
        status_check("to_status", ORDER_STATUSES),
    )

    op.add_column("orders", sa.Column("conversation_id", sa.Uuid(), nullable=True))
    op.add_column("orders", sa.Column("product_title_snapshot", sa.String(120), nullable=True))
    op.add_column("orders", sa.Column("campus_name_snapshot", sa.String(120), nullable=True))
    op.add_column("orders", sa.Column("buyer_display_name_snapshot", sa.String(80), nullable=True))
    op.add_column("orders", sa.Column("seller_display_name_snapshot", sa.String(80), nullable=True))
    op.add_column(
        "orders",
        sa.Column("payment_mode", sa.String(24), server_default="offline", nullable=False),
    )
    op.add_column("orders", sa.Column("seller_delivered_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("cancellation_reason_code", sa.String(64)))
    op.add_column("orders", sa.Column("cancellation_note", sa.Text()))
    op.add_column("orders", sa.Column("disputed_at", sa.DateTime(timezone=True)))
    op.add_column("orders", sa.Column("dispute_reason_code", sa.String(64)))
    op.add_column("orders", sa.Column("dispute_details", sa.Text()))
    op.create_foreign_key(
        "fk_orders_conversation_id_conversations",
        "orders",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        sa.text(
            """
            UPDATE orders AS o
            SET product_title_snapshot = p.title,
                campus_name_snapshot = c.name,
                buyer_display_name_snapshot = buyer.display_name,
                seller_display_name_snapshot = seller.display_name
            FROM products AS p, campuses AS c, users AS buyer, users AS seller
            WHERE p.id = o.product_id
              AND c.id = p.campus_id
              AND buyer.id = o.buyer_id
              AND seller.id = o.seller_id
            """
        )
    )
    for column in (
        "product_title_snapshot",
        "campus_name_snapshot",
        "buyer_display_name_snapshot",
        "seller_display_name_snapshot",
    ):
        op.alter_column("orders", column, nullable=False)

    op.create_index(
        "uq_orders_active_product",
        "orders",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('accepted', 'scheduled', 'seller_delivered', 'disputed')"
        ),
    )
    op.create_index(
        "uq_orders_open_buyer_product",
        "orders",
        ["product_id", "buyer_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_seller_confirmation', 'accepted', 'scheduled', "
            "'seller_delivered', 'disputed')"
        ),
    )

    op.create_table(
        "order_meeting_proposals",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("proposer_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_text", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "accepted",
                "superseded",
                "withdrawn",
                name="meeting_proposal_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("buyer_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("seller_confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(location_text) BETWEEN 2 AND 200",
            name="ck_order_meeting_proposals_location_length",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_order_meeting_proposals_order_created",
        "order_meeting_proposals",
        ["order_id", "created_at"],
    )

    op.create_table(
        "order_commands",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("client_action_id", sa.String(64), nullable=False),
        sa.Column("command", sa.String(48), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("event_id", sa.Uuid()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["event_id"], ["order_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_id", "client_action_id", name="uq_order_commands_actor_action"),
    )
    op.create_index("ix_order_commands_order_created", "order_commands", ["order_id", "created_at"])

    op.add_column(
        "reviews",
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
    )
    op.add_column(
        "reviews", sa.Column("is_visible", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column("reviews", sa.Column("hidden_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.execute("UPDATE orders SET status = 'accepted' WHERE status = 'seller_delivered'")
    op.execute(
        """
        UPDATE order_events SET from_status = 'accepted'
        WHERE from_status = 'seller_delivered'
        """
    )
    op.execute(
        """
        UPDATE order_events SET to_status = 'accepted'
        WHERE to_status = 'seller_delivered'
        """
    )
    op.execute(
        """
        UPDATE orders AS pending
        SET status = 'cancelled', cancelled_at = now()
        WHERE pending.status = 'pending_seller_confirmation'
          AND EXISTS (
              SELECT 1 FROM orders AS reserved
              WHERE reserved.product_id = pending.product_id
                AND reserved.id <> pending.id
                AND reserved.status IN ('accepted', 'scheduled', 'disputed')
          )
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY product_id ORDER BY created_at, id
            ) AS position
            FROM orders WHERE status = 'pending_seller_confirmation'
        )
        UPDATE orders SET status = 'cancelled', cancelled_at = now()
        WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """
    )
    op.drop_column("reviews", "hidden_at")
    op.drop_column("reviews", "is_visible")
    op.drop_column("reviews", "tags")
    op.drop_index("ix_order_commands_order_created", table_name="order_commands")
    op.drop_table("order_commands")
    op.drop_index("ix_order_meeting_proposals_order_created", table_name="order_meeting_proposals")
    op.drop_table("order_meeting_proposals")
    op.drop_index("uq_orders_open_buyer_product", table_name="orders")
    op.drop_index("uq_orders_active_product", table_name="orders")
    op.create_index(
        "uq_orders_active_product",
        "orders",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_seller_confirmation', 'accepted', 'scheduled', 'disputed')"
        ),
    )
    op.drop_constraint("fk_orders_conversation_id_conversations", "orders", type_="foreignkey")
    for column in (
        "dispute_details",
        "dispute_reason_code",
        "disputed_at",
        "cancellation_note",
        "cancellation_reason_code",
        "seller_delivered_at",
        "payment_mode",
        "seller_display_name_snapshot",
        "buyer_display_name_snapshot",
        "campus_name_snapshot",
        "product_title_snapshot",
        "conversation_id",
    ):
        op.drop_column("orders", column)
    op.drop_constraint(op.f("ck_order_events_order_event_to_status"), "order_events", type_="check")
    op.drop_constraint(
        op.f("ck_order_events_order_event_from_status"), "order_events", type_="check"
    )
    op.drop_constraint(op.f("ck_orders_order_status"), "orders", type_="check")
    op.create_check_constraint(
        "order_status", "orders", status_check("status", LEGACY_ORDER_STATUSES)
    )
    op.create_check_constraint(
        "order_event_from_status",
        "order_events",
        f"from_status IS NULL OR {status_check('from_status', LEGACY_ORDER_STATUSES)}",
    )
    op.create_check_constraint(
        "order_event_to_status",
        "order_events",
        status_check("to_status", LEGACY_ORDER_STATUSES),
    )
