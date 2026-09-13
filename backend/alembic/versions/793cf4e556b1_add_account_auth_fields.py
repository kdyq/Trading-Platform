"""add account authentication fields

Revision ID: 793cf4e556b1
Revises: 71217f66a358
Create Date: 2026-09-13 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "793cf4e556b1"
down_revision: str | None = "71217f66a358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_users_login_email", table_name="users")
    op.create_index(
        "uq_users_login_email",
        "users",
        [sa.literal_column("lower(login_email)")],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.add_column(
        "users", sa.Column("login_email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("user_agreement_version", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("privacy_policy_version", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("terms_agreed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("avatar_key", sa.String(255), nullable=True))
    op.execute(
        """
        UPDATE users
        SET login_email_verified_at = created_at,
            user_agreement_version = 'pre-account-rules',
            privacy_policy_version = 'pre-account-rules',
            terms_agreed_at = created_at
        """
    )
    op.alter_column("users", "login_email_verified_at", nullable=False)
    op.alter_column("users", "user_agreement_version", nullable=False)
    op.alter_column("users", "privacy_policy_version", nullable=False)
    op.alter_column("users", "terms_agreed_at", nullable=False)
    op.add_column("user_sessions", sa.Column("user_agent", sa.String(512), nullable=True))
    op.add_column("user_sessions", sa.Column("ip_address", sa.String(64), nullable=True))
    op.add_column(
        "user_sessions", sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE user_sessions SET authenticated_at = created_at")
    op.alter_column("user_sessions", "authenticated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("user_sessions", "authenticated_at")
    op.drop_column("user_sessions", "ip_address")
    op.drop_column("user_sessions", "user_agent")
    op.drop_column("users", "avatar_key")
    op.drop_column("users", "terms_agreed_at")
    op.drop_column("users", "privacy_policy_version")
    op.drop_column("users", "user_agreement_version")
    op.drop_column("users", "login_email_verified_at")
    # Keep the partial unique index so a downgrade never destroys or rejects a
    # legitimate soft-delete followed by re-registration.
