from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies import get_auth_service
from app.core.config import Settings
from app.core.security import PasswordManager, TokenManager
from app.main import create_app
from app.models.identity import (
    CampusVerificationStatus,
    PasswordResetToken,
    User,
    UserSession,
    UserStatus,
)
from app.services.auth import AuthService


class MemoryIdentityRepository:
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.sessions: dict[UUID, UserSession] = {}
        self.password_reset_tokens: dict[UUID, PasswordResetToken] = {}

    async def get_user_by_email(self, email: str) -> User | None:
        return next((user for user in self.users.values() if user.login_email == email), None)

    async def get_user_by_username(self, username: str) -> User | None:
        return next((user for user in self.users.values() if user.username == username), None)

    async def get_user(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def create_user(self, user: User) -> User:
        self.users[user.id] = user
        return user

    async def create_session(self, session: UserSession) -> UserSession:
        self.sessions[session.id] = session
        return session

    async def get_session_by_digest(self, digest: str) -> UserSession | None:
        return next(
            (
                session
                for session in self.sessions.values()
                if session.refresh_token_digest == digest
            ),
            None,
        )

    async def get_session(self, session_id: UUID) -> UserSession | None:
        return self.sessions.get(session_id)

    async def revoke_session(self, session: UserSession, *, at: datetime) -> None:
        session.revoked_at = at
        session.last_used_at = at

    async def revoke_family(self, family_id: UUID, *, at: datetime) -> None:
        for session in self.sessions.values():
            if session.family_id == family_id and session.revoked_at is None:
                session.revoked_at = at

    async def revoke_user_sessions(self, user_id: UUID, *, at: datetime) -> None:
        for session in self.sessions.values():
            if session.user_id == user_id and session.revoked_at is None:
                session.revoked_at = at

    async def get_campus_verification_status(self, user_id: UUID) -> CampusVerificationStatus:
        return CampusVerificationStatus.UNAPPLIED

    async def get_business_campus_status(self, user_id: UUID) -> CampusVerificationStatus:
        return await self.get_campus_verification_status(user_id)

    async def update_user(self, user: User) -> None:
        self.users[user.id] = user

    async def profile_counts(self, user_id: UUID) -> tuple[int, int, int, int]:
        return 0, 0, 0, 0

    async def list_active_sessions(self, user_id: UUID) -> list[UserSession]:
        now = datetime.now(UTC)
        return [
            session
            for session in self.sessions.values()
            if session.user_id == user_id
            and session.revoked_at is None
            and session.expires_at > now
        ]

    async def revoke_other_sessions(
        self, user_id: UUID, current_session_id: UUID, *, at: datetime
    ) -> None:
        for session in self.sessions.values():
            if (
                session.user_id == user_id
                and session.id != current_session_id
                and session.revoked_at is None
            ):
                session.revoked_at = at

    async def create_password_reset_token(self, token: PasswordResetToken) -> PasswordResetToken:
        self.password_reset_tokens[token.id] = token
        return token

    async def get_password_reset_token(self, digest: str) -> PasswordResetToken | None:
        return next(
            (
                token
                for token in self.password_reset_tokens.values()
                if token.token_digest == digest
            ),
            None,
        )

    async def delete_password_reset_token(self, token: PasswordResetToken) -> None:
        self.password_reset_tokens.pop(token.id, None)

    async def prune_password_reset_tokens(self, user_id: UUID, *, at: datetime) -> None:
        self.password_reset_tokens = {
            token_id: token
            for token_id, token in self.password_reset_tokens.items()
            if token.user_id != user_id or (token.used_at is None and token.expires_at > at)
        }

    async def retire_other_password_reset_tokens(
        self, user_id: UUID, selected_id: UUID, *, at: datetime
    ) -> None:
        for token in self.password_reset_tokens.values():
            if token.user_id == user_id and token.id != selected_id and token.used_at is None:
                token.used_at = at

    async def consume_password_reset_tokens(self, user_id: UUID, *, at: datetime) -> None:
        for token in self.password_reset_tokens.values():
            if token.user_id == user_id and token.used_at is None:
                token.used_at = at


class MemoryVerificationStore:
    def __init__(self) -> None:
        self.codes: dict[tuple[str, str], str] = {}
        self.limits: list[tuple[str, str]] = []

    async def limit(self, *, subject: str, scope: str) -> None:
        self.limits.append((subject, scope))

    async def issue(self, *, email: str, purpose: str) -> str:
        self.codes[(email, purpose)] = "123456"
        return "123456"

    async def consume(self, *, email: str, purpose: str, code: str) -> None:
        from app.core.exceptions import AppError

        if self.codes.get((email, purpose)) != code:
            raise AppError(
                status_code=422, code="verification_invalid", message="验证码无效或已过期"
            )
        self.codes.pop((email, purpose))

    async def discard(self, *, email: str, purpose: str) -> None:
        self.codes.pop((email, purpose), None)


class RecordingMailer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.reset_messages: list[tuple[str, str]] = []

    async def send_verification_code(self, *, recipient: str, code: str) -> None:
        self.messages.append((recipient, code))

    async def send_password_reset(self, *, recipient: str, reset_url: str) -> None:
        self.reset_messages.append((recipient, reset_url))


def auth_test_client(
    *, environment: Literal["development", "test", "production"] = "test"
) -> tuple[TestClient, MemoryIdentityRepository, MemoryVerificationStore, RecordingMailer]:
    auth_secret = "test-secret-key-that-is-longer-than-32-characters"
    settings = Settings(
        database_url=None,
        redis_url=None,
        auth_secret_key=auth_secret,
        auth_verification_secret="test-verification-secret",
        environment=environment,
    )
    repository = MemoryIdentityRepository()
    codes = MemoryVerificationStore()
    mailer = RecordingMailer()
    service = AuthService(
        repository=repository,
        verification_store=codes,
        mailer=mailer,
        password_manager=PasswordManager(),
        token_manager=TokenManager(auth_secret, access_minutes=15, refresh_days=30),
        settings=settings,
    )
    app = create_app(settings)
    app.dependency_overrides[get_auth_service] = lambda: service
    return TestClient(app), repository, codes, mailer


def registration_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "email": "Student@example.com",
        "code": "123456",
        "display_name": "小橘同学",
        "password": "market2026",
        "accept_user_agreement": True,
        "accept_privacy_policy": True,
    }
    payload.update(overrides)
    return payload


def request_code(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/email-verifications",
        json={"email": "Student@example.com", "purpose": "registration"},
    )
    assert response.status_code == 202


def test_registration_verifies_email_and_sets_secure_session_cookie() -> None:
    client, repository, _, mailer = auth_test_client()
    with client:
        request_code(client)
        response = client.post("/api/v1/auth/register", json=registration_payload())

    assert response.status_code == 201
    assert response.json()["user"]["login_email"] == "student@example.com"
    assert response.json()["user"]["campus_verification_status"] == "unapplied"
    assert "shiguang_refresh=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert mailer.messages == [("student@example.com", "123456")]
    user = next(iter(repository.users.values()))
    assert user.password_hash != "market2026"
    assert user.login_email_verified_at is not None
    assert user.login_email_verified_at.tzinfo == UTC


def test_existing_email_receives_same_verification_request_flow() -> None:
    client, _, _, mailer = auth_test_client()
    with client:
        request_code(client)
        assert client.post("/api/v1/auth/register", json=registration_payload()).status_code == 201
        request_code(client)

    assert mailer.messages == [
        ("student@example.com", "123456"),
        ("student@example.com", "123456"),
    ]


def test_registration_rejects_weak_password_and_missing_agreement() -> None:
    client, _, _, _ = auth_test_client()
    with client:
        request_code(client)
        weak = client.post("/api/v1/auth/register", json=registration_payload(password="abcdefgh"))
        missing_agreement = client.post(
            "/api/v1/auth/register",
            json=registration_payload(accept_privacy_policy=False),
        )

    assert weak.status_code == 422
    assert weak.json()["code"] == "weak_password"
    assert missing_agreement.status_code == 422
    assert missing_agreement.json()["code"] == "agreements_required"


def test_registration_rejects_common_password_and_reserved_display_name() -> None:
    client, _, _, _ = auth_test_client()
    with client:
        request_code(client)
        common = client.post(
            "/api/v1/auth/register", json=registration_payload(password="Welcome123")
        )
        reserved = client.post(
            "/api/v1/auth/register", json=registration_payload(display_name="拾光集市客服")
        )

    assert common.status_code == 422
    assert common.json()["code"] == "weak_password"
    assert reserved.status_code == 422


def test_password_policy_rejects_common_sequences_and_repetition() -> None:
    from app.core.exceptions import AppError
    from app.core.security import validate_password

    for password in ("qwerty1234", "123456789a", "summer2026", "aaaaaaaa1"):
        try:
            validate_password(password, email="student@example.com")
        except AppError as exc:
            assert exc.code == "weak_password"
        else:
            raise AssertionError(f"common password was accepted: {password}")


def test_production_cookie_is_secure_and_untrusted_origin_is_rejected() -> None:
    client, _, _, _ = auth_test_client(environment="production")
    with client:
        request_code(client)
        registered = client.post("/api/v1/auth/register", json=registration_payload())
        client.cookies.set(
            "shiguang_refresh",
            registered.cookies["shiguang_refresh"],
            path="/api/v1/auth",
        )
        rejected = client.post(
            "/api/v1/auth/refresh",
            headers={"Origin": "https://hostile.example"},
        )

    assert "Secure" in registered.headers["set-cookie"]
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "untrusted_origin"


def test_login_does_not_enumerate_unknown_or_disabled_users() -> None:
    client, repository, _, _ = auth_test_client()
    with client:
        request_code(client)
        registered = client.post("/api/v1/auth/register", json=registration_payload())
        assert registered.status_code == 201
        user = next(iter(repository.users.values()))
        user.status = UserStatus.DISABLED
        disabled = client.post(
            "/api/v1/auth/login",
            json={"email": "student@example.com", "password": "market2026"},
        )
        unknown = client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "market2026"},
        )

    assert disabled.status_code == unknown.status_code == 401
    assert disabled.json()["code"] == unknown.json()["code"] == "invalid_credentials"
    assert disabled.json()["message"] == unknown.json()["message"]


def test_refresh_rotation_detects_replay_and_revokes_family() -> None:
    client, _, _, _ = auth_test_client()
    with client:
        request_code(client)
        registered = client.post("/api/v1/auth/register", json=registration_payload())
        old_refresh = registered.cookies["shiguang_refresh"]
        rotated = client.post("/api/v1/auth/refresh")
        assert rotated.status_code == 200
        new_refresh = rotated.cookies["shiguang_refresh"]

        client.cookies.set("shiguang_refresh", old_refresh, path="/api/v1/auth")
        replay = client.post("/api/v1/auth/refresh")
        client.cookies.set("shiguang_refresh", new_refresh, path="/api/v1/auth")
        family_revoked = client.post("/api/v1/auth/refresh")

    assert replay.status_code == 401
    assert replay.json()["code"] == "refresh_token_reused"
    assert family_revoked.status_code == 401


def test_logout_all_invalidates_existing_access_token() -> None:
    client, _, _, _ = auth_test_client()
    with client:
        request_code(client)
        registered = client.post("/api/v1/auth/register", json=registration_payload())
        access_token = registered.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout-all", headers=headers).status_code == 200
        invalidated = client.get("/api/v1/auth/me", headers=headers)

    assert invalidated.status_code == 401
    assert invalidated.json()["code"] == "invalid_access_token"
