"""Stage 7 two-context order, meeting, completion and review browser gate."""

import asyncio
import os
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from playwright.sync_api import BrowserContext, Route, sync_playwright
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.core.security import TokenManager  # noqa: E402
from browser_db import browser_engine  # noqa: E402

BASE_URL = "http://127.0.0.1:5173"
OUTPUT = ROOT / "frontend" / ".tmp"
SELLER_ID = UUID("7a000000-0000-4000-8000-000000000001")
BUYER_ID = UUID("7a000000-0000-4000-8000-000000000002")
SELLER_SESSION_ID = UUID("7a000000-0000-4000-8000-000000000011")
BUYER_SESSION_ID = UUID("7a000000-0000-4000-8000-000000000012")
SCHOOL_ID = UUID("7a000000-0000-4000-8000-000000000021")
CAMPUS_ID = UUID("7a000000-0000-4000-8000-000000000022")
CATEGORY_ID = UUID("7a000000-0000-4000-8000-000000000023")
PRODUCT_ID = UUID("7a000000-0000-4000-8000-000000000024")


async def clean(connection) -> None:  # type: ignore[no-untyped-def]
    values = {
        "seller": SELLER_ID,
        "buyer": BUYER_ID,
        "product": PRODUCT_ID,
        "category": CATEGORY_ID,
        "campus": CAMPUS_ID,
        "school": SCHOOL_ID,
    }
    statements = (
        "DELETE FROM notification_delivery_attempts WHERE notification_id IN "
        "(SELECT id FROM notifications WHERE user_id IN (:seller, :buyer))",
        "DELETE FROM notifications WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM reports WHERE target_type = 'order' AND target_id IN "
        "(SELECT id FROM orders WHERE product_id = :product)",
        "DELETE FROM reviews WHERE order_id IN (SELECT id FROM orders WHERE product_id = :product)",
        "DELETE FROM order_commands WHERE order_id IN "
        "(SELECT id FROM orders WHERE product_id = :product)",
        "DELETE FROM order_meeting_proposals WHERE order_id IN "
        "(SELECT id FROM orders WHERE product_id = :product)",
        "DELETE FROM order_events WHERE order_id IN "
        "(SELECT id FROM orders WHERE product_id = :product)",
        "DELETE FROM orders WHERE product_id = :product",
        "DELETE FROM favorites WHERE product_id = :product",
        "DELETE FROM products WHERE id = :product",
        "DELETE FROM campus_verifications WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM user_sessions WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM users WHERE id IN (:seller, :buyer)",
        "DELETE FROM categories WHERE id = :category",
        "DELETE FROM campuses WHERE id = :campus",
        "DELETE FROM schools WHERE id = :school",
    )
    for statement in statements:
        await connection.execute(text(statement), values)


async def prepare() -> tuple[str, str, str]:
    settings = Settings()
    assert settings.database_url and settings.auth_secret_key
    engine = browser_engine(settings.database_url)
    now = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await clean(connection)
            await connection.execute(
                text(
                    "INSERT INTO schools (id, code, name) VALUES (:id, 'STAGE7', '阶段七测试大学')"
                ),
                {"id": SCHOOL_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'STAGE7', '阶段七校区')"
                ),
                {"id": CAMPUS_ID, "school": SCHOOL_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO categories (id, code, slug, name) "
                    "VALUES (:id, 'stage7', 'stage7', '阶段七测试')"
                ),
                {"id": CATEGORY_ID},
            )
            for user_id, email, name in (
                (SELLER_ID, "stage7-seller@example.com", "阶段七卖家"),
                (BUYER_ID, "stage7-buyer@example.com", "阶段七买家"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, login_email, password_hash, display_name, login_email_verified_at, "
                        "user_agreement_version, privacy_policy_version, terms_agreed_at) "
                        "VALUES (:id, :email, 'browser-test-hash', :name, now(), 'test', 'test', now())"
                    ),
                    {"id": user_id, "email": email, "name": name},
                )
                await connection.execute(
                    text(
                        "INSERT INTO campus_verifications "
                        "(id, user_id, campus_id, campus_email, status, verified_at, expires_at) "
                        "VALUES (gen_random_uuid(), :user, :campus, :email, 'verified', now(), :expires)"
                    ),
                    {
                        "user": user_id,
                        "campus": CAMPUS_ID,
                        "email": email,
                        "expires": now + timedelta(days=30),
                    },
                )
            for user_id, session_id, digest in (
                (SELLER_ID, SELLER_SESSION_ID, "stage7-seller-session"),
                (BUYER_ID, BUYER_SESSION_ID, "stage7-buyer-session"),
            ):
                await connection.execute(
                    text(
                        "INSERT INTO user_sessions "
                        "(id, user_id, family_id, refresh_token_digest, expires_at, authenticated_at) "
                        "VALUES (:id, :user, :family, :digest, :expires, :authenticated)"
                    ),
                    {
                        "id": session_id,
                        "user": user_id,
                        "family": session_id,
                        "digest": digest,
                        "expires": now + timedelta(days=1),
                        "authenticated": now,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, seller_id, campus_id, category_id, title, description, price, status, "
                    "published_at) VALUES (:id, :seller, :campus, :category, "
                    "'阶段七面交教材', '用于双浏览器订单全生命周期验收', 36.00, 'on_sale', now())"
                ),
                {
                    "id": PRODUCT_ID,
                    "seller": SELLER_ID,
                    "campus": CAMPUS_ID,
                    "category": CATEGORY_ID,
                },
            )
        manager = TokenManager(
            settings.auth_secret_key.get_secret_value(),
            access_minutes=settings.access_token_minutes,
            refresh_days=settings.refresh_token_days,
        )
        seller_token, expires = manager.issue_access_token(
            user_id=SELLER_ID, session_id=SELLER_SESSION_ID, authenticated_at=now
        )
        buyer_token, _ = manager.issue_access_token(
            user_id=BUYER_ID, session_id=BUYER_SESSION_ID, authenticated_at=now
        )
        return seller_token, buyer_token, expires.isoformat()
    finally:
        await engine.dispose()


async def cleanup() -> None:
    settings = Settings()
    assert settings.database_url
    engine = browser_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await clean(connection)
    finally:
        await engine.dispose()


def install_session(
    context: BrowserContext,
    *,
    token: str,
    expires: str,
    user_id: UUID,
    name: str,
    email: str,
) -> None:
    def route_refresh(route: Route) -> None:
        route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {
                    "access_token": token,
                    "access_token_expires_at": expires,
                    "token_type": "bearer",
                    "user": {
                        "id": str(user_id),
                        "login_email": email,
                        "display_name": name,
                        "status": "active",
                        "campus_verification_status": "verified",
                    },
                },
                ensure_ascii=False,
            ),
        )

    context.route("**/api/v1/auth/refresh", route_refresh)


def run() -> None:
    seller_token, buyer_token, expires = asyncio.run(prepare())
    OUTPUT.mkdir(exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            seller_context = browser.new_context(viewport={"width": 390, "height": 844})
            buyer_context = browser.new_context(viewport={"width": 1440, "height": 900})
            install_session(
                seller_context,
                token=seller_token,
                expires=expires,
                user_id=SELLER_ID,
                name="阶段七卖家",
                email="stage7-seller@example.com",
            )
            install_session(
                buyer_context,
                token=buyer_token,
                expires=expires,
                user_id=BUYER_ID,
                name="阶段七买家",
                email="stage7-buyer@example.com",
            )
            seller_page = seller_context.new_page()
            buyer_page = buyer_context.new_page()

            buyer_page.goto(
                f"{BASE_URL}/products/{PRODUCT_ID}", wait_until="networkidle"
            )
            buyer_page.get_by_role("button", name="直接发起交易").click()
            buyer_page.wait_for_url("**/orders/**")
            order_url = buyer_page.url
            buyer_page.get_by_text("待卖家确认", exact=True).first.wait_for()

            seller_page.goto(f"{BASE_URL}/orders", wait_until="networkidle")
            seller_page.get_by_role("button", name="我卖出的").click()
            seller_page.get_by_text("阶段七面交教材", exact=True).click()
            seller_page.get_by_role("button", name="接受交易").click()
            seller_page.get_by_text("待预约", exact=True).first.wait_for()

            buyer_page.reload(wait_until="networkidle")
            meeting_at = (datetime.now() + timedelta(days=1)).replace(
                minute=30, second=0, microsecond=0
            )
            buyer_page.locator('input[type="datetime-local"]').fill(
                meeting_at.strftime("%Y-%m-%dT%H:%M")
            )
            buyer_page.get_by_placeholder("例如：图书馆东门").fill("图书馆东门服务台")
            buyer_page.get_by_role("button", name="提出安排").click()
            buyer_page.get_by_text("图书馆东门服务台", exact=True).wait_for()

            seller_page.reload(wait_until="networkidle")
            seller_page.get_by_text("图书馆东门服务台", exact=True).wait_for()
            seller_page.get_by_role("button", name="确认安排").click()
            seller_page.get_by_text("双方已确认", exact=True).wait_for()
            seller_page.get_by_role("button", name="确认已交付").click()
            seller_page.get_by_text("待买家确认", exact=True).first.wait_for()

            buyer_page.goto(order_url, wait_until="networkidle")
            buyer_page.get_by_role("button", name="确认收货").click()
            buyer_page.get_by_text("已完成", exact=True).first.wait_for()
            buyer_page.get_by_role("button", name="描述一致").click()
            buyer_page.get_by_placeholder("可选，写下真实交易体验").fill(
                "商品与描述一致，面交过程顺利"
            )
            buyer_page.get_by_role("button", name="提交评价").click()
            buyer_page.get_by_text(
                "商品与描述一致，面交过程顺利", exact=True
            ).wait_for()

            seller_page.reload(wait_until="networkidle")
            seller_page.get_by_role("button", name="沟通顺畅").click()
            seller_page.get_by_placeholder("可选，写下真实交易体验").fill(
                "买家沟通清楚并准时到达"
            )
            seller_page.get_by_role("button", name="提交评价").click()
            seller_page.get_by_text("买家沟通清楚并准时到达", exact=True).wait_for()
            seller_page.get_by_text(
                "商品与描述一致，面交过程顺利", exact=True
            ).wait_for()

            assert seller_page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            assert buyer_page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            seller_page.screenshot(
                path=str(OUTPUT / "stage7-seller-mobile.png"), full_page=True
            )
            buyer_page.screenshot(
                path=str(OUTPUT / "stage7-buyer-desktop.png"), full_page=True
            )
            seller_context.close()
            buyer_context.close()
            browser.close()
    finally:
        if not os.getenv("DATABASE_SCHEMA"):
            asyncio.run(cleanup())


if __name__ == "__main__":
    run()
