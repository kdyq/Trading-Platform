import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import insert, select

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import PasswordManager, TokenManager
from app.db.bootstrap_super_admin import bootstrap
from app.db.session import create_database_engine, create_session_factory, transaction_scope
from app.main import create_app
from app.models.admin import AuditExportJob
from app.models.identity import CampusVerificationStatus, Role, User, UserStatus, user_roles
from app.repositories.identity import SqlAlchemyIdentityRepository
from app.schemas.admin import AuditExportCreate, StaffRolesUpdate
from app.schemas.moderation import AppealReviewDecision, ProductModerationDecision
from app.services.account import AccountService
from app.services.admin import AdminService
from app.services.auth import AuthService
from app.services.email_verification import UnavailableVerificationCodeStore
from app.services.mailer import UnavailableAccountMailer, UnavailableVerificationMailer
from app.workers.audit_export import claim, process_job, prune_unavailable_files


def test_high_risk_reason_rejects_whitespace() -> None:
    with pytest.raises(ValidationError):
        StaffRolesUpdate.model_validate(
            {"roles": ["ADMIN"], "reason": "     ", "confirm_target": str(uuid4())}
        )
    with pytest.raises(ValidationError):
        AuditExportCreate.model_validate(
            {
                "starts_at": "2026-01-01T00:00:00Z",
                "ends_at": "2026-01-02T00:00:00Z",
                "reason": "     ",
            }
        )
    with pytest.raises(ValidationError):
        ProductModerationDecision.model_validate(
            {
                "action": "hide",
                "version": 1,
                "reason_code": "test",
                "public_note": "     ",
                "request_id": "stage9test",
            }
        )
    with pytest.raises(ValidationError):
        AppealReviewDecision.model_validate(
            {"action": "reverse", "reason": "     ", "request_id": "stage9test"}
        )


def test_bootstrap_permissions_and_staff_guards(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = os.getenv("DATABASE_URL")
    schema = os.getenv("DATABASE_SCHEMA")
    if not database_url or not schema:
        pytest.skip("PostgreSQL gate schema is required")
    changed_password, support_email, support_password = asyncio.run(_exercise(database_url, schema))
    app = create_app(
        Settings(
            database_url=database_url,
            auth_secret_key="stage-nine-secret-longer-than-thirty-two-characters",
            private_storage_root=tmp_path,
            environment="test",
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/staff").status_code == 401
        logged_in = client.post(
            "/api/v1/auth/login", json={"email": "guo", "password": changed_password}
        )
        assert logged_in.status_code == 200
        token = logged_in.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            "staff:manage" in client.get("/api/v1/admin/me", headers=headers).json()["permissions"]
        )
        assert client.get("/api/v1/admin/staff", headers=headers).status_code == 200
        assert (
            client.get("/api/v1/admin/users?page_size=1", headers=headers).json()["page_size"] == 1
        )
        assert client.get("/api/v1/admin/products", headers=headers).status_code == 200
        assert client.get("/api/v1/admin/categories", headers=headers).status_code == 200
        assert client.get("/api/v1/admin/campuses", headers=headers).status_code == 200
        assert client.get("/api/v1/admin/dashboard", headers=headers).status_code == 200
        assert client.get("/api/v1/admin/audit", headers=headers).status_code == 200
        assert (
            client.post(
                "/api/v1/admin/audit-exports",
                headers=headers,
                json={
                    "starts_at": "2026-01-01T00:00:00Z",
                    "ends_at": "2026-01-02T00:00:00Z",
                    "reason": "     ",
                },
            ).status_code
            == 422
        )
        support_login = client.post(
            "/api/v1/auth/login", json={"email": support_email, "password": support_password}
        )
        support_headers = {"Authorization": f"Bearer {support_login.json()['access_token']}"}
        assert client.get("/api/v1/admin/staff", headers=support_headers).status_code == 403
        users = client.get("/api/v1/admin/users", headers=support_headers)
        assert users.status_code == 200
        assert all("***@" in item["email"] for item in users.json()["items"])
        assert (
            client.get(
                f"/api/v1/admin/users?query={support_email}", headers=support_headers
            ).json()["total"]
            == 0
        )
        assert client.get("/api/v1/admin/audit", headers=support_headers).status_code == 403
        staff_rows = client.get("/api/v1/admin/staff", headers=headers).json()["items"]
        support_id = next(item["id"] for item in staff_rows if item["email"] == support_email)
        changed = client.put(
            f"/api/v1/admin/staff/{support_id}/roles",
            headers=headers,
            json={
                "roles": ["ADMIN"],
                "reason": "集成测试调整后台权限",
                "confirm_target": support_id,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["roles"] == ["ADMIN"]
        assert client.get("/api/v1/admin/users", headers=support_headers).status_code == 401
        support_login = client.post(
            "/api/v1/auth/login", json={"email": support_email, "password": support_password}
        )
        support_headers = {"Authorization": f"Bearer {support_login.json()['access_token']}"}
        assert client.get("/api/v1/admin/dashboard", headers=support_headers).status_code == 200
        assert client.get("/api/v1/admin/staff", headers=support_headers).status_code == 403
        disabled = client.patch(
            f"/api/v1/admin/staff/{support_id}/status",
            headers=headers,
            json={
                "status": "disabled",
                "reason": "集成测试停用后台人员",
                "confirm_target": support_id,
            },
        )
        assert disabled.status_code == 200
        assert client.get("/api/v1/admin/dashboard", headers=support_headers).status_code == 401
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": support_email, "password": support_password}
            ).status_code
            == 401
        )
        assert (
            client.patch(
                f"/api/v1/admin/staff/{support_id}/status",
                headers=headers,
                json={
                    "status": "active",
                    "reason": "集成测试恢复后台人员",
                    "confirm_target": support_id,
                },
            ).status_code
            == 200
        )
        support_login = client.post(
            "/api/v1/auth/login", json={"email": support_email, "password": support_password}
        )
        assert support_login.status_code == 200
        support_headers = {"Authorization": f"Bearer {support_login.json()['access_token']}"}
        self_id = logged_in.json()["user"]["id"]
        assert (
            client.put(
                f"/api/v1/admin/staff/{self_id}/roles",
                headers=headers,
                json={
                    "roles": ["ADMIN"],
                    "reason": "尝试移除唯一超级管理员",
                    "confirm_target": self_id,
                },
            ).status_code
            == 409
        )
        now = datetime.now(UTC)
        created = client.post(
            "/api/v1/admin/audit-exports",
            headers=headers,
            json={
                "starts_at": (now - timedelta(days=1)).isoformat(),
                "ends_at": now.isoformat(),
                "reason": "集成测试导出审计",
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]
        own_jobs = client.get("/api/v1/admin/audit-exports", headers=headers)
        assert own_jobs.status_code == 200
        assert any(item["id"] == job_id for item in own_jobs.json()["items"])
        assert client.get("/api/v1/admin/audit-exports", headers=support_headers).status_code == 403
        assert (
            client.get(
                f"/api/v1/admin/audit-exports/{job_id}/download", headers=headers
            ).status_code
            == 409
        )
        assert (
            client.get(f"/api/v1/admin/audit-exports/{job_id}", headers=support_headers).status_code
            == 403
        )
        asyncio.run(_process_export_once(database_url, schema, tmp_path))
        ready = client.get(f"/api/v1/admin/audit-exports/{job_id}", headers=headers)
        assert ready.json()["status"] == "ready"
        exported = client.get(f"/api/v1/admin/audit-exports/{job_id}/download", headers=headers)
        assert exported.status_code == 200
        assert b"exported_by" in exported.content
        assert (
            client.delete(f"/api/v1/admin/audit-exports/{job_id}", headers=headers).status_code
            == 200
        )
        assert (
            client.get(
                f"/api/v1/admin/audit-exports/{job_id}/download", headers=headers
            ).status_code
            == 410
        )
        asyncio.run(_suspend_user(database_url, schema, support_id))
        assert (
            client.patch(
                f"/api/v1/admin/staff/{support_id}/status",
                headers=headers,
                json={
                    "status": "active",
                    "reason": "不得绕过处罚暂停",
                    "confirm_target": support_id,
                },
            ).json()["code"]
            == "suspension_review_required"
        )
    get_settings.cache_clear()


async def _process_export_once(database_url: str, schema: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine = create_database_engine(database_url, schema=schema)
    factory = create_session_factory(engine)
    try:
        job_id = await claim(factory)
        assert job_id is not None
        assert await claim(factory) is None
        await process_job(factory, job_id, tmp_path)
        async with transaction_scope(factory) as session:
            actor = await session.scalar(select(User).where(User.username == "guo"))
            assert actor is not None
            stale = AuditExportJob(
                id=uuid4(),
                actor_id=actor.id,
                status="processing",
                filters={},
                object_key=None,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                revoked=False,
                failure_code=None,
                completed_at=None,
            )
            session.add(stale)
            await session.flush()
            stale.updated_at = datetime.now(UTC) - timedelta(minutes=11)
        await prune_unavailable_files(factory, tmp_path)
        async with transaction_scope(factory) as session:
            failed = await session.get(AuditExportJob, stale.id)
            assert failed is not None
            assert failed.status == "failed"
            assert failed.failure_code == "export_worker_lost"
    finally:
        await engine.dispose()


async def _suspend_user(database_url: str, schema: str, user_id) -> None:  # type: ignore[no-untyped-def]
    engine = create_database_engine(database_url, schema=schema)
    factory = create_session_factory(engine)
    try:
        async with transaction_scope(factory) as session:
            user = await session.get(User, user_id)
            assert user is not None
            user.status = UserStatus.SUSPENDED
    finally:
        await engine.dispose()


async def _exercise(database_url: str, schema: str) -> tuple[str, str, str]:
    settings = Settings(
        database_url=database_url,
        auth_secret_key="stage-nine-secret-longer-than-thirty-two-characters",
        environment="test",
    )
    password = f"Initial{uuid4().hex}9"
    email = f"stage9-{uuid4().hex}@example.com"
    await bootstrap(email, password)
    with pytest.raises(RuntimeError, match="already exists"):
        await bootstrap(email, "DifferentSecret9381")

    engine = create_database_engine(database_url, schema=schema)
    factory = create_session_factory(engine)
    assert settings.auth_secret_key is not None
    tokens = TokenManager(
        settings.auth_secret_key.get_secret_value(), access_minutes=15, refresh_days=30
    )
    changed_password = f"Changed{uuid4().hex}8"
    support_password = f"Support{uuid4().hex}8"
    support_email = ""
    try:
        async with transaction_scope(factory) as session:
            user = await session.scalar(select(User).where(User.username == "guo"))
            assert user is not None
            assert user.password_hash != password
            assert PasswordManager().verify(user.password_hash, password)
            assert user.must_change_password
            auth = AuthService(
                repository=SqlAlchemyIdentityRepository(session),
                verification_store=UnavailableVerificationCodeStore(),
                mailer=UnavailableVerificationMailer(),
                password_manager=PasswordManager(),
                token_manager=tokens,
                settings=settings,
            )
            logged_in = await auth.login(
                email="guo", password=password, user_agent="pytest", ip_address="127.0.0.1"
            )
            context = await auth.authenticate(logged_in.access_token)
            assert context.user.id == user.id
            admin = AdminService(session, settings)
            with pytest.raises(AppError) as forced:
                await admin.require(context, "staff:manage")
            assert forced.value.code == "password_change_required"
            account = AccountService(
                repository=SqlAlchemyIdentityRepository(session),
                request_limiter=UnavailableVerificationCodeStore(),
                mailer=UnavailableAccountMailer(),
                password_manager=PasswordManager(),
                token_manager=tokens,
                settings=settings,
            )
            await account.change_password(
                context=context,
                current_password=password,
                new_password=changed_password,
            )
            await admin.require(context, "staff:manage")
            assert not user.must_change_password

            for role_code, permissions in ROLE_PERMISSIONS.items():
                role = await session.scalar(select(Role).where(Role.code == role_code))
                assert role is not None
                other_email = f"role-{role_code.lower()}-{uuid4().hex}@example.com"
                other = User(
                    id=uuid4(),
                    login_email=other_email,
                    username=None,
                    password_hash=PasswordManager().hash(support_password)
                    if role_code == "SUPPORT"
                    else "unused",
                    display_name="权限测试用户",
                    status=UserStatus.ACTIVE,
                    last_login_at=None,
                    login_email_verified_at=datetime.now(UTC),
                    user_agreement_version="test",
                    privacy_policy_version="test",
                    terms_agreed_at=datetime.now(UTC),
                    avatar_key=None,
                )
                session.add(other)
                if role_code == "SUPPORT":
                    support_email = other_email
                await session.flush()
                await session.execute(insert(user_roles).values(user_id=other.id, role_id=role.id))
                from app.core.security import AccessClaims
                from app.models.identity import UserSession
                from app.services.auth import AuthContext

                checked = AuthContext(
                    user=other,
                    session=UserSession(
                        id=uuid4(),
                        user_id=other.id,
                        family_id=uuid4(),
                        refresh_token_digest="unused",
                        expires_at=datetime.now(UTC),
                        authenticated_at=datetime.now(UTC),
                        last_used_at=None,
                        revoked_at=None,
                        user_agent=None,
                        ip_address=None,
                    ),
                    claims=AccessClaims(other.id, uuid4(), datetime.now(UTC), datetime.now(UTC)),
                    campus_verification_status=CampusVerificationStatus.UNAPPLIED,
                )
                for permission in set().union(*ROLE_PERMISSIONS.values()):
                    try:
                        await admin.require(checked, permission)
                        allowed = True
                    except AppError as exc:
                        assert exc.code == "permission_denied"
                        allowed = False
                    assert allowed == (permission in permissions), (role_code, permission)
    finally:
        await engine.dispose()
    return changed_password, support_email, support_password
