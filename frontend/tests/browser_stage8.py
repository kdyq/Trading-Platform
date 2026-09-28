"""Stage 8 report, moderation, appeal and reversal browser gate."""

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from playwright.sync_api import BrowserContext, Route, sync_playwright
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.core.security import TokenManager  # noqa: E402
from app.db.seed import seed_roles_and_permissions  # noqa: E402
from app.db.url import database_url_for_sqlalchemy  # noqa: E402
from scripts.postgres_gate import load_database_url  # noqa: E402

BASE_URL = "http://127.0.0.1:5173"
REPORTER_ID = UUID("8a000000-0000-4000-8000-000000000001")
SUBJECT_ID = UUID("8a000000-0000-4000-8000-000000000002")
REVIEWER_ONE_ID = UUID("8a000000-0000-4000-8000-000000000003")
REVIEWER_TWO_ID = UUID("8a000000-0000-4000-8000-000000000004")
SESSION_IDS = {
    REPORTER_ID: UUID("8a000000-0000-4000-8000-000000000011"),
    SUBJECT_ID: UUID("8a000000-0000-4000-8000-000000000012"),
    REVIEWER_ONE_ID: UUID("8a000000-0000-4000-8000-000000000013"),
    REVIEWER_TWO_ID: UUID("8a000000-0000-4000-8000-000000000014"),
}
SCHOOL_ID = UUID("8a000000-0000-4000-8000-000000000021")
CAMPUS_ID = UUID("8a000000-0000-4000-8000-000000000022")
CATEGORY_ID = UUID("8a000000-0000-4000-8000-000000000023")
PRODUCT_ID = UUID("8a000000-0000-4000-8000-000000000024")
ROLE_ID = UUID("8a000000-0000-4000-8000-000000000025")


async def clean(connection, storage_root: Path) -> None:  # type: ignore[no-untyped-def]
    user_ids = (REPORTER_ID, SUBJECT_ID, REVIEWER_ONE_ID, REVIEWER_TWO_ID)
    keys = list(
        await connection.scalars(
            text(
                "SELECT object_key FROM report_evidence WHERE report_id IN "
                "(SELECT id FROM reports WHERE reporter_id = ANY(:users))"
            ),
            {"users": list(user_ids)},
        )
    )
    keys.extend(
        await connection.scalars(
            text(
                "SELECT object_key FROM report_appeal_evidence WHERE appeal_id IN "
                "(SELECT id FROM report_appeals WHERE appellant_id = ANY(:users))"
            ),
            {"users": list(user_ids)},
        )
    )
    for key in keys:
        target = (storage_root / str(key)).resolve()
        if target.is_relative_to(storage_root.resolve()):
            target.unlink(missing_ok=True)
    values = {
        "users": list(user_ids),
        "product": PRODUCT_ID,
        "role": ROLE_ID,
        "category": CATEGORY_ID,
        "campus": CAMPUS_ID,
        "school": SCHOOL_ID,
    }
    statements = (
        "DELETE FROM notification_delivery_attempts WHERE notification_id IN "
        "(SELECT id FROM notifications WHERE user_id = ANY(:users))",
        "DELETE FROM notifications WHERE user_id = ANY(:users)",
        "DELETE FROM report_appeal_evidence WHERE appeal_id IN "
        "(SELECT id FROM report_appeals WHERE appellant_id = ANY(:users))",
        "DELETE FROM report_appeals WHERE report_id IN "
        "(SELECT id FROM reports WHERE reporter_id = ANY(:users))",
        "DELETE FROM report_events WHERE report_id IN "
        "(SELECT id FROM reports WHERE reporter_id = ANY(:users))",
        "DELETE FROM report_evidence WHERE report_id IN "
        "(SELECT id FROM reports WHERE reporter_id = ANY(:users))",
        "DELETE FROM credit_ledgers WHERE user_id = ANY(:users)",
        "DELETE FROM moderation_records WHERE moderator_id = ANY(:users) OR target_id = :product",
        "DELETE FROM audit_logs WHERE actor_id = ANY(:users) OR target_id = :product",
        "DELETE FROM reports WHERE reporter_id = ANY(:users)",
        "DELETE FROM user_roles WHERE user_id = ANY(:users) OR role_id = :role",
        "DELETE FROM roles WHERE id = :role",
        "DELETE FROM products WHERE id = :product",
        "DELETE FROM campus_verifications WHERE user_id = ANY(:users)",
        "DELETE FROM user_sessions WHERE user_id = ANY(:users)",
        "DELETE FROM users WHERE id = ANY(:users)",
        "DELETE FROM categories WHERE id = :category",
        "DELETE FROM campuses WHERE id = :campus",
        "DELETE FROM schools WHERE id = :school",
    )
    for statement in statements:
        await connection.execute(text(statement), values)


async def prepare() -> tuple[dict[UUID, str], str]:
    settings = Settings()
    assert settings.auth_secret_key
    engine = create_async_engine(database_url_for_sqlalchemy(load_database_url()))
    now = datetime.now(UTC)
    users = (
        (REPORTER_ID, "stage8-reporter@example.com", "阶段八举报人"),
        (SUBJECT_ID, "stage8-subject@example.com", "阶段八卖家"),
        (REVIEWER_ONE_ID, "stage8-reviewer-1@example.com", "审核员甲"),
        (REVIEWER_TWO_ID, "stage8-reviewer-2@example.com", "审核员乙"),
    )
    try:
        async with engine.begin() as connection:
            await clean(connection, settings.resolved_private_storage_root)
            await seed_roles_and_permissions(connection)
            await connection.execute(
                text(
                    "INSERT INTO schools (id, code, name) VALUES (:id, 'STAGE8', '阶段八测试大学')"
                ),
                {"id": SCHOOL_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO campuses (id, school_id, code, name) "
                    "VALUES (:id, :school, 'STAGE8', '阶段八校区')"
                ),
                {"id": CAMPUS_ID, "school": SCHOOL_ID},
            )
            await connection.execute(
                text(
                    "INSERT INTO categories (id, code, slug, name) "
                    "VALUES (:id, 'stage8', 'stage8', '阶段八测试')"
                ),
                {"id": CATEGORY_ID},
            )
            for user_id, email, name in users:
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
                        "INSERT INTO user_sessions "
                        "(id, user_id, family_id, refresh_token_digest, expires_at, authenticated_at) "
                        "VALUES (:id, :user, :id, :digest, :expires, :authenticated)"
                    ),
                    {
                        "id": SESSION_IDS[user_id],
                        "user": user_id,
                        "digest": f"stage8-{user_id}",
                        "expires": now + timedelta(days=1),
                        "authenticated": now,
                    },
                )
            await connection.execute(
                text(
                    "INSERT INTO roles (id, code, name) VALUES (:id, 'REVIEWER', '审核员') "
                    "ON CONFLICT (code) DO NOTHING"
                ),
                {"id": ROLE_ID},
            )
            reviewer_role_id = await connection.scalar(
                text("SELECT id FROM roles WHERE code = 'REVIEWER'")
            )
            for reviewer_id in (REVIEWER_ONE_ID, REVIEWER_TWO_ID):
                await connection.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id) VALUES (:user, :role)"
                    ),
                    {"user": reviewer_id, "role": reviewer_role_id},
                )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, seller_id, campus_id, category_id, title, description, price, status, "
                    "published_at) VALUES (:id, :seller, :campus, :category, "
                    "'阶段八审核商品', '用于举报申诉全流程浏览器验收', 58.00, 'on_sale', now())"
                ),
                {
                    "id": PRODUCT_ID,
                    "seller": SUBJECT_ID,
                    "campus": CAMPUS_ID,
                    "category": CATEGORY_ID,
                },
            )
        manager = TokenManager(
            settings.auth_secret_key.get_secret_value(),
            access_minutes=settings.access_token_minutes,
            refresh_days=settings.refresh_token_days,
        )
        tokens = {
            user_id: manager.issue_access_token(
                user_id=user_id,
                session_id=SESSION_IDS[user_id],
                authenticated_at=now,
            )[0]
            for user_id, _, _ in users
        }
        return tokens, (
            now + timedelta(minutes=settings.access_token_minutes)
        ).isoformat()
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
    tokens, expires = asyncio.run(prepare())
    settings = Settings()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            contexts: dict[UUID, BrowserContext] = {}
            names = {
                REPORTER_ID: ("阶段八举报人", "stage8-reporter@example.com"),
                SUBJECT_ID: ("阶段八卖家", "stage8-subject@example.com"),
                REVIEWER_ONE_ID: ("审核员甲", "stage8-reviewer-1@example.com"),
                REVIEWER_TWO_ID: ("审核员乙", "stage8-reviewer-2@example.com"),
            }
            for user_id, (name, email) in names.items():
                context = browser.new_context()
                install_session(
                    context,
                    token=tokens[user_id],
                    expires=expires,
                    user_id=user_id,
                    name=name,
                    email=email,
                )
                contexts[user_id] = context

            reporter = contexts[REPORTER_ID].new_page()
            reporter.goto(f"{BASE_URL}/products/{PRODUCT_ID}")
            reporter.get_by_role("button", name="举报商品").click()
            reporter.get_by_label("事实说明").fill(
                "商品描述疑似存在欺诈信息，请平台核查"
            )
            reporter.get_by_label("证据附件（可选）").set_input_files(
                {
                    "name": "evidence.png",
                    "mimeType": "image/png",
                    "buffer": b"\x89PNG\r\n\x1a\nproof",
                }
            )
            reporter.get_by_role("button", name="提交举报").click()
            reporter.get_by_text("举报已受理").wait_for()

            reviewer_one = contexts[REVIEWER_ONE_ID].new_page()
            reviewer_one.goto(f"{BASE_URL}/admin")
            report_card = reviewer_one.locator(".report-review-card").first
            report_card.get_by_label("公开处理结论").fill(
                "核实存在违规，给予警告并扣减信用"
            )
            report_card.get_by_label("内部调查理由").fill(
                "证据文件与举报事实能够相互印证"
            )
            report_card.get_by_role("button", name="确认违规").click()
            report_card.get_by_text("resolved").wait_for()

            subject = contexts[SUBJECT_ID].new_page()
            subject.goto(f"{BASE_URL}/notifications")
            subject.get_by_role("link", name="提交申诉").click()
            subject.get_by_label("申诉说明").fill(
                "原处理忽略了关键上下文，请求由不同审核员独立复核"
            )
            subject.get_by_label("复核材料（可选，仅授权人员可查看）").set_input_files(
                {
                    "name": "appeal.png",
                    "mimeType": "image/png",
                    "buffer": b"\x89PNG\r\n\x1a\nappeal-proof",
                }
            )
            subject.get_by_role("button", name="提交申诉").click()
            subject.get_by_text("申诉已提交").wait_for()

            reviewer_two = contexts[REVIEWER_TWO_ID].new_page()
            reviewer_two.on("dialog", lambda dialog: dialog.accept())
            reviewer_two.goto(f"{BASE_URL}/admin")
            appeal_card = (
                reviewer_two.locator(".report-review-card")
                .filter(has_text="独立复核")
                .first
            )
            if appeal_card.count() == 0:
                appeal_card = (
                    reviewer_two.locator(".report-queue")
                    .last.locator(".report-review-card")
                    .first
                )
            appeal_card.get_by_label("复核理由").fill(
                "复核发现现有证据不足以支持原处罚"
            )
            appeal_card.get_by_role("button", name="下载复核材料").wait_for()
            appeal_card.get_by_role("button", name="撤销处罚").click()
            appeal_card.get_by_text("reversed").wait_for()
            browser.close()
        print("STAGE8_BROWSER_OK")
    finally:

        async def cleanup() -> None:
            engine = create_async_engine(database_url_for_sqlalchemy(load_database_url()))
            try:
                async with engine.begin() as connection:
                    await clean(connection, settings.resolved_private_storage_root)
            finally:
                await engine.dispose()

        asyncio.run(cleanup())


if __name__ == "__main__":
    run()
