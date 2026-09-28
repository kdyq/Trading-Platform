from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import AccessClaims, PasswordManager, TokenManager, validate_password
from app.models.identity import CampusVerificationStatus, User, UserSession, UserStatus
from app.repositories.identity import IdentityRepository, session_is_active
from app.services.email_verification import VerificationCodeStore
from app.services.mailer import VerificationMailer


@dataclass(frozen=True)
class AuthResult:
    user: User
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    campus_verification_status: CampusVerificationStatus


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: UserSession
    claims: AccessClaims
    campus_verification_status: CampusVerificationStatus


class AuthService:
    def __init__(
        self,
        *,
        repository: IdentityRepository,
        verification_store: VerificationCodeStore,
        mailer: VerificationMailer,
        password_manager: PasswordManager,
        token_manager: TokenManager,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._verification_store = verification_store
        self._mailer = mailer
        self._password_manager = password_manager
        self._token_manager = token_manager
        self._settings = settings

    async def request_registration_code(self, email: str) -> None:
        normalized_email = normalize_email(email)
        code = await self._verification_store.issue(email=normalized_email, purpose="registration")
        try:
            await self._mailer.send_verification_code(recipient=normalized_email, code=code)
        except AppError:
            await self._verification_store.discard(email=normalized_email, purpose="registration")
            raise

    async def register(
        self,
        *,
        email: str,
        code: str,
        display_name: str,
        password: str,
        accept_user_agreement: bool,
        accept_privacy_policy: bool,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuthResult:
        if not self._settings.registration_enabled:
            raise AppError(status_code=403, code="registration_closed", message="当前暂未开放注册")
        if not accept_user_agreement or not accept_privacy_policy:
            raise AppError(
                status_code=422,
                code="agreements_required",
                message="请分别同意用户协议和隐私政策",
            )
        normalized_email = normalize_email(email)
        validate_password(password, email=normalized_email)
        await self._verification_store.consume(
            email=normalized_email, purpose="registration", code=code
        )
        if await self._repository.get_user_by_email(normalized_email) is not None:
            raise AppError(status_code=409, code="email_already_registered", message="该邮箱已注册")
        now = datetime.now(UTC)
        user = User(
            id=uuid4(),
            login_email=normalized_email,
            password_hash=self._password_manager.hash(password),
            display_name=display_name,
            status=UserStatus.ACTIVE,
            last_login_at=now,
            login_email_verified_at=now,
            user_agreement_version=self._settings.user_agreement_version,
            privacy_policy_version=self._settings.privacy_policy_version,
            terms_agreed_at=now,
            avatar_key=None,
        )
        try:
            await self._repository.create_user(user)
        except IntegrityError as exc:
            raise AppError(
                status_code=409, code="email_already_registered", message="该邮箱已注册"
            ) from exc
        return await self._new_session(
            user=user, authenticated_at=now, user_agent=user_agent, ip_address=ip_address
        )

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuthResult:
        login = normalize_email(email)
        user = (
            await self._repository.get_user_by_email(login)
            if "@" in login
            else await self._repository.get_user_by_username(login)
        )
        if user is None:
            self._password_manager.verify_unknown(password)
            raise invalid_credentials()
        if not self._password_manager.verify(user.password_hash, password):
            raise invalid_credentials()
        if user.status != UserStatus.ACTIVE:
            raise invalid_credentials()
        now = datetime.now(UTC)
        user.last_login_at = now
        return await self._new_session(
            user=user, authenticated_at=now, user_agent=user_agent, ip_address=ip_address
        )

    async def refresh(self, refresh_token: str) -> AuthResult:
        digest = self._token_manager.digest(refresh_token)
        current = await self._repository.get_session_by_digest(digest)
        if current is None:
            raise invalid_refresh_token()
        now = datetime.now(UTC)
        if current.revoked_at is not None:
            await self._repository.revoke_family(current.family_id, at=now)
            raise AppError(
                status_code=401,
                code="refresh_token_reused",
                message="登录状态存在风险，请重新登录",
            )
        if not session_is_active(current, now=now):
            await self._repository.revoke_session(current, at=now)
            raise invalid_refresh_token()
        user = await self._repository.get_user(current.user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            await self._repository.revoke_family(current.family_id, at=now)
            raise invalid_refresh_token()

        await self._repository.revoke_session(current, at=now)
        refresh, refresh_digest, refresh_expires_at = self._token_manager.issue_refresh_token()
        successor = UserSession(
            id=uuid4(),
            user_id=user.id,
            family_id=current.family_id,
            refresh_token_digest=refresh_digest,
            expires_at=refresh_expires_at,
            authenticated_at=current.authenticated_at,
            last_used_at=None,
            revoked_at=None,
            user_agent=current.user_agent,
            ip_address=current.ip_address,
        )
        await self._repository.create_session(successor)
        access, access_expires_at = self._token_manager.issue_access_token(
            user_id=user.id,
            session_id=successor.id,
            authenticated_at=current.authenticated_at,
        )
        campus_status = await self._repository.get_campus_verification_status(user.id)
        return AuthResult(user, access, access_expires_at, refresh, campus_status)

    async def authenticate(self, access_token: str) -> AuthContext:
        claims = self._token_manager.decode_access_token(access_token)
        session = await self._repository.get_session(claims.session_id)
        user = await self._repository.get_user(claims.user_id)
        if (
            session is None
            or user is None
            or session.user_id != user.id
            or not session_is_active(session)
            or user.status != UserStatus.ACTIVE
        ):
            raise AppError(
                status_code=401, code="invalid_access_token", message="登录状态无效或已过期"
            )
        campus_status = await self._repository.get_campus_verification_status(user.id)
        return AuthContext(
            user=user,
            session=session,
            claims=claims,
            campus_verification_status=campus_status,
        )

    async def logout(self, refresh_token: str) -> None:
        session = await self._repository.get_session_by_digest(
            self._token_manager.digest(refresh_token)
        )
        if session is not None and session.revoked_at is None:
            await self._repository.revoke_session(session, at=datetime.now(UTC))

    async def logout_all(self, user_id: UUID) -> None:
        await self._repository.revoke_user_sessions(user_id, at=datetime.now(UTC))

    async def _new_session(
        self,
        *,
        user: User,
        authenticated_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuthResult:
        refresh, refresh_digest, refresh_expires_at = self._token_manager.issue_refresh_token()
        session = UserSession(
            id=uuid4(),
            user_id=user.id,
            family_id=uuid4(),
            refresh_token_digest=refresh_digest,
            expires_at=refresh_expires_at,
            authenticated_at=authenticated_at,
            last_used_at=None,
            revoked_at=None,
            user_agent=user_agent[:512] if user_agent else None,
            ip_address=ip_address[:64] if ip_address else None,
        )
        await self._repository.create_session(session)
        access, access_expires_at = self._token_manager.issue_access_token(
            user_id=user.id,
            session_id=session.id,
            authenticated_at=authenticated_at,
        )
        campus_status = await self._repository.get_campus_verification_status(user.id)
        return AuthResult(user, access, access_expires_at, refresh, campus_status)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def invalid_credentials() -> AppError:
    return AppError(status_code=401, code="invalid_credentials", message="邮箱或密码不正确")


def invalid_refresh_token() -> AppError:
    return AppError(status_code=401, code="invalid_refresh_token", message="登录状态无效或已过期")
