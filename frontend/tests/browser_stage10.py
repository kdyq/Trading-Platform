"""Run production-preview browser journeys against a disposable PostgreSQL schema."""

import asyncio
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from PIL import Image
from playwright.sync_api import Page, Route, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
sys.path.insert(0, str(BACKEND))

from app.db.url import require_project_database, require_test_schema  # noqa: E402
from scripts.postgres_gate import asyncpg_url, load_database_url  # noqa: E402

BASE_URL = "http://127.0.0.1:5173"
API_URL = "http://127.0.0.1:8000"
SCREENSHOTS = ROOT / "docs" / "第十阶段截图"


async def schema_command(database_url: str, sql: str) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


async def seed_browser_campus(database_url: str, schema: str) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        school_id = uuid4()
        await connection.execute(
            "INSERT INTO schools (id, code, name) VALUES ($1, 'STAGE10', '阶段十测试大学')",
            school_id,
        )
        await connection.execute(
            "INSERT INTO campuses (id, school_id, code, name) "
            "VALUES (gen_random_uuid(), $1, 'STAGE10', '阶段十校区')",
            school_id,
        )
        await connection.execute(
            "INSERT INTO school_email_domains (id, school_id, domain) "
            "VALUES (gen_random_uuid(), $1, 'example.com')",
            school_id,
        )
    finally:
        await connection.close()


def run_command(*args: str, cwd: Path, environment: dict[str, str]) -> None:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"{' '.join(args[:2])} failed:\n{result.stdout[-1500:]}\n{result.stderr[-1500:]}"
        )


def wait_ready(url: str, process: subprocess.Popen[str]) -> None:
    last_error = ""
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"Server exited before ready: {url}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.2)
    raise RuntimeError(f"Server not ready: {url}; last response: {last_error}")


def responsive_preview() -> dict[str, object]:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    captures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (375, 768, 1024, 1440):
                for motion in ("no-preference", "reduce"):
                    context = browser.new_context(
                        viewport={"width": width, "height": 900}, reduced_motion=motion
                    )
                    context.route(
                        "**/api/v1/auth/refresh",
                        lambda route: route.fulfill(
                            status=401,
                            content_type="application/json",
                            body='{"code":"authentication_required"}',
                        ),
                    )
                    page = context.new_page()
                    errors: list[str] = []
                    failed: list[str] = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: errors.append(f"console: {message.text}")
                        if message.type == "error"
                        and not message.location.get("url", "").endswith(
                            "/api/v1/auth/refresh"
                        )
                        else None,
                    )
                    page.on(
                        "requestfailed",
                        lambda request: failed.append(
                            f"transport: {request.url} {request.failure}"
                        ),
                    )
                    page.on(
                        "response",
                        lambda response: failed.append(
                            f"{response.status} {response.url}"
                        )
                        if response.status >= 400
                        and ("/api/v1/" in response.url or "/assets/" in response.url)
                        and not (
                            response.status == 401
                            and response.url.endswith("/api/v1/auth/refresh")
                        )
                        else None,
                    )
                    for route in ("/", "/market", "/login", "/register", "/privacy"):
                        if route == "/market":
                            with (
                                page.expect_response(
                                    lambda response: "/api/v1/market/products?"
                                    in response.url
                                ) as market_response,
                                page.expect_response(
                                    lambda response: response.url.endswith(
                                        "/api/v1/market/campuses"
                                    )
                                ) as campuses_response,
                            ):
                                page.get_by_role(
                                    "link", name="开始逛逛", exact=True
                                ).click()
                            assert market_response.value.status == 200
                            assert campuses_response.value.status == 200
                            page.wait_for_url(BASE_URL + "/market")
                            page.wait_for_load_state("networkidle")
                            assert page.evaluate(
                                "() => window.__stage10Seal && !window.__stage10Seal.isConnected "
                                "&& window.__stage10Seal.style.transform === '' "
                                "&& window.__stage10Ticket.style.transform === ''"
                            ), (
                                "Home GSAP transforms were not reverted during SPA unmount"
                            )
                            assert not page.locator(".pin-spacer").count(), (
                                "SPA pin remains"
                            )
                        else:
                            page.goto(BASE_URL + route, wait_until="networkidle")
                        if route == "/":
                            page.evaluate(
                                "() => { window.__stage10Seal = document.querySelector('.hero-trust-seal'); "
                                "window.__stage10Ticket = document.querySelector('.hero-market-ticket'); }"
                            )
                            initial_transform = page.locator(
                                ".hero-trust-seal"
                            ).evaluate("el => getComputedStyle(el).transform")
                            page.wait_for_timeout(350)
                            later_transform = page.locator(".hero-trust-seal").evaluate(
                                "el => getComputedStyle(el).transform"
                            )
                            if motion == "reduce":
                                assert initial_transform == later_transform == "none", (
                                    "Reduced motion still animates the trust seal"
                                )
                                assert not page.locator(".pin-spacer").count()
                                assert page.locator(".market-reveal").evaluate_all(
                                    "els => els.every(el => getComputedStyle(el).opacity === '1' "
                                    "&& getComputedStyle(el).visibility !== 'hidden')"
                                ), "Reduced motion leaves content concealed"
                            else:
                                assert initial_transform != later_transform, (
                                    "Normal motion stopped"
                                )
                        if not page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth + 1"
                        ):
                            raise AssertionError(
                                f"Horizontal overflow at {width}px {motion} {route}"
                            )
                        if route in ("/", "/market") and motion == "no-preference":
                            name = f"{route.strip('/') or 'home'}-{width}.png"
                            path = SCREENSHOTS / name
                            page.screenshot(path=str(path), full_page=True)
                            captures.append(str(path.relative_to(ROOT)))
                    if page.locator(".pin-spacer").count():
                        raise AssertionError(
                            f"GSAP pin remains after leaving home: {width}px"
                        )
                    if errors or failed:
                        raise AssertionError(
                            f"Browser errors at {width}px {motion}: {errors} {failed}"
                        )
                    context.close()
        finally:
            browser.close()
    return {
        "widths": [375, 768, 1024, 1440],
        "motions": ["normal", "reduce"],
        "screenshots": captures,
    }


def auth_preview() -> dict[str, object]:
    user_id = str(uuid4())
    auth_result = {
        "access_token": "stage10-browser-mock-token",
        "access_token_expires_at": "2030-01-01T00:00:00Z",
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "login_email": "stage10@example.invalid",
            "display_name": "阶段十同学",
            "status": "active",
            "campus_verification_status": "unverified",
        },
    }
    calls: list[str] = []

    def auth_api(route: Route) -> None:
        request = route.request
        path = request.url.split("?", 1)[0]
        if path.endswith("/api/v1/auth/refresh"):
            route.fulfill(
                status=401,
                content_type="application/json",
                body='{"code":"authentication_required"}',
            )
        elif path.endswith("/api/v1/auth/email-verifications"):
            calls.append("verification-request")
            route.fulfill(
                status=202,
                content_type="application/json",
                body='{"message":"验证码已发送"}',
            )
        elif path.endswith("/api/v1/auth/register"):
            calls.append("register")
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps(auth_result, ensure_ascii=False),
            )
        elif path.endswith("/api/v1/auth/login"):
            calls.append("login")
            if (request.post_data_json or {}).get("password") != "ValidPass123":
                route.fulfill(
                    status=401,
                    content_type="application/json",
                    body='{"code":"invalid_credentials","message":"账号或密码错误"}',
                )
            else:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(auth_result, ensure_ascii=False),
                )
        else:
            route.continue_()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            registration = browser.new_context(viewport={"width": 375, "height": 812})
            registration.route("**/api/v1/auth/**", auth_api)
            page = registration.new_page()
            page.goto(BASE_URL + "/register", wait_until="networkidle")
            page.locator('input[name="email"]').fill("stage10@example.invalid")
            page.get_by_role("button", name="发送验证码").click()
            page.get_by_text("验证码已发送").wait_for()
            page.locator('input[name="code"]').fill("123456")
            page.locator('input[name="display-name"]').fill("阶段十同学")
            page.locator('input[name="password"]').fill("ValidPass123")
            page.locator(".consent-row input").nth(0).check()
            page.locator(".consent-row input").nth(1).check()
            page.screenshot(path=str(SCREENSHOTS / "register-375.png"), full_page=True)
            page.get_by_role("button", name="创建账户").click()
            page.wait_for_url(BASE_URL + "/")
            page.get_by_role("heading", name="闲置好物，换个主人继续发光").wait_for()
            registration.close()

            login = browser.new_context(viewport={"width": 1440, "height": 900})
            login.route("**/api/v1/auth/**", auth_api)
            page = login.new_page()
            page.goto(BASE_URL + "/login", wait_until="networkidle")
            page.locator('input[name="email"]').fill("stage10@example.invalid")
            page.locator('input[name="password"]').fill("wrong")
            page.get_by_role("button", name="登录", exact=True).click()
            page.get_by_role("alert").get_by_text("账号或密码错误").wait_for()
            page.locator('input[name="password"]').fill("ValidPass123")
            page.get_by_role("button", name="登录", exact=True).click()
            page.wait_for_url(BASE_URL + "/")
            login.close()
        finally:
            browser.close()
    assert calls == ["verification-request", "register", "login", "login"], calls
    return {
        "mocked_ui_journey": calls,
        "screenshot": "docs/第十阶段截图/register-375.png",
    }


async def pending_test_product(
    database_url: str, schema: str, seller_id: str, title: str
) -> str:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        row = await connection.fetchrow(
            "SELECT id, status FROM products WHERE seller_id = $1 AND title = $2",
            UUID(seller_id),
            title,
        )
        assert row is not None and row["status"] == "pending_review", row
        return str(row["id"])
    finally:
        await connection.close()


async def assign_test_reviewer(database_url: str, schema: str, user_id: str) -> None:
    connection = await asyncpg.connect(asyncpg_url(database_url))
    try:
        await connection.execute(f'SET search_path TO "{schema}"')
        await connection.execute(
            "INSERT INTO user_roles (user_id, role_id) "
            "SELECT $1, id FROM roles WHERE code = 'REVIEWER'",
            UUID(user_id),
        )
    finally:
        await connection.close()


def real_core_preview(
    database_url: str, schema: str, mail_file: Path
) -> dict[str, object]:
    suffix = uuid4().hex[:10]
    password = secrets.token_urlsafe(14) + "A1"
    product_title = f"阶段十真实发布教材 {suffix}"
    seller_email = f"stage10-seller-{suffix}@example.com"
    buyer_email = f"stage10-buyer-{suffix}@example.com"
    photo = io.BytesIO()
    Image.new("RGB", (128, 128), (255, 107, 53)).save(photo, format="PNG")

    def run_db(coroutine: object) -> object:
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coroutine).result()

    def register(page: Page, email: str, name: str) -> str:
        page.goto(BASE_URL + "/register", wait_until="networkidle")
        page.locator('input[name="email"]').fill(email)
        mail_file.unlink(missing_ok=True)
        with page.expect_response(
            lambda response: response.url.endswith("/api/v1/auth/email-verifications")
        ) as pending_code:
            page.get_by_role("button", name="发送验证码").click()
        assert pending_code.value.status == 202, pending_code.value.text()
        page.locator(".success-message").wait_for()
        delivered = json.loads(mail_file.read_text(encoding="utf-8"))
        assert delivered["recipient"] == email
        page.locator('input[name="code"]').fill(delivered["code"])
        page.locator('input[name="display-name"]').fill(name)
        page.locator('input[name="password"]').fill(password)
        page.locator(".consent-row input").nth(0).check()
        page.locator(".consent-row input").nth(1).check()
        with page.expect_response(
            lambda response: response.url.endswith("/api/v1/auth/register")
        ) as pending:
            page.get_by_role("button", name="创建账户").click()
        assert pending.value.status == 201, pending.value.text()
        page.wait_for_url(BASE_URL + "/")
        return str(pending.value.json()["user"]["id"])

    def verify_campus(page: Page, email: str) -> None:
        page.goto(BASE_URL + "/campus-verification", wait_until="networkidle")
        page.get_by_label("校园邮箱").fill(email)
        mail_file.unlink(missing_ok=True)
        with page.expect_response(
            lambda response: response.url.endswith("/api/v1/campus/email-verifications")
        ) as pending_code:
            page.get_by_role("button", name="发送校园验证码").click()
        assert pending_code.value.status == 202, pending_code.value.text()
        page.get_by_role("heading", name="确认验证码", exact=True).wait_for()
        delivered = json.loads(mail_file.read_text(encoding="utf-8"))
        assert delivered["recipient"] == email
        page.get_by_label("6 位验证码").fill(delivered["code"])
        with page.expect_response(
            lambda response: response.url.endswith(
                "/api/v1/campus/email-verifications/confirm"
            )
        ) as pending_confirmation:
            page.get_by_role("button", name="完成认证").click()
        assert pending_confirmation.value.status == 200, (
            pending_confirmation.value.text()
        )
        assert pending_confirmation.value.json()["status"] == "verified"
        page.get_by_role("status").get_by_text("校园身份认证成功").wait_for()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            seller = browser.new_context(viewport={"width": 375, "height": 812})
            seller_page = seller.new_page()
            seller_calls: list[str] = []
            draft_updates: list[str] = []
            seller_page.on(
                "response",
                lambda response: seller_calls.append(
                    f"{response.status} {response.url}"
                )
                if "/api/v1/seller/products" in response.url
                else None,
            )
            seller_page.on(
                "response",
                lambda response: draft_updates.append(response.url)
                if response.request.method == "PATCH"
                and "/api/v1/seller/products/" in response.url
                else None,
            )
            seller_id = register(seller_page, seller_email, "真实卖家")
            verify_campus(seller_page, seller_email)
            seller_page.reload(wait_until="networkidle")
            seller_page.goto(BASE_URL + "/sell", wait_until="networkidle")
            seller_page.get_by_role("heading", name="发布一件校园好物").wait_for()
            seller_page.get_by_label("商品标题").fill(product_title)
            seller_page.get_by_label("详细描述").fill(
                "隔离浏览器验收的真实教材商品，页面完整、内页无破损。"
            )
            seller_page.get_by_label("售价").fill("18.50")
            seller_page.get_by_role("button", name="下一步").click()
            seller_page.locator('input[type="file"]').set_input_files(
                {
                    "name": "stage10.png",
                    "mimeType": "image/png",
                    "buffer": photo.getvalue(),
                }
            )
            seller_page.get_by_text("图片 1").wait_for()
            seller_page.get_by_label("交付说明").fill("图书馆门口当面交接")
            save_button = seller_page.get_by_role("button", name="保存草稿")
            save_button.click()
            seller_page.get_by_role("status").get_by_text("草稿已保存").wait_for()
            saved_updates = len(draft_updates)
            seller_page.wait_for_timeout(1600)
            seller_page.wait_for_load_state("networkidle")
            assert len(draft_updates) == saved_updates, (
                "Server hydration retriggered autosave"
            )
            seller_page.get_by_role("button", name="下一步").click()
            seller_page.get_by_role("button", name="提交审核").click()
            try:
                seller_page.wait_for_url("**/my-products", timeout=8000)
            except Exception as exc:
                alerts = seller_page.locator('[role="alert"]').all_text_contents()
                validity = seller_page.evaluate(
                    "() => ({ valid: document.querySelector('form').checkValidity(), invalid: [...document.querySelectorAll('form :invalid')].map(el => [el.tagName, el.name, el.value]), submitDisabled: document.querySelector('.publish-submit').disabled })"
                )
                raise AssertionError(
                    f"Real publish failed: {seller_page.url} {alerts} {validity} {seller_calls}"
                ) from exc
            seller_page.get_by_text("待审核", exact=True).wait_for()
            seller_page.screenshot(
                path=str(SCREENSHOTS / "publish-real-375.png"), full_page=True
            )
            product_id = run_db(
                pending_test_product(database_url, schema, seller_id, product_title)
            )
            assert isinstance(product_id, str)

            login = browser.new_context(viewport={"width": 1440, "height": 900})
            login_page = login.new_page()
            login_page.goto(BASE_URL + "/login", wait_until="networkidle")
            login_page.locator('input[name="email"]').fill(seller_email)
            login_page.locator('input[name="password"]').fill("wrong")
            login_page.get_by_role("button", name="登录", exact=True).click()
            login_page.get_by_role("alert").get_by_text("账号或密码不正确").wait_for()
            login_page.locator('input[name="password"]').fill(password)
            with login_page.expect_response(
                lambda response: response.url.endswith("/api/v1/auth/login")
            ) as pending_login:
                login_page.get_by_role("button", name="登录", exact=True).click()
            assert pending_login.value.status == 200
            login_page.wait_for_url(BASE_URL + "/")
            login.close()

            buyer = browser.new_context(viewport={"width": 375, "height": 812})
            buyer_page = buyer.new_page()
            buyer_id = register(buyer_page, buyer_email, "真实买家")
            verify_campus(buyer_page, buyer_email)
            run_db(assign_test_reviewer(database_url, schema, buyer_id))
            buyer_page.reload(wait_until="networkidle")
            buyer_page.goto(BASE_URL + "/admin", wait_until="networkidle")
            card = buyer_page.locator(".moderation-card").filter(has_text=product_title)
            card.get_by_label("给卖家的公开说明").fill(
                "商品信息与图片完整，通过隔离验收审核"
            )
            with buyer_page.expect_response(
                lambda response: "/api/v1/moderation/products/" in response.url
                and response.request.method == "POST"
            ) as pending_review:
                card.get_by_role("button", name="通过", exact=True).click()
            assert pending_review.value.status == 200, pending_review.value.text()
            buyer_page.goto(
                BASE_URL + f"/products/{product_id}", wait_until="networkidle"
            )
            buyer_page.get_by_role("heading", name=product_title).wait_for()
            buyer_page.get_by_role("button", name="收藏 · 0").click()
            buyer_page.get_by_role("button", name="取消收藏 · 1").wait_for()
            buyer_page.goto(BASE_URL + "/favorites", wait_until="networkidle")
            buyer_page.get_by_text(product_title, exact=True).wait_for()
            assert buyer_page.locator(".product-card img").evaluate(
                "el => el.complete && el.naturalWidth > 0"
            ), "Favorite thumbnail failed to load"
            buyer_page.screenshot(
                path=str(SCREENSHOTS / "favorites-real-375.png"), full_page=True
            )
            buyer_page.goto(BASE_URL + "/market", wait_until="networkidle")
            with buyer_page.expect_response(
                lambda response: "/api/v1/market/products?" in response.url
                and "keyword=" in response.url
            ) as pending_search:
                buyer_page.get_by_label("搜索商品").fill(product_title)
            assert pending_search.value.status == 200, pending_search.value.text()
            assert any(
                item["title"] == product_title and item["image_url"]
                for item in pending_search.value.json()["items"]
            )
            buyer_page.get_by_text(product_title, exact=True).wait_for()
            buyer_page.wait_for_load_state("networkidle")
            assert (
                buyer_page.locator(".product-card")
                .filter(has_text=product_title)
                .locator("img")
                .evaluate("el => el.complete && el.naturalWidth > 0")
            ), "Search thumbnail failed to load"
            buyer.close()
            seller.close()
        finally:
            browser.close()
    return {
        "real_api_journey": [
            "register-seller",
            "campus-email-verification-seller",
            "publish-submit",
            "login-failure",
            "login-success",
            "register-buyer",
            "campus-email-verification-buyer",
            "review-approve",
            "favorite",
            "search",
        ],
        "database_schema": "disposable test_gate_*",
        "screenshots": [
            "docs/第十阶段截图/publish-real-375.png",
            "docs/第十阶段截图/favorites-real-375.png",
        ],
    }


async def run(state: dict[str, object]) -> dict[str, object]:
    state["stage"] = "preflight"
    for port in (8000, 5173):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    database_url = load_database_url()
    require_project_database(database_url)
    schema = f"test_gate_{uuid4().hex}"
    require_test_schema(schema)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["DATABASE_SCHEMA"] = schema
    environment["VITE_API_BASE_URL"] = API_URL
    environment["APP_ENV"] = "test"
    temp_dir = tempfile.TemporaryDirectory(prefix="stage10-browser-")
    mail_file = Path(temp_dir.name) / "verification.json"
    api_log_path = Path(temp_dir.name) / "api.log"
    api_log = api_log_path.open("w", encoding="utf-8")
    environment["STAGE10_MAIL_FILE"] = str(mail_file)
    environment["APP_PRIVATE_STORAGE_ROOT"] = str(Path(temp_dir.name) / "private")
    environment["APP_PUBLIC_PRODUCT_STORAGE_ROOT"] = str(Path(temp_dir.name) / "public")
    python = sys.executable
    api: subprocess.Popen[str] | None = None
    preview: subprocess.Popen[str] | None = None
    results: dict[str, object] = {}
    state["results"] = results
    try:
        state["stage"] = "database-and-build"
        await schema_command(database_url, f'CREATE SCHEMA "{schema}"')
        run_command(
            python,
            "-m",
            "alembic",
            "upgrade",
            "head",
            cwd=BACKEND,
            environment=environment,
        )
        run_command(python, "-m", "app.db.seed", cwd=BACKEND, environment=environment)
        await seed_browser_campus(database_url, schema)
        run_command(
            "node",
            "node_modules/vue-tsc/bin/vue-tsc.js",
            "-b",
            cwd=FRONTEND,
            environment=environment,
        )
        run_command(
            "node",
            "node_modules/vite/bin/vite.js",
            "build",
            cwd=FRONTEND,
            environment=environment,
        )
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        api = subprocess.Popen(
            [
                python,
                "-m",
                "uvicorn",
                "scripts.browser_stage10_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=BACKEND,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=api_log,
            creationflags=flags,
            text=True,
        )
        preview = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                "5173",
                "--strictPort",
            ],
            cwd=FRONTEND,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            text=True,
        )
        try:
            wait_ready(API_URL + "/api/v1/health/ready", api)
        except RuntimeError as exc:
            api_log.flush()
            stderr = api_log_path.read_text(encoding="utf-8")
            raise RuntimeError(f"API did not start: {exc}; {stderr[-1800:]}") from exc
        wait_ready(BASE_URL, preview)
        with urllib.request.urlopen(
            API_URL + "/api/v1/market/categories", timeout=5
        ) as response:
            categories = json.load(response)
        assert any(item["code"] == "books" for item in categories), categories
        try:
            state["stage"] = "core_real"
            results["core_real"] = await asyncio.to_thread(
                real_core_preview, database_url, schema, mail_file
            )
        except Exception as exc:
            api_log.flush()
            tail = api_log_path.read_text(encoding="utf-8")[-2000:]
            raise RuntimeError(
                f"Core browser journey failed: {exc}; API log: {tail}"
            ) from exc
        journeys = (
            ("stage4", "browser_stage4.py"),
            ("stage5_publish", "browser_stage5_publish.py"),
            ("stage5_favorites", "browser_stage5_favorites.py"),
            ("stage6", "browser_stage6.py"),
            ("stage7", "browser_stage7.py"),
            ("stage8", "browser_stage8.py"),
            ("stage9", "browser_stage9.py"),
        )
        for name, filename in journeys:
            state["stage"] = name
            result = subprocess.run(
                [python, str(FRONTEND / "tests" / filename)],
                cwd=FRONTEND,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            results[name] = {
                "exit_code": result.returncode,
                "output_tail": (result.stdout + result.stderr)[-1000:],
            }
            if result.returncode:
                raise RuntimeError(f"{name} browser journey failed: {results[name]}")
        state["stage"] = "responsive"
        results["responsive"] = await asyncio.to_thread(responsive_preview)
        state["stage"] = "auth_ui"
        results["auth_ui"] = await asyncio.to_thread(auth_preview)
        state["stage"] = "journey-screenshots"
        journey_screenshots = {
            "stage5-publish-375.png": "publish-375.png",
            "stage5-favorites-375.png": "favorites-375.png",
            "stage6-chat-mobile.png": "chat-375.png",
            "stage7-buyer-desktop.png": "order-1440.png",
            "stage9-dashboard.png": "admin-1440.png",
        }
        for source, target in journey_screenshots.items():
            shutil.copyfile(FRONTEND / ".tmp" / source, SCREENSHOTS / target)
        results["journey_screenshots"] = [
            str((SCREENSHOTS / target).relative_to(ROOT))
            for target in journey_screenshots.values()
        ]
    finally:
        for process in (preview, api):
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        api_log.close()
        try:
            await schema_command(
                database_url, f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'
            )
        finally:
            temp_dir.cleanup()
    return results


def write_result(state: dict[str, object]) -> None:
    output = ROOT / "docs" / "第十阶段浏览器验收数据.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output)


async def tracked_run() -> None:
    state: dict[str, object] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "stage": "starting",
        "results": {},
    }
    write_result(state)
    try:
        state["results"] = await run(state)
    except BaseException as exc:
        state.update(status="failed", error=f"{type(exc).__name__}: {exc}", exit_code=1)
        write_result(state)
        raise
    state.update(status="passed", stage="complete", exit_code=0)
    state["completed_at_utc"] = datetime.now(UTC).isoformat()
    write_result(state)
    print("STAGE10_BROWSER_OK")


if __name__ == "__main__":
    asyncio.run(tracked_run())
