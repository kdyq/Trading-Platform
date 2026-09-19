"""Stage 4 real-browser smoke test; run while API and Vite are available locally."""

import base64
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT = Path(__file__).parents[1] / ".tmp"
PRODUCT_ID = "11111111-1111-4111-8111-111111111111"
PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def product_fixture(status: str = "on_sale") -> dict[str, object]:
    return {
        "id": PRODUCT_ID,
        "title": "高等数学教材",
        "price": "18.50",
        "status": status,
        "published_at": "2026-09-14T08:00:00Z",
        "campus_name": "东校区",
        "school_name": "测试大学",
        "seller_name": "小林",
        "seller_verified": True,
        "category_code": "books",
        "category_name": "教材书籍",
        "condition": "good",
        "is_negotiable": True,
        "view_count": 12,
        "favorite_count": 2,
        "image_url": None,
        "image_alt": None,
        "description": "少量笔记，无缺页。",
        "seller": {
            "id": "22222222-2222-4222-8222-222222222222",
            "display_name": "小林",
            "campus_verified": True,
            "review_count": 2,
            "average_rating": "4.50",
            "completed_orders": 3,
        },
        "images": [
            {
                "id": "33333333-3333-4333-8333-333333333333",
                "url": "/api/v1/market/product-images/33333333-3333-4333-8333-333333333333",
                "alt_text": "教材封面",
            },
            {
                "id": "44444444-4444-4444-8444-444444444444",
                "url": "/api/v1/market/product-images/44444444-4444-4444-8444-444444444444",
                "alt_text": "教材内页",
            },
        ],
        "similar_products": [],
    }


def run() -> None:
    OUTPUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height in ((375, 812), (768, 1024), (1024, 900), (1440, 1000)):
            page = browser.new_page(viewport={"width": width, "height": height})
            console_errors: list[str] = []
            failed_responses: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error" and "401" not in message.text
                else None,
            )
            page.on(
                "response",
                lambda response: failed_responses.append(f"{response.status} {response.url}")
                if response.status >= 400
                and not (response.status == 401 and "/auth/refresh" in response.url)
                else None,
            )
            page.goto("http://127.0.0.1:5173/", wait_until="networkidle")
            page.get_by_role("heading", name="闲置好物，换个主人继续发光").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=OUTPUT / f"stage4-home-{width}.png", full_page=True)

            page.goto(
                "http://127.0.0.1:5173/market?keyword=教材&category=books&condition=good",
                wait_until="networkidle",
            )
            page.get_by_role("heading", name="找到今天想带走的好物").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            if width <= 768:
                page.get_by_role("button", name="筛选商品").click()
                dialog = page.get_by_role("dialog", name="筛选商品")
                dialog.wait_for()
                assert dialog.locator("#mobile-filter-category").input_value() == "books"
                page.keyboard.press("Escape")
                assert dialog.count() == 0
            else:
                assert page.locator("#desktop-filter-category").input_value() == "books"
                page.locator("#desktop-filter-condition").select_option("like_new")
                page.get_by_role("button", name="应用筛选").click()
                page.wait_for_url("**condition=like_new**")
                page.go_back(wait_until="networkidle")
                assert page.locator("#desktop-filter-condition").input_value() == "good"
            page.screenshot(path=OUTPUT / f"task3-market-{width}.png", full_page=True)

            page.route(
                f"**/api/v1/market/products/{PRODUCT_ID}",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(product_fixture()),
                ),
            )
            page.route(
                "**/api/v1/market/product-images/*",
                lambda route: route.fulfill(
                    status=200,
                    content_type="image/png",
                    body=PIXEL_PNG,
                ),
            )
            page.goto(f"http://127.0.0.1:5173/products/{PRODUCT_ID}", wait_until="networkidle")
            page.get_by_role("heading", name="高等数学教材").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            gallery = page.locator(".product-gallery-stage")
            gallery.focus()
            page.keyboard.press("ArrowRight")
            box = gallery.bounding_box()
            assert box is not None and abs(box["width"] / box["height"] - 4 / 3) < 0.03
            page.get_by_role("button", name="联系卖家 / 发起交易").click()
            page.get_by_role("dialog", name="登录后继续").wait_for()
            page.keyboard.press("Escape")
            page.screenshot(path=OUTPUT / f"task4-detail-{width}.png", full_page=True)

            page.goto("http://127.0.0.1:5173/campus-verification", wait_until="networkidle")
            page.wait_for_url("**/login")
            page.get_by_role("heading", name="登录拾光集市").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=OUTPUT / f"stage4-campus-entry-{width}.png", full_page=True)
            assert not console_errors, console_errors
            assert not failed_responses, failed_responses
            page.close()
        browser.close()


if __name__ == "__main__":
    run()
