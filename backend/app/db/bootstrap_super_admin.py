"""Explicit one-time super-admin bootstrap. No password is stored in source or logs."""

import argparse
import asyncio
import getpass
import os
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select

from app.core.config import get_settings
from app.core.security import PasswordManager
from app.db.seed import seed_roles_and_permissions
from app.db.session import create_database_engine
from app.db.url import require_project_database
from app.models.identity import Role, User, UserStatus, user_roles


async def bootstrap(password: str) -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is required")
    require_project_database(settings.database_url)
    engine = create_database_engine(settings.database_url, schema=os.getenv("DATABASE_SCHEMA"))
    try:
        async with engine.begin() as connection:
            # This is explicit setup, not an application-startup side effect.
            await seed_roles_and_permissions(connection)
            existing = await connection.scalar(select(User.id).where(User.username == "guo"))
            if existing is not None:
                raise RuntimeError("Bootstrap account already exists; no account was changed")
            role = await connection.scalar(select(Role.id).where(Role.code == "SUPER_ADMIN"))
            if role is None:
                raise RuntimeError("SUPER_ADMIN role is unavailable")
            now = datetime.now(UTC)
            user_id = uuid4()
            await connection.execute(
                insert(User).values(
                    id=user_id,
                    login_email=None,
                    username="guo",
                    password_hash=PasswordManager().hash(password),
                    must_change_password=True,
                    display_name="平台管理员",
                    status=UserStatus.ACTIVE,
                    last_login_at=None,
                    login_email_verified_at=None,
                    user_agreement_version=settings.user_agreement_version,
                    privacy_policy_version=settings.privacy_policy_version,
                    terms_agreed_at=now,
                    avatar_key=None,
                )
            )
            await connection.execute(insert(user_roles).values(user_id=user_id, role_id=role))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the one-time guo super-admin account")
    parser.parse_args()
    password = os.environ.get("BOOTSTRAP_SUPER_ADMIN_PASSWORD") or getpass.getpass(
        "Initial password (not echoed): "
    )
    if not password:
        raise SystemExit("Initial password is required")
    asyncio.run(bootstrap(password))
    print("Super-admin account created; password change required on first login")


if __name__ == "__main__":
    main()
