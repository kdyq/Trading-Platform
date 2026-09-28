from collections.abc import Callable
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import (
    Campus,
    CampusAppealStatus,
    CampusVerification,
    CampusVerificationAppeal,
    CampusVerificationStatus,
    Permission,
    Role,
    School,
    SchoolEmailDomain,
    User,
    role_permissions,
    user_roles,
)


class CampusRepository(Protocol):
    def register_rollback_callback(self, callback: Callable[[], None]) -> None: ...

    async def lock_user(self, user_id: UUID) -> None: ...

    async def list_schools(self) -> list[School]: ...

    async def get_school(self, school_id: UUID) -> School | None: ...

    async def get_campus(self, campus_id: UUID) -> Campus | None: ...

    async def list_email_domains(self, school_id: UUID) -> list[SchoolEmailDomain]: ...

    async def latest_verification(
        self, user_id: UUID, *, for_update: bool = False
    ) -> CampusVerification | None: ...

    async def verification_for_user(
        self, verification_id: UUID, user_id: UUID, *, for_update: bool = False
    ) -> CampusVerification | None: ...

    async def retire_pending_verifications(self, user_id: UUID, *, at: datetime) -> None: ...

    async def expire_verification(self, verification_id: UUID, *, at: datetime) -> None: ...

    async def expire_email_verifications(self, campus_email: str, *, at: datetime) -> None: ...

    async def create_verification(self, verification: CampusVerification) -> CampusVerification: ...

    async def save_verification(self, verification: CampusVerification) -> None: ...

    async def pending_appeal(self, user_id: UUID) -> CampusVerificationAppeal | None: ...

    async def create_appeal(self, appeal: CampusVerificationAppeal) -> CampusVerificationAppeal: ...

    async def get_appeal(self, appeal_id: UUID) -> CampusVerificationAppeal | None: ...

    async def has_permission(self, user_id: UUID, permission_code: str) -> bool: ...


class SqlAlchemyCampusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def register_rollback_callback(self, callback: Callable[[], None]) -> None:
        callbacks = cast(
            list[Callable[[], None]],
            self._session.info.setdefault("rollback_callbacks", []),
        )
        callbacks.append(callback)

    async def lock_user(self, user_id: UUID) -> None:
        await self._session.execute(select(User.id).where(User.id == user_id).with_for_update())

    async def list_schools(self) -> list[School]:
        result = await self._session.execute(
            select(School)
            .where(School.is_active.is_(True), School.deleted_at.is_(None))
            .options(selectinload(School.campuses), selectinload(School.email_domains))
            .order_by(School.name)
        )
        return list(result.scalars().unique())

    async def get_school(self, school_id: UUID) -> School | None:
        result = await self._session.execute(
            select(School).where(
                School.id == school_id,
                School.is_active.is_(True),
                School.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_campus(self, campus_id: UUID) -> Campus | None:
        result = await self._session.execute(
            select(Campus).where(
                Campus.id == campus_id,
                Campus.is_active.is_(True),
                Campus.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_email_domains(self, school_id: UUID) -> list[SchoolEmailDomain]:
        result = await self._session.execute(
            select(SchoolEmailDomain).where(
                SchoolEmailDomain.school_id == school_id,
                SchoolEmailDomain.is_active.is_(True),
            )
        )
        return list(result.scalars())

    async def latest_verification(
        self, user_id: UUID, *, for_update: bool = False
    ) -> CampusVerification | None:
        statement = (
            select(CampusVerification)
            .where(
                CampusVerification.user_id == user_id,
                CampusVerification.deleted_at.is_(None),
            )
            .order_by(CampusVerification.created_at.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def verification_for_user(
        self, verification_id: UUID, user_id: UUID, *, for_update: bool = False
    ) -> CampusVerification | None:
        statement = select(CampusVerification).where(
            CampusVerification.id == verification_id,
            CampusVerification.user_id == user_id,
            CampusVerification.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def retire_pending_verifications(self, user_id: UUID, *, at: datetime) -> None:
        await self._session.execute(
            update(CampusVerification)
            .where(
                CampusVerification.user_id == user_id,
                CampusVerification.status == CampusVerificationStatus.PENDING,
                CampusVerification.deleted_at.is_(None),
            )
            .values(deleted_at=at)
        )

    async def expire_verification(self, verification_id: UUID, *, at: datetime) -> None:
        await self._session.execute(
            update(CampusVerification)
            .where(
                CampusVerification.id == verification_id,
                CampusVerification.status == CampusVerificationStatus.VERIFIED,
                CampusVerification.expires_at <= at,
                CampusVerification.deleted_at.is_(None),
            )
            .values(
                status=CampusVerificationStatus.EXPIRED,
                version=CampusVerification.version + 1,
            )
        )

    async def expire_email_verifications(self, campus_email: str, *, at: datetime) -> None:
        await self._session.execute(
            update(CampusVerification)
            .where(
                CampusVerification.campus_email == campus_email,
                CampusVerification.status == CampusVerificationStatus.VERIFIED,
                CampusVerification.expires_at <= at,
                CampusVerification.deleted_at.is_(None),
            )
            .values(
                status=CampusVerificationStatus.EXPIRED,
                version=CampusVerification.version + 1,
            )
        )

    async def create_verification(self, verification: CampusVerification) -> CampusVerification:
        self._session.add(verification)
        await self._session.flush()
        return verification

    async def save_verification(self, verification: CampusVerification) -> None:
        self._session.add(verification)
        await self._session.flush()

    async def pending_appeal(self, user_id: UUID) -> CampusVerificationAppeal | None:
        result = await self._session.execute(
            select(CampusVerificationAppeal).where(
                CampusVerificationAppeal.user_id == user_id,
                CampusVerificationAppeal.status == CampusAppealStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def create_appeal(self, appeal: CampusVerificationAppeal) -> CampusVerificationAppeal:
        self._session.add(appeal)
        await self._session.flush()
        return appeal

    async def get_appeal(self, appeal_id: UUID) -> CampusVerificationAppeal | None:
        result = await self._session.execute(
            select(CampusVerificationAppeal).where(CampusVerificationAppeal.id == appeal_id)
        )
        return result.scalar_one_or_none()

    async def has_permission(self, user_id: UUID, permission_code: str) -> bool:
        result = await self._session.execute(
            select(Permission.id)
            .select_from(user_roles)
            .join(Role, Role.id == user_roles.c.role_id)
            .join(role_permissions, role_permissions.c.role_id == Role.id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .join(User, User.id == user_roles.c.user_id)
            .where(
                user_roles.c.user_id == user_id,
                Role.deleted_at.is_(None),
                User.must_change_password.is_(False),
                Permission.code == permission_code,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
