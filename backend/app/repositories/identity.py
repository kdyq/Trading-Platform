from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User, UserSession


class IdentityRepository(Protocol):
    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def create_user(self, user: User) -> User: ...

    async def create_session(self, session: UserSession) -> UserSession: ...

    async def get_session_by_digest(self, digest: str) -> UserSession | None: ...

    async def get_session(self, session_id: UUID) -> UserSession | None: ...

    async def revoke_session(self, session: UserSession, *, at: datetime) -> None: ...

    async def revoke_family(self, family_id: UUID, *, at: datetime) -> None: ...

    async def revoke_user_sessions(self, user_id: UUID, *, at: datetime) -> None: ...


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.login_email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_user(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def create_user(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def create_session(self, session: UserSession) -> UserSession:
        self._session.add(session)
        await self._session.flush()
        return session

    async def get_session_by_digest(self, digest: str) -> UserSession | None:
        result = await self._session.execute(
            select(UserSession).where(UserSession.refresh_token_digest == digest).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_session(self, session_id: UUID) -> UserSession | None:
        result = await self._session.execute(
            select(UserSession).where(UserSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def revoke_session(self, session: UserSession, *, at: datetime) -> None:
        session.revoked_at = at
        session.last_used_at = at
        await self._session.flush()

    async def revoke_family(self, family_id: UUID, *, at: datetime) -> None:
        await self._session.execute(
            update(UserSession)
            .where(UserSession.family_id == family_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=at, last_used_at=at)
        )

    async def revoke_user_sessions(self, user_id: UUID, *, at: datetime) -> None:
        await self._session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=at, last_used_at=at)
        )


def session_is_active(session: UserSession, *, now: datetime | None = None) -> bool:
    reference = now or datetime.now(UTC)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return session.revoked_at is None and expires_at > reference
