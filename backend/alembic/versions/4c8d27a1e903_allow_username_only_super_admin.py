"""allow username-only super-admin identity

Revision ID: 4c8d27a1e903
Revises: 1c3e90d4a72b
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4c8d27a1e903"
down_revision: str | None = "1c3e90d4a72b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "login_email", existing_type=sa.String(320), nullable=True)
    op.alter_column(
        "users", "login_email_verified_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.create_check_constraint(
        "ck_users_login_identity_present",
        "users",
        "login_email IS NOT NULL OR username IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_users_login_email_verification_consistent",
        "users",
        "(login_email IS NULL AND login_email_verified_at IS NULL) OR "
        "(login_email IS NOT NULL AND login_email_verified_at IS NOT NULL)",
    )


def downgrade() -> None:
    username_only_count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM users WHERE login_email IS NULL")
    )
    if username_only_count:
        raise RuntimeError(
            "Cannot downgrade while username-only users exist; migrate those identities explicitly"
        )
    op.drop_constraint("ck_users_login_email_verification_consistent", "users", type_="check")
    op.drop_constraint("ck_users_login_identity_present", "users", type_="check")
    op.alter_column(
        "users", "login_email_verified_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.alter_column("users", "login_email", existing_type=sa.String(320), nullable=False)
