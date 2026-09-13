import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import PasswordManager, TokenManager
from app.db.session import create_database_engine, create_session_factory, transaction_scope
from app.models.identity import User, UserSession, UserStatus
from app.repositories.identity import SqlAlchemyIdentityRepository
from app.services.auth import AuthService
from app.services.email_verification import UnavailableVerificationCodeStore
from app.services.mailer import UnavailableVerificationMailer


def test_concurrent_refresh_has_one_winner_and_revokes_the_family() -> None:
    database_url = os.getenv("DATABASE_URL")
    schema = os.getenv("DATABASE_SCHEMA")
    if database_url is None or schema is None:
        pytest.skip("PostgreSQL gate schema is required")
    asyncio.run(_exercise_concurrent_refresh(database_url, schema))


async def _exercise_concurrent_refresh(database_url: str, schema: str) -> None:
    engine = create_database_engine(database_url, schema=schema)
    session_factory = create_session_factory(engine)
    secret = "postgres-test-secret-that-is-longer-than-32-characters"
    token_manager = TokenManager(secret, access_minutes=15, refresh_days=30)
    settings = Settings(
        database_url=database_url,
        auth_secret_key=secret,
        environment="test",
    )
    now = datetime.now(UTC)
    user_id = uuid4()
    family_id = uuid4()
    refresh_token, digest, expires_at = token_manager.issue_refresh_token()

    try:
        async with transaction_scope(session_factory) as session:
            repository = SqlAlchemyIdentityRepository(session)
            await repository.create_user(
                User(
                    id=user_id,
                    login_email=f"parallel-{user_id}@example.com",
                    password_hash="not-used",
                    display_name="并发测试用户",
                    status=UserStatus.ACTIVE,
                    last_login_at=now,
                    login_email_verified_at=now,
                    user_agreement_version="test",
                    privacy_policy_version="test",
                    terms_agreed_at=now,
                    avatar_key=None,
                )
            )
            await repository.create_session(
                UserSession(
                    id=uuid4(),
                    user_id=user_id,
                    family_id=family_id,
                    refresh_token_digest=digest,
                    expires_at=expires_at,
                    authenticated_at=now,
                    last_used_at=None,
                    revoked_at=None,
                    user_agent="pytest",
                    ip_address="127.0.0.1",
                )
            )

        async def rotate() -> str:
            async with transaction_scope(session_factory) as session:
                service = AuthService(
                    repository=SqlAlchemyIdentityRepository(session),
                    verification_store=UnavailableVerificationCodeStore(),
                    mailer=UnavailableVerificationMailer(),
                    password_manager=PasswordManager(),
                    token_manager=token_manager,
                    settings=settings,
                )
                try:
                    await service.refresh(refresh_token)
                    return "ok"
                except AppError as exc:
                    return exc.code

        results = await asyncio.gather(rotate(), rotate())
        assert sorted(results) == ["ok", "refresh_token_reused"]

        async with transaction_scope(session_factory) as session:
            total = await session.scalar(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.family_id == family_id)
            )
            active = await session.scalar(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.family_id == family_id, UserSession.revoked_at.is_(None))
            )
            assert total == 2
            assert active == 0
    finally:
        await engine.dispose()
