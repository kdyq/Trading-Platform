import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import PasswordManager, TokenManager, validate_password
from app.models.identity import PasswordResetToken, User, UserSession, UserStatus
from app.repositories.identity import AccountRepository, session_is_active
from app.services.auth import AuthContext, normalize_email
from app.services.email_verification import VerificationCodeStore
from app.services.mailer import AccountMailer

logger = logging.getLogger(__name__)


class AccountService:
    def __init__(
        self,
        *,
        repository: AccountRepository,
        request_limiter: VerificationCodeStore,
        mailer: AccountMailer,
        password_manager: PasswordManager,
        token_manager: TokenManager,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._request_limiter = request_limiter
        self._mailer = mailer
        self._password_manager = password_manager
        self._token_manager = token_manager
        self._settings = settings

    async def request_password_reset(self, email: str, *, ip_address: str | None) -> None:
        normalized_email = normalize_email(email)
        await self._request_limiter.issue(
            email=normalized_email, purpose="password-reset-email"
        )
        try:
            await self._request_limiter.issue(
                email=ip_address or "unknown", purpose="password-reset-ip"
            )
        except AppError:
            await self._request_limiter.discard(
                email=normalized_email, purpose="password-reset-email"
            )
            raise
        user = await self._repository.get_user_by_email(normalized_email)
        if user is None or user.status != UserStatus.ACTIVE:
            self._password_manager.verify_unknown("password-reset-timing-probe")
            return
        raw_token, digest, expires_at = self._token_manager.issue_single_use_token(
            minutes=self._settings.password_reset_minutes
        )
        token = PasswordResetToken(
            id=uuid4(),
            user_id=user.id,
            token_digest=digest,
            expires_at=expires_at,
            used_at=None,
        )
        await self._repository.prune_password_reset_tokens(user.id, at=datetime.now(UTC))
        await self._repository.create_password_reset_token(token)
        query = urlencode({"token": raw_token})
        reset_url = f"{self._settings.frontend_public_url.rstrip('/')}/forgot-password?{query}"
        try:
            await self._mailer.send_password_reset(
                recipient=user.login_email, reset_url=reset_url
            )
        except AppError as exc:
            await self._repository.delete_password_reset_token(token)
            logger.warning("password_reset_email_delivery_failed", extra={"error_code": exc.code})
            return
        await self._repository.retire_other_password_reset_tokens(
            user.id, token.id, at=datetime.now(UTC)
        )

    async def reset_password(self, *, token: str, new_password: str) -> None:
        digest = self._token_manager.digest(token)
        record = await self._repository.get_password_reset_token(digest)
        now = datetime.now(UTC)
        if record is None or record.used_at is not None or not _future(record.expires_at, now):
            raise AppError(
                status_code=422,
                code="password_reset_invalid",
                message="重置链接无效或已过期",
            )
        user = await self._repository.get_user(record.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise AppError(
                status_code=422,
                code="password_reset_invalid",
                message="重置链接无效或已过期",
            )
        validate_password(new_password, email=user.login_email)
        user.password_hash = self._password_manager.hash(new_password)
        await self._repository.update_user(user)
        await self._repository.consume_password_reset_tokens(user.id, at=now)
        await self._repository.revoke_user_sessions(user.id, at=now)

    async def change_password(
        self, *, context: AuthContext, current_password: str, new_password: str
    ) -> None:
        self.require_recent_auth(context)
        if not self._password_manager.verify(context.user.password_hash, current_password):
            raise AppError(
                status_code=422,
                code="current_password_invalid",
                message="当前密码不正确",
            )
        validate_password(new_password, email=context.user.login_email)
        context.user.password_hash = self._password_manager.hash(new_password)
        await self._repository.update_user(context.user)
        await self._repository.revoke_other_sessions(
            context.user.id, context.session.id, at=datetime.now(UTC)
        )

    async def update_profile(self, *, user: User, display_name: str) -> User:
        user.display_name = display_name
        await self._repository.update_user(user)
        return user

    async def profile_counts(self, user_id: UUID) -> tuple[int, int, int, int]:
        return await self._repository.profile_counts(user_id)

    async def sessions(self, user_id: UUID) -> list[UserSession]:
        return await self._repository.list_active_sessions(user_id)

    async def revoke_session(self, *, context: AuthContext, session_id: UUID) -> None:
        self.require_recent_auth(context)
        session = await self._repository.get_session(session_id)
        if session is None or session.user_id != context.user.id or not session_is_active(session):
            raise AppError(status_code=404, code="session_not_found", message="未找到该会话")
        await self._repository.revoke_session(session, at=datetime.now(UTC))

    def require_recent_auth(self, context: AuthContext) -> None:
        threshold = datetime.now(UTC) - timedelta(minutes=self._settings.recent_auth_minutes)
        authenticated_at = context.claims.authenticated_at
        if authenticated_at.tzinfo is None:
            authenticated_at = authenticated_at.replace(tzinfo=UTC)
        if authenticated_at < threshold:
            raise AppError(
                status_code=403,
                code="recent_authentication_required",
                message="请重新登录后再执行此操作",
            )


def _future(value: datetime, reference: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value > reference
