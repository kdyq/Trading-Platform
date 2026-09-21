"""fix notification delivery audit and recipient idempotency

Revision ID: a8d31e7f4b2c
Revises: f7c20d5a91be
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8d31e7f4b2c"
down_revision: str | None = "f7c20d5a91be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_notifications_event_key", "notifications", type_="unique")
    op.create_unique_constraint(
        "uq_notifications_user_event_key", "notifications", ["user_id", "event_key"]
    )
    op.add_column(
        "notification_delivery_attempts",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_notification_attempts_retry",
        "notification_delivery_attempts",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_attempts_retry", table_name="notification_delivery_attempts")
    op.drop_column("notification_delivery_attempts", "next_retry_at")
    op.drop_constraint("uq_notifications_user_event_key", "notifications", type_="unique")
    # The old schema can represent only one recipient for an event key. Preserve the
    # earliest notification deterministically and remove dependent attempts first.
    op.execute(
        sa.text(
            """
            WITH duplicates AS (
                SELECT id, row_number() OVER (
                    PARTITION BY event_key ORDER BY created_at, id
                ) AS position
                FROM notifications
            )
            DELETE FROM notification_delivery_attempts
            WHERE notification_id IN (
                SELECT id FROM duplicates WHERE position > 1
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH duplicates AS (
                SELECT id, row_number() OVER (
                    PARTITION BY event_key ORDER BY created_at, id
                ) AS position
                FROM notifications
            )
            DELETE FROM notifications
            WHERE id IN (SELECT id FROM duplicates WHERE position > 1)
            """
        )
    )
    op.create_unique_constraint("uq_notifications_event_key", "notifications", ["event_key"])
