"""Stage 5 favorite browser smoke; run while Vite is available locally."""

import base64
import json
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

BASE_URL = "http://127.0.0.1:5173"
OUTPUT = Path(__file__).parents[1] / ".tmp"
PRODUCT_ID = "44444444-4444-4444-8444-444444444444"
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def summary() -> dict[str, object]:
    return {
        "id": PRODUCT_ID,
        "title": "高等数学教材",
        "price": "18.50",
        "status": "on_sale",
        "published_at": "2026-09-19T08:00:00Z",
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
    }


def detail() -> dict[str, object]:
    return {
        **summary(),
        "description": "有少量课堂笔记，页面完整，没有缺页和明显污损。",
        "seller": {
            "id": "77777777-7777-4777-8777-777777777777",
            "display_name": "小林",
            "campus_verified": True,
            "review_count": 2,
            "average_rating": "4.50",
            "completed_orders": 3,
        },
        "images": [
            {
                "id": "66666666-6666-4666-8666-666666666666",
                "url": "/api/v1/market/product-images/66666666-6666-4666-8666-666666666666",
                "alt_text": "教材封面",
            }
        ],
        "similar_products": [],
    }


def fulfill_json(route: Route, payload: object) -> None:
    route.fulfill(content_type="application/json", body=json.dumps(payload, ensure_ascii=False))


def run() -> None:
    OUTPUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        for width in (375, 768, 1024, 1440):
            page = browser.new_page(viewport={"width": width, "height": 900})
            favorited = {"value": False}
            console_errors: list[str] = []
            failed_responses: list[str] = []
            page.on(
                "console",
                lambda message: console_errors.append(message.text)
                if message.type == "error"
                else None,
            )
            page.on(
                "response",
                lambda response: failed_responses.append(f"{response.status} {response.url}")
                if response.status >= 400
                else None,
            )

            def api(route: Route) -> None:
                request = route.request
                url = request.url
                if url.endswith("/api/v1/auth/refresh"):
                    fulfill_json(
                        route,
                        {
                            "access_token": "browser-token",
                            "access_token_expires_at": "2026-09-19T09:00:00Z",
                            "token_type": "bearer",
                            "user": {
                                "id": "11111111-1111-4111-8111-111111111111",
                                "login_email": "buyer@example.edu",
                                "display_name": "测试买家",
                                "status": "active",
                                "campus_verification_status": "verified",
                            },
                        },
                    )
                elif url.endswith(f"/api/v1/market/products/{PRODUCT_ID}"):
                    fulfill_json(route, detail())
                elif "/api/v1/market/product-images/" in url:
                    route.fulfill(content_type="image/png", body=PIXEL)
                elif url.endswith(f"/api/v1/favorites/{PRODUCT_ID}") and request.method == "GET":
                    fulfill_json(
                        route,
                        {"favorited": favorited["value"], "favorite_count": 3 if favorited["value"] else 2},
                    )
                elif url.endswith(f"/api/v1/favorites/{PRODUCT_ID}") and request.method == "PUT":
                    favorited["value"] = True
                    fulfill_json(route, {"favorited": True, "favorite_count": 3})
                elif url.endswith("/api/v1/favorites"):
                    fulfill_json(
                        route,
                        {"items": [summary()], "total": 1, "page": 1, "page_size": 1},
                    )
                else:
                    route.continue_()

            page.route("**/api/v1/**", api)
            page.goto(f"{BASE_URL}/products/{PRODUCT_ID}", wait_until="networkidle")
            page.get_by_role("button", name="收藏 · 2").click()
            page.get_by_role("button", name="取消收藏 · 3").wait_for()
            page.goto(f"{BASE_URL}/favorites", wait_until="networkidle")
            page.get_by_role("heading", name="我的收藏").wait_for()
            page.get_by_text("高等数学教材", exact=True).wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=OUTPUT / f"stage5-favorites-{width}.png", full_page=True)
            assert not console_errors, console_errors
            assert not failed_responses, failed_responses
            page.close()
        browser.close()


if __name__ == "__main__":
    run()
