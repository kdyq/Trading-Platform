import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_account_service
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.security import PasswordManager, TokenManager
from app.main import create_app
from app.models.catalog import ProductStatus
from app.models.identity import PasswordResetToken
from app.repositories.identity import SqlAlchemyIdentityRepository
from app.services.account import AccountService
from tests.test_auth import (
    MemoryIdentityRepository,
    MemoryVerificationStore,
    RecordingMailer,
    auth_test_client,
    registration_payload,
    request_code,
)


def account_client() -> tuple[
    TestClient,
    MemoryIdentityRepository,
    RecordingMailer,
    PasswordManager,
]:
    client, repository, limiter, mailer = auth_test_client()
    app = cast(FastAPI, client.app)
    settings = cast(Settings, app.state.settings)
    assert settings.auth_secret_key is not None
    password_manager = PasswordManager()
    service = AccountService(
        repository=repository,
        request_limiter=limiter,
        mailer=mailer,
        password_manager=password_manager,
        token_manager=TokenManager(
            settings.auth_secret_key.get_secret_value(),
            access_minutes=settings.access_token_minutes,
            refresh_days=settings.refresh_token_days,
        ),
        settings=settings,
    )
    app.dependency_overrides[get_account_service] = lambda: service
    return client, repository, mailer, password_manager


def register(client: TestClient) -> tuple[str, str]:
    request_code(client)
    response = client.post("/api/v1/auth/register", json=registration_payload())
    assert response.status_code == 201
    return response.json()["access_token"], response.cookies["shiguang_refresh"]


def test_account_closure_redacts_identity_and_revokes_sessions() -> None:
    client, repository, _, _ = account_client()
    with client:
        access, refresh = register(client)
        headers = {"Authorization": f"Bearer {access}"}
        closed = client.delete("/api/v1/account/profile", headers=headers)
        assert closed.status_code == 200
        assert client.get("/api/v1/account/profile", headers=headers).status_code == 401
        client.cookies.set("shiguang_refresh", refresh, path="/api/v1/auth")
        assert client.post("/api/v1/auth/refresh").status_code == 401
    user = next(iter(repository.users.values()))
    assert user.login_email is None
    assert user.display_name == "已注销用户"
    assert user.deleted_at is not None


def test_password_reset_is_single_use_and_revokes_all_sessions() -> None:
    client, repository, mailer, password_manager = account_client()
    with client:
        _, old_refresh = register(client)
        requested = client.post(
            "/api/v1/account/password-reset-requests",
            json={"email": "Student@example.com"},
        )
        reset_url = mailer.reset_messages[0][1]
        token = parse_qs(urlparse(reset_url).query)["token"][0]
        reset = client.post(
            "/api/v1/account/password-resets",
            json={"token": token, "new_password": "newmarket2027"},
        )
        reused = client.post(
            "/api/v1/account/password-resets",
            json={"token": token, "new_password": "againmarket2028"},
        )
        client.cookies.set("shiguang_refresh", old_refresh, path="/api/v1/auth")
        revoked = client.post("/api/v1/auth/refresh")

    user = next(iter(repository.users.values()))
    assert requested.status_code == 202
    assert reset.status_code == 200
    assert reused.status_code == 422
    assert reused.json()["code"] == "password_reset_invalid"
    assert revoked.status_code == 401
    assert password_manager.verify(user.password_hash, "newmarket2027")


def test_unknown_password_reset_has_same_public_response() -> None:
    client, _, mailer, _ = account_client()
    with client:
        response = client.post(
            "/api/v1/account/password-reset-requests", json={"email": "missing@example.com"}
        )

    assert response.status_code == 202
    assert response.json() == {"message": "如果该账户存在，重置邮件将很快送达"}
    assert mailer.reset_messages == []


def test_new_delivered_reset_link_retires_the_previous_link() -> None:
    client, repository, mailer, _ = account_client()
    with client:
        register(client)
        first = client.post(
            "/api/v1/account/password-reset-requests",
            json={"email": "student@example.com"},
        )
        first_token = next(iter(repository.password_reset_tokens.values()))
        second = client.post(
            "/api/v1/account/password-reset-requests",
            json={"email": "student@example.com"},
        )

    assert first.status_code == second.status_code == 202
    assert len(mailer.reset_messages) == 2
    assert first_token.used_at is not None
    assert sum(token.used_at is None for token in repository.password_reset_tokens.values()) == 1


def test_password_change_requires_recent_auth_and_revokes_other_devices() -> None:
    client, repository, _, password_manager = account_client()
    with client:
        first_access, _ = register(client)
        second = client.post(
            "/api/v1/auth/login",
            json={"email": "student@example.com", "password": "market2026"},
        )
        second_access = second.json()["access_token"]
        changed = client.post(
            "/api/v1/account/password-change",
            headers={"Authorization": f"Bearer {second_access}"},
            json={"current_password": "market2026", "new_password": "securemarket2027"},
        )
        old_device = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {first_access}"}
        )
        current_device = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {second_access}"}
        )

    user = next(iter(repository.users.values()))
    assert changed.status_code == 200
    assert old_device.status_code == 401
    assert current_device.status_code == 200
    assert password_manager.verify(user.password_hash, "securemarket2027")


def test_profile_uses_real_counts_and_session_owner_boundary() -> None:
    client, repository, _, _ = account_client()
    with client:
        access, _ = register(client)
        headers = {"Authorization": f"Bearer {access}"}
        profile = client.get("/api/v1/account/profile", headers=headers)
        updated = client.patch(
            "/api/v1/account/profile", headers=headers, json={"display_name": "新昵称同学"}
        )
        missing = client.delete(
            "/api/v1/account/sessions/00000000-0000-0000-0000-000000000001",
            headers=headers,
        )

    assert profile.status_code == 200
    assert profile.json()["active_products"] == 0
    assert profile.json()["favorites"] == 0
    assert profile.json()["orders"] == 0
    assert profile.json()["has_avatar"] is False
    assert updated.json()["display_name"] == "新昵称同学"
    assert missing.status_code == 404
    assert missing.json()["code"] == "session_not_found"
    assert next(iter(repository.users.values())).display_name == "新昵称同学"


def test_expired_reset_token_is_rejected() -> None:
    client, repository, mailer, _ = account_client()
    with client:
        register(client)
        client.post(
            "/api/v1/account/password-reset-requests",
            json={"email": "student@example.com"},
        )
        reset_url = mailer.reset_messages[0][1]
        token = parse_qs(urlparse(reset_url).query)["token"][0]
        next(iter(repository.password_reset_tokens.values())).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        response = client.post(
            "/api/v1/account/password-resets",
            json={"token": token, "new_password": "newmarket2027"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "password_reset_invalid"


def test_mail_failure_does_not_destroy_previous_reset_token() -> None:
    class FailingMailer:
        async def send_password_reset(self, *, recipient: str, reset_url: str) -> None:
            raise AppError(
                status_code=503,
                code="email_delivery_failed",
                message="重置邮件暂时无法发送，请稍后重试",
            )

    repository = MemoryIdentityRepository()
    settings = Settings(
        database_url=None,
        redis_url=None,
        auth_secret_key="test-secret-key-that-is-longer-than-32-characters",
    )
    password_manager = PasswordManager()
    assert settings.auth_secret_key is not None
    token_manager = TokenManager(
        settings.auth_secret_key.get_secret_value(), access_minutes=15, refresh_days=30
    )
    app = create_app(settings)
    client = TestClient(app)
    service = AccountService(
        repository=repository,
        request_limiter=MemoryVerificationStore(),
        mailer=FailingMailer(),
        password_manager=password_manager,
        token_manager=token_manager,
        settings=settings,
    )
    app.dependency_overrides[get_account_service] = lambda: service

    # Reuse the normal registration stack, then point account recovery at the same repository.
    normal_client, normal_repository, _, _ = auth_test_client()
    with normal_client:
        register(normal_client)
    repository.users.update(normal_repository.users)

    user = next(iter(repository.users.values()))
    previous = PasswordResetToken(
        id=uuid4(),
        user_id=user.id,
        token_digest="previous",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        used_at=None,
    )
    repository.password_reset_tokens[previous.id] = previous
    with client:
        response = client.post(
            "/api/v1/account/password-reset-requests",
            json={"email": user.login_email},
        )

    assert response.status_code == 202
    assert response.json() == {"message": "如果该账户存在，重置邮件将很快送达"}
    assert list(repository.password_reset_tokens.values()) == [previous]


def test_active_product_count_filters_to_on_sale_status() -> None:
    session = AsyncMock()
    session.scalar.side_effect = [2, 0, 0, 0]
    repository = SqlAlchemyIdentityRepository(session)

    counts = asyncio.run(repository.profile_counts(uuid4()))

    product_statement = session.scalar.await_args_list[0].args[0]
    assert counts == (2, 0, 0, 0)
    assert ProductStatus.ON_SALE in product_statement.compile().params.values()
