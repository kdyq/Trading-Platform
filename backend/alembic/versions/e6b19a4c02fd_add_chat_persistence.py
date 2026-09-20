"""add chat persistence

Revision ID: e6b19a4c02fd
Revises: d5a07c2b91ef
"""

import sqlalchemy as sa

from alembic import op

revision: str = "e6b19a4c02fd"
down_revision: str | None = "d5a07c2b91ef"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("product_title_snapshot", sa.String(120)))
    op.add_column("conversations", sa.Column("product_price_snapshot", sa.Numeric(12, 2)))
    op.execute(
        """
        UPDATE conversations AS c
        SET product_title_snapshot = p.title, product_price_snapshot = p.price
        FROM products AS p WHERE p.id = c.product_id
        """
    )
    op.alter_column("conversations", "product_title_snapshot", nullable=False)
    op.alter_column("conversations", "product_price_snapshot", nullable=False)
    op.create_check_constraint(
        "ck_messages_body_length", "messages", "char_length(body) BETWEEN 1 AND 2000"
    )
    op.create_table(
        "conversation_read_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("last_read_message_id", sa.Uuid()),
        sa.Column("last_read_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["last_read_message_id"], ["messages.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_read_states_member"
        ),
    )
    op.create_index(
        "ix_conversation_read_states_user",
        "conversation_read_states",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_read_states_user", table_name="conversation_read_states")
    op.drop_table("conversation_read_states")
    op.drop_constraint("ck_messages_body_length", "messages", type_="check")
    op.drop_column("conversations", "product_price_snapshot")
    op.drop_column("conversations", "product_title_snapshot")
