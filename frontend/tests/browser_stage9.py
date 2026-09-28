"""Stage 9 real-browser admin navigation, RBAC, masking, and responsive smoke."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from playwright.sync_api import sync_playwright
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.core.security import TokenManager  # noqa: E402
from app.db.seed import seed_roles_and_permissions  # noqa: E402
from app.db.url import database_url_for_sqlalchemy  # noqa: E402
from scripts.postgres_gate import load_database_url  # noqa: E402

from browser_stage8 import BASE_URL, install_session

SUPER_ID = UUID("9a000000-0000-4000-8000-000000000001")
SUPPORT_ID = UUID("9a000000-0000-4000-8000-000000000002")
SUPER_SESSION = UUID("9a000000-0000-4000-8000-000000000011")
SUPPORT_SESSION = UUID("9a000000-0000-4000-8000-000000000012")


async def cleanup() -> None:
    engine = create_async_engine(database_url_for_sqlalchemy(load_database_url()))
    ids = [SUPER_ID, SUPPORT_ID]
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM audit_export_jobs WHERE actor_id = ANY(:ids)"), {"ids": ids})
            await connection.execute(text("DELETE FROM audit_logs WHERE actor_id = ANY(:ids)"), {"ids": ids})
            await connection.execute(text("DELETE FROM notifications WHERE user_id = ANY(:ids)"), {"ids": ids})
            await connection.execute(text("DELETE FROM user_roles WHERE user_id = ANY(:ids)"), {"ids": ids})
            await connection.execute(text("DELETE FROM user_sessions WHERE user_id = ANY(:ids)"), {"ids": ids})
            await connection.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
    finally:
        await engine.dispose()


async def prepare() -> tuple[dict[UUID, str], str]:
    settings = Settings()
    assert settings.auth_secret_key is not None
    engine = create_async_engine(database_url_for_sqlalchemy(load_database_url()))
    now = datetime.now(UTC)
    try:
        await cleanup()
        async with engine.begin() as connection:
            await seed_roles_and_permissions(connection)
            for user_id, session_id, role, email, name in (
                (SUPER_ID, SUPER_SESSION, "SUPER_ADMIN", "stage9-super@example.com", "阶段九管理员"),
                (SUPPORT_ID, SUPPORT_SESSION, "SUPPORT", "stage9-support@example.com", "阶段九客服"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users (id, login_email, username, password_hash, display_name, "
                        "login_email_verified_at, user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, NULL, 'browser-test-hash', :name, now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email, "name": name},
                )
                await connection.execute(
                    text(
                        "INSERT INTO user_sessions (id, user_id, family_id, refresh_token_digest, expires_at, authenticated_at) "
                        "VALUES (:id, :user, :id, :digest, :expires, :authenticated)"
                    ),
                    {
                        "id": session_id,
                        "user": user_id,
                        "digest": f"stage9-{user_id}",
                        "expires": now + timedelta(days=1),
                        "authenticated": now,
                    },
                )
                await connection.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) "
                        "SELECT :user, id FROM roles WHERE code = :role"
                    ),
                    {"user": user_id, "role": role},
                )
        manager = TokenManager(
            settings.auth_secret_key.get_secret_value(),
            access_minutes=settings.access_token_minutes,
            refresh_days=settings.refresh_token_days,
        )
        tokens = {
            SUPER_ID: manager.issue_access_token(
                user_id=SUPER_ID, session_id=SUPER_SESSION, authenticated_at=now
            )[0],
            SUPPORT_ID: manager.issue_access_token(
                user_id=SUPPORT_ID, session_id=SUPPORT_SESSION, authenticated_at=now
            )[0],
        }
        return tokens, (now + timedelta(minutes=settings.access_token_minutes)).isoformat()
    finally:
        await engine.dispose()


def run() -> None:
    tokens, expires = asyncio.run(prepare())
    screenshot_root = ROOT / "frontend" / ".tmp"
    screenshot_root.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            super_context = browser.new_context(viewport={"width": 1440, "height": 900})
            install_session(
                super_context,
                token=tokens[SUPER_ID], expires=expires, user_id=SUPER_ID,
                name="阶段九管理员", email="stage9-super@example.com",
            )
            page = super_context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(f"{BASE_URL}/admin/dashboard")
            page.wait_for_load_state("networkidle")
            page.get_by_role("heading", name="运营概览").wait_for()
            page.get_by_text("当前活跃会话").wait_for()
            page.screenshot(path=str(screenshot_root / "stage9-dashboard.png"), full_page=True)
            for label, heading in (
                ("后台人员", "后台人员"),
                ("用户管理", "用户管理"),
                ("商品管理", "商品管理"),
                ("校园复核", "校园认证复核"),
                ("分类与校区", "分类与校区"),
                ("审计日志", "审计日志"),
            ):
                page.get_by_role("link", name=label).click()
                page.wait_for_load_state("networkidle")
                page.get_by_role("heading", name=heading).wait_for()
                assert page.get_by_role("alert").count() == 0
            page.on("dialog", lambda dialog: dialog.accept())
            page.get_by_role("textbox", name="导出理由").fill("阶段九浏览器导出恢复测试")
            page.get_by_role("button", name="创建导出").click()
            page.get_by_text("导出已排队").wait_for()
            page.reload()
            page.get_by_role("heading", name="审计日志").wait_for()
            page.get_by_text("queued").first.wait_for()
            page.get_by_role("button", name="撤销访问").first.click()
            page.get_by_text("文件访问已撤销").wait_for()
            assert not page_errors, page_errors

            support_context = browser.new_context(viewport={"width": 375, "height": 812})
            install_session(
                support_context,
                token=tokens[SUPPORT_ID], expires=expires, user_id=SUPPORT_ID,
                name="阶段九客服", email="stage9-support@example.com",
            )
            support_page = support_context.new_page()
            support_page.goto(f"{BASE_URL}/admin/users")
            support_page.wait_for_load_state("networkidle")
            support_page.get_by_role("heading", name="用户管理").wait_for()
            assert support_page.get_by_role("link", name="后台人员").count() == 0
            support_page.get_by_text("s***@example.com").first.wait_for()
            assert support_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            response = support_context.request.get(
                f"http://127.0.0.1:8000/api/v1/admin/staff",
                headers={"Authorization": f"Bearer {tokens[SUPPORT_ID]}"},
            )
            assert response.status == 403
            support_page.screenshot(path=str(screenshot_root / "stage9-support-mobile.png"), full_page=True)
            browser.close()
    finally:
        asyncio.run(cleanup())
    print("STAGE9_BROWSER_OK")


if __name__ == "__main__":
    run()
