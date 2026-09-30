"""Stage 6 two-context chat, reconnect, block, report and notification gate."""

import asyncio
import json
import os
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
SELLER_ID = UUID("6a000000-0000-4000-8000-000000000001")
BUYER_ID = UUID("6a000000-0000-4000-8000-000000000002")
SELLER_SESSION_ID = UUID("6a000000-0000-4000-8000-000000000011")
BUYER_SESSION_ID = UUID("6a000000-0000-4000-8000-000000000012")
SCHOOL_ID = UUID("6a000000-0000-4000-8000-000000000021")
CAMPUS_ID = UUID("6a000000-0000-4000-8000-000000000022")
CATEGORY_ID = UUID("6a000000-0000-4000-8000-000000000023")
PRODUCT_ID = UUID("6a000000-0000-4000-8000-000000000024")


async def clean(connection) -> None:  # type: ignore[no-untyped-def]
    user_ids = {"seller": SELLER_ID, "buyer": BUYER_ID}
    await connection.execute(
        text(
            "DELETE FROM notification_delivery_attempts WHERE notification_id IN "
            "(SELECT id FROM notifications WHERE user_id IN (:seller, :buyer))"
        ),
        user_ids,
    )
    for statement in (
        "DELETE FROM notifications WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM notification_preferences WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM audit_logs WHERE actor_id IN (:seller, :buyer)",
        "DELETE FROM reports WHERE reporter_id IN (:seller, :buyer)",
        "DELETE FROM message_risk_signals WHERE message_id IN "
        "(SELECT id FROM messages WHERE conversation_id IN "
        "(SELECT id FROM conversations WHERE product_id = :product))",
        "DELETE FROM conversation_read_states WHERE conversation_id IN "
        "(SELECT id FROM conversations WHERE product_id = :product)",
        "DELETE FROM messages WHERE conversation_id IN "
        "(SELECT id FROM conversations WHERE product_id = :product)",
        "DELETE FROM user_blocks WHERE blocker_id IN (:seller, :buyer) "
        "OR blocked_id IN (:seller, :buyer)",
        "DELETE FROM conversations WHERE product_id = :product",
        "DELETE FROM favorites WHERE product_id = :product",
        "DELETE FROM products WHERE id = :product",
        "DELETE FROM campus_verifications WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM user_sessions WHERE user_id IN (:seller, :buyer)",
        "DELETE FROM users WHERE id IN (:seller, :buyer)",
        "DELETE FROM categories WHERE id = :category",
        "DELETE FROM campuses WHERE id = :campus",
        "DELETE FROM schools WHERE id = :school",
    ):
        await connection.execute(
            text(statement),
            {
                **user_ids,
                "product": PRODUCT_ID,
                "category": CATEGORY_ID,
                "campus": CAMPUS_ID,
                "school": SCHOOL_ID,
            },
        )


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
                    "INSERT INTO schools (id, code, name) VALUES (:id, 'STAGE6', '阶段六测试大学')"
                ),
                {"id": SCHOOL_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'STAGE6', '阶段六校区')"
                ),
                {"id": CAMPUS_ID, "school": SCHOOL_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO categories (id, code, slug, name) "
                    "VALUES (:id, 'stage6', 'stage6', '阶段六测试')"
                ),
                {"id": CATEGORY_ID},
            )
            for user_id, email, name in (
                (SELLER_ID, "stage6-seller@example.com", "阶段六卖家"),
                (BUYER_ID, "stage6-buyer@example.com", "阶段六买家"),
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
                (SELLER_ID, SELLER_SESSION_ID, "stage6-seller-session"),
                (BUYER_ID, BUYER_SESSION_ID, "stage6-buyer-session"),
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
                    "(id, seller_id, campus_id, category_id, title, description, price, status, published_at) "
                    "VALUES (:id, :seller, :campus, :category, '阶段六聊天教材', "
                    "'用于双浏览器真实聊天验收', 26.00, 'on_sale', now())"
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
        if route.request.url.endswith("/api/v1/auth/refresh"):
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
        else:
            route.continue_()

    context.route("**/api/v1/auth/refresh", route_refresh)


def run() -> None:
    seller_token, buyer_token, expires = asyncio.run(prepare())
    OUTPUT.mkdir(exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            seller_context = browser.new_context(viewport={"width": 375, "height": 850})
            buyer_context = browser.new_context(viewport={"width": 1440, "height": 900})
            install_session(
                seller_context,
                token=seller_token,
                expires=expires,
                user_id=SELLER_ID,
                name="阶段六卖家",
                email="stage6-seller@example.com",
            )
            install_session(
                buyer_context,
                token=buyer_token,
                expires=expires,
                user_id=BUYER_ID,
                name="阶段六买家",
                email="stage6-buyer@example.com",
            )
            seller_page = seller_context.new_page()
            buyer_page = buyer_context.new_page()

            product_response = buyer_page.request.get(
                f"http://127.0.0.1:8000/api/v1/market/products/{PRODUCT_ID}"
            )
            assert product_response.ok, product_response.text()

            buyer_page.goto(
                f"{BASE_URL}/products/{PRODUCT_ID}", wait_until="networkidle"
            )
            buyer_page.get_by_role("button", name="联系卖家", exact=True).click()
            buyer_page.wait_for_url("**/messages/**")
            conversation_id = buyer_page.url.rsplit("/", 1)[-1]

            seller_page.goto(f"{BASE_URL}/messages", wait_until="networkidle")
            seller_page.get_by_text("阶段六买家", exact=True).click()
            seller_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            ).wait_for()
            seller_page.locator(".connection-state.live").wait_for()
            buyer_page.locator(".connection-state.live").wait_for()

            buyer_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            ).fill("买家消息：周三中午图书馆见")
            buyer_page.get_by_role("button", name="发送", exact=True).click()
            buyer_page.locator(".message-row.mine").last.get_by_text(
                "已发送", exact=False
            ).wait_for()
            seller_page.locator(".thread-pane").get_by_text(
                "买家消息：周三中午图书馆见", exact=True
            ).wait_for()

            seller_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            ).fill("卖家消息：可以，带上校园卡")
            seller_page.get_by_role("button", name="发送", exact=True).click()
            buyer_page.locator(".thread-pane").get_by_text(
                "卖家消息：可以，带上校园卡", exact=True
            ).wait_for()

            buyer_composer = buyer_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            )
            buyer_composer.fill("键盘回车发送")
            buyer_composer.press("Enter")
            seller_page.locator(".thread-pane").get_by_text(
                "键盘回车发送", exact=True
            ).wait_for()

            seller_composer = seller_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            )
            seller_composer.fill("第一行")
            seller_composer.press("Shift+Enter")
            seller_composer.type("第二行")
            assert seller_composer.input_value() == "第一行\n第二行"
            seller_composer.press("Enter")
            buyer_page.locator(".thread-pane").get_by_text(
                "第一行\n第二行", exact=True
            ).wait_for()

            buyer_page.close()
            seller_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            ).fill("离线补拉消息：我会提前五分钟到")
            seller_page.get_by_role("button", name="发送", exact=True).click()
            buyer_page = buyer_context.new_page()
            buyer_page.goto(
                f"{BASE_URL}/messages/{conversation_id}", wait_until="networkidle"
            )
            buyer_page.locator(".thread-pane").get_by_text(
                "离线补拉消息：我会提前五分钟到", exact=True
            ).wait_for()

            buyer_page.locator(".message-row:not(.mine)").last.get_by_role(
                "button", name="举报"
            ).click()
            buyer_page.get_by_role("dialog", name="举报这条消息").get_by_label(
                "举报原因"
            ).select_option("spam")
            buyer_page.get_by_role("dialog", name="举报这条消息").get_by_label(
                "事实说明"
            ).fill("重复引导离开平台")
            buyer_page.get_by_role("button", name="提交举报").click()
            buyer_page.get_by_text("举报已受理").wait_for()

            seller_page.once("dialog", lambda dialog: dialog.accept())
            seller_page.get_by_role("button", name="屏蔽").click()
            seller_page.get_by_text("已屏蔽该用户").wait_for()
            buyer_page.get_by_placeholder(
                "输入消息，建议只在校内公共区域当面交易"
            ).fill("这条消息应被屏蔽")
            buyer_page.get_by_role("button", name="发送", exact=True).click()
            buyer_page.get_by_text("发送失败", exact=False).wait_for()

            buyer_page.goto(f"{BASE_URL}/notifications", wait_until="networkidle")
            buyer_page.get_by_text("收到一条新消息", exact=True).first.wait_for()
            assert "卖家消息：可以" not in buyer_page.locator("body").inner_text()
            buyer_page.get_by_role("button", name="全部标为已读").click()
            buyer_page.get_by_role("button", name="全部标为已读").wait_for(
                state="detached"
            )
            assert seller_page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            assert buyer_page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            seller_page.screenshot(
                path=OUTPUT / "stage6-chat-mobile.png", full_page=True
            )
            buyer_page.screenshot(
                path=OUTPUT / "stage6-notifications-desktop.png", full_page=True
            )

            unread = buyer_page.request.get(
                "http://127.0.0.1:8000/api/v1/chat/conversations",
                headers={"Authorization": f"Bearer {buyer_token}"},
            )
            assert unread.ok and unread.json()["items"][0]["unread_count"] == 0
            report_count = buyer_page.request.get(
                "http://127.0.0.1:8000/api/v1/chat/notifications",
                headers={"Authorization": f"Bearer {buyer_token}"},
            )
            assert report_count.ok

            seller_context.close()
            buyer_context.close()
            browser.close()
    finally:
        if not os.getenv("DATABASE_SCHEMA"):
            asyncio.run(cleanup())


if __name__ == "__main__":
    run()
