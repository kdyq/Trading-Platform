from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from secrets import token_urlsafe
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.exceptions import AppError

ALGORITHM = "HS256"


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    authenticated_at: datetime
    expires_at: datetime


class PasswordManager:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash("not-a-real-account-password-4937")

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerifyMismatchError):
            return False

    def verify_unknown(self, password: str) -> None:
        self.verify(self._dummy_hash, password)


class TokenManager:
    def __init__(self, secret: str, *, access_minutes: int, refresh_days: int) -> None:
        if len(secret) < 32:
            raise ValueError("AUTH_SECRET_KEY must contain at least 32 characters")
        self._secret = secret.encode()
        self._jwt_secret = secret
        self._access_minutes = access_minutes
        self._refresh_days = refresh_days

    def issue_access_token(
        self, *, user_id: UUID, session_id: UUID, authenticated_at: datetime
    ) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self._access_minutes)
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "sid": str(session_id),
            "auth_time": int(authenticated_at.timestamp()),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "type": "access",
        }
        return jwt.encode(payload, self._jwt_secret, algorithm=ALGORITHM), expires_at

    def decode_access_token(self, token: str) -> AccessClaims:
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[ALGORITHM])
            if payload.get("type") != "access":
                raise jwt.InvalidTokenError
            return AccessClaims(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                authenticated_at=datetime.fromtimestamp(payload["auth_time"], UTC),
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except (KeyError, TypeError, ValueError, jwt.InvalidTokenError) as exc:
            raise AppError(
                status_code=401, code="invalid_access_token", message="登录状态无效或已过期"
            ) from exc

    def issue_refresh_token(self) -> tuple[str, str, datetime]:
        token = token_urlsafe(48)
        return token, self.digest(token), datetime.now(UTC) + timedelta(days=self._refresh_days)

    def digest(self, token: str) -> str:
        return hmac_new(self._secret, token.encode(), sha256).hexdigest()

    def matches_digest(self, token: str, digest: str) -> bool:
        return compare_digest(self.digest(token), digest)


def validate_password(password: str, *, email: str) -> None:
    if not 8 <= len(password) <= 128:
        raise AppError(status_code=422, code="weak_password", message="密码长度必须为 8-128 位")
    if any(character.isspace() for character in password):
        raise AppError(status_code=422, code="weak_password", message="密码不能包含空白字符")
    if not any(character.isascii() and character.isalpha() for character in password):
        raise AppError(status_code=422, code="weak_password", message="密码必须包含英文字母")
    if not any(character.isdigit() for character in password):
        raise AppError(status_code=422, code="weak_password", message="密码必须包含数字")
    lowered = password.lower()
    common = {
        "12345678a",
        "1q2w3e4r",
        "abc12345",
        "admin1234",
        "iloveyou1",
        "letmein123",
        "passw0rd",
        "password1",
        "password123",
        "qwerty123",
        "welcome123",
    }
    weak_prefixes = (
        "123456",
        "abcdef",
        "admin",
        "dragon",
        "football",
        "iloveyou",
        "letmein",
        "monkey",
        "password",
        "princess",
        "qwerty",
        "summer",
        "sunshine",
        "welcome",
    )
    comparable_password = "".join(character for character in lowered if character.isalnum())
    email_local = "".join(
        character for character in email.partition("@")[0].lower() if character.isalnum()
    )
    resembles_email = len(email_local) >= 4 and (
        email_local in comparable_password
        or comparable_password in email_local
        or SequenceMatcher(None, comparable_password, email_local).ratio() >= 0.72
    )
    too_repetitive = len(set(comparable_password)) <= 3
    if (
        comparable_password in common
        or comparable_password.startswith(weak_prefixes)
        or too_repetitive
        or resembles_email
    ):
        raise AppError(status_code=422, code="weak_password", message="密码过于常见或接近邮箱")
