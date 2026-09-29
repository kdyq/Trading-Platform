from datetime import UTC, datetime
from secrets import token_urlsafe
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.catalog import Favorite, Product, ProductStatus
from app.models.identity import (
    CampusAppealStatus,
    CampusVerification,
    CampusVerificationAppeal,
    CampusVerificationStatus,
    PasswordResetToken,
    Role,
    User,
    UserSession,
    UserStatus,
    user_roles,
)
from app.models.moderation import Report, ReportStatus
from app.models.trade import CreditLedger, Order, OrderStatus


class IdentityRepository(Protocol):
    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_user_by_username(self, username: str) -> User | None: ...

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def create_user(self, user: User) -> User: ...

    async def create_session(self, session: UserSession) -> UserSession: ...

    async def get_session_by_digest(self, digest: str) -> UserSession | None: ...

    async def get_session(self, session_id: UUID) -> UserSession | None: ...

    async def revoke_session(self, session: UserSession, *, at: datetime) -> None: ...

    async def revoke_family(self, family_id: UUID, *, at: datetime) -> None: ...

    async def revoke_user_sessions(self, user_id: UUID, *, at: datetime) -> None: ...

    async def get_campus_verification_status(self, user_id: UUID) -> CampusVerificationStatus: ...

    async def get_business_campus_status(self, user_id: UUID) -> CampusVerificationStatus: ...


class AccountRepository(IdentityRepository, Protocol):
    async def update_user(self, user: User) -> None: ...

    async def close_account(self, user_id: UUID, *, at: datetime) -> None: ...

    async def profile_counts(self, user_id: UUID) -> tuple[int, int, int, int]: ...

    async def list_active_sessions(self, user_id: UUID) -> list[UserSession]: ...

    async def revoke_other_sessions(
        self, user_id: UUID, current_session_id: UUID, *, at: datetime
    ) -> None: ...

    async def create_password_reset_token(
        self, token: PasswordResetToken
    ) -> PasswordResetToken: ...

    async def get_password_reset_token(self, digest: str) -> PasswordResetToken | None: ...

    async def delete_password_reset_token(self, token: PasswordResetToken) -> None: ...

    async def prune_password_reset_tokens(self, user_id: UUID, *, at: datetime) -> None: ...

    async def retire_other_password_reset_tokens(
        self, user_id: UUID, selected_id: UUID, *, at: datetime
    ) -> None: ...

    async def consume_password_reset_tokens(self, user_id: UUID, *, at: datetime) -> None: ...


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.login_email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.username == username, User.deleted_at.is_(None))
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

    async def get_campus_verification_status(self, user_id: UUID) -> CampusVerificationStatus:
        super_admin_role = await self._session.scalar(
            select(Role.id)
            .select_from(user_roles)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                user_roles.c.user_id == user_id,
                Role.code == "SUPER_ADMIN",
                Role.deleted_at.is_(None),
            )
            .limit(1)
        )
        if super_admin_role is not None:
            return CampusVerificationStatus.VERIFIED
        return await self.get_business_campus_status(user_id)

    async def get_business_campus_status(self, user_id: UUID) -> CampusVerificationStatus:
        verification_result = await self._session.execute(
            select(CampusVerification)
            .where(
                CampusVerification.user_id == user_id,
                CampusVerification.deleted_at.is_(None),
            )
            .order_by(CampusVerification.created_at.desc())
            .limit(1)
        )
        verification = verification_result.scalar_one_or_none()
        now = datetime.now(UTC)
        effective_status = (
            verification.status if verification is not None else CampusVerificationStatus.UNAPPLIED
        )
        if verification is not None and verification.status == CampusVerificationStatus.VERIFIED:
            expires_at = verification.expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at is not None and expires_at > now:
                return CampusVerificationStatus.VERIFIED
            await self._session.execute(
                update(CampusVerification)
                .where(
                    CampusVerification.id == verification.id,
                    CampusVerification.status == CampusVerificationStatus.VERIFIED,
                    CampusVerification.expires_at <= now,
                    CampusVerification.deleted_at.is_(None),
                )
                .values(
                    status=CampusVerificationStatus.EXPIRED,
                    version=CampusVerification.version + 1,
                )
            )
            effective_status = CampusVerificationStatus.EXPIRED

        appeal_result = await self._session.execute(
            select(CampusVerificationAppeal.id)
            .where(
                CampusVerificationAppeal.user_id == user_id,
                CampusVerificationAppeal.status == CampusAppealStatus.PENDING,
            )
            .limit(1)
        )
        if appeal_result.scalar_one_or_none() is not None:
            return CampusVerificationStatus.APPEALING
        return effective_status

    async def update_user(self, user: User) -> None:
        self._session.add(user)
        await self._session.flush()

    async def close_account(self, user_id: UUID, *, at: datetime) -> None:
        user = await self._session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.deleted_at is not None or user.status != UserStatus.ACTIVE:
            raise AppError(status_code=404, code="account_not_found", message="账号不存在")
        staff_role = await self._session.scalar(
            select(Role.id)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id, Role.code != "USER")
            .limit(1)
        )
        if staff_role is not None:
            raise AppError(
                status_code=409, code="staff_closure_requires_review", message="请先移交管理职责"
            )
        open_order = await self._session.scalar(
            select(Order.id)
            .where(
                or_(Order.buyer_id == user_id, Order.seller_id == user_id),
                Order.status.not_in(
                    (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.EXPIRED)
                ),
            )
            .limit(1)
        )
        open_report = await self._session.scalar(
            select(Report.id)
            .where(
                or_(Report.reporter_id == user_id, Report.subject_user_id == user_id),
                Report.status.in_(
                    (ReportStatus.OPEN, ReportStatus.REVIEWING, ReportStatus.APPEALED)
                ),
            )
            .limit(1)
        )
        pending_appeal = await self._session.scalar(
            select(CampusVerificationAppeal.id)
            .where(
                CampusVerificationAppeal.user_id == user_id,
                CampusVerificationAppeal.status == CampusAppealStatus.PENDING,
            )
            .limit(1)
        )
        if open_order is not None or open_report is not None or pending_appeal is not None:
            raise AppError(
                status_code=409, code="account_has_open_cases", message="请先处理未完成事项"
            )
        await self._session.execute(
            update(Product)
            .where(Product.seller_id == user_id, Product.deleted_at.is_(None))
            .values(status=ProductStatus.DELETED, deleted_at=at)
        )
        await self._session.execute(
            update(Order)
            .where(Order.buyer_id == user_id)
            .values(buyer_display_name_snapshot="已注销用户")
        )
        await self._session.execute(
            update(Order)
            .where(Order.seller_id == user_id)
            .values(seller_display_name_snapshot="已注销用户")
        )
        await self._session.execute(
            update(CampusVerification)
            .where(CampusVerification.user_id == user_id)
            .values(
                campus_email=f"closed-{user_id.hex}@invalid.example",
                status=CampusVerificationStatus.EXPIRED,
                deleted_at=at,
            )
        )
        await self._session.execute(
            update(CampusVerificationAppeal)
            .where(CampusVerificationAppeal.user_id == user_id)
            .values(retention_until=at)
        )
        await self._session.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id)
            .values(revoked_at=at, user_agent=None, ip_address=None)
        )
        await self._session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id)
        )
        user.login_email = None
        user.login_email_verified_at = None
        user.username = f"closed_{user_id.hex[:24]}"
        user.display_name = "已注销用户"
        user.password_hash = token_urlsafe(48)
        user.last_login_at = None
        user.avatar_key = None
        user.status = UserStatus.DISABLED
        user.deleted_at = at
        await self._session.flush()

    async def profile_counts(self, user_id: UUID) -> tuple[int, int, int, int]:
        product_count = await self._session.scalar(
            select(func.count())
            .select_from(Product)
            .where(
                Product.seller_id == user_id,
                Product.status == ProductStatus.ON_SALE,
                Product.deleted_at.is_(None),
            )
        )
        favorite_count = await self._session.scalar(
            select(func.count()).select_from(Favorite).where(Favorite.user_id == user_id)
        )
        order_count = await self._session.scalar(
            select(func.count())
            .select_from(Order)
            .where(or_(Order.buyer_id == user_id, Order.seller_id == user_id))
        )
        credit_event_count = await self._session.scalar(
            select(func.count()).select_from(CreditLedger).where(CreditLedger.user_id == user_id)
        )
        return (
            int(product_count or 0),
            int(favorite_count or 0),
            int(order_count or 0),
            int(credit_event_count or 0),
        )

    async def list_active_sessions(self, user_id: UUID) -> list[UserSession]:
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
        )
        return list(result.scalars())

    async def revoke_other_sessions(
        self, user_id: UUID, current_session_id: UUID, *, at: datetime
    ) -> None:
        await self._session.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.id != current_session_id,
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=at, last_used_at=at)
        )

    async def create_password_reset_token(self, token: PasswordResetToken) -> PasswordResetToken:
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_password_reset_token(self, digest: str) -> PasswordResetToken | None:
        result = await self._session.execute(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_digest == digest)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def delete_password_reset_token(self, token: PasswordResetToken) -> None:
        await self._session.delete(token)
        await self._session.flush()

    async def prune_password_reset_tokens(self, user_id: UUID, *, at: datetime) -> None:
        await self._session.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.user_id == user_id,
                or_(
                    PasswordResetToken.used_at.is_not(None),
                    PasswordResetToken.expires_at <= at,
                ),
            )
        )

    async def retire_other_password_reset_tokens(
        self, user_id: UUID, selected_id: UUID, *, at: datetime
    ) -> None:
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.id != selected_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=at)
        )

    async def consume_password_reset_tokens(self, user_id: UUID, *, at: datetime) -> None:
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=at)
        )


def session_is_active(session: UserSession, *, now: datetime | None = None) -> bool:
    reference = now or datetime.now(UTC)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return session.revoked_at is None and expires_at > reference
