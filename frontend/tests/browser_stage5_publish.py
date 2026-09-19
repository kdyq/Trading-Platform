"""Stage 5 seller publishing browser smoke; run while Vite is available locally."""

import base64
import json
from pathlib import Path

from playwright.sync_api import Route, sync_playwright

BASE_URL = "http://127.0.0.1:5173"
OUTPUT = Path(__file__).parents[1] / ".tmp"
USER_ID = "11111111-1111-4111-8111-111111111111"
CAMPUS_ID = "22222222-2222-4222-8222-222222222222"
CATEGORY_ID = "33333333-3333-4333-8333-333333333333"
PRODUCT_ID = "44444444-4444-4444-8444-444444444444"
UPLOAD_ID = "55555555-5555-4555-8555-555555555555"
IMAGE_ID = "66666666-6666-4666-8666-666666666666"
PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def product(status: str, version: int, with_image: bool) -> dict[str, object]:
    images = (
        [
            {
                "id": IMAGE_ID,
                "url": f"/api/v1/seller/products/{PRODUCT_ID}/images/{IMAGE_ID}",
                "thumbnail_url": (
                    f"/api/v1/seller/products/{PRODUCT_ID}/images/{IMAGE_ID}/thumbnail"
                ),
                "alt_text": "高等数学教材",
                "display_order": 0,
            }
        ]
        if with_image
        else []
    )
    return {
        "id": PRODUCT_ID,
        "title": "高等数学教材",
        "description": "有少量课堂笔记，页面完整，没有缺页和明显污损。",
        "price": "18.50",
        "original_price": "49.00",
        "category_id": CATEGORY_ID,
        "campus_id": CAMPUS_ID,
        "condition": "good",
        "is_negotiable": True,
        "delivery_notes": "工作日傍晚东门自提",
        "status": status,
        "version": version,
        "updated_at": "2026-09-19T08:00:00Z",
        "images": images,
    }


def fulfill_json(route: Route, payload: object, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload, ensure_ascii=False),
    )


def run() -> None:
    OUTPUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        for width in (375, 768, 1024, 1440):
            page = browser.new_page(viewport={"width": width, "height": 900})
            console_errors: list[str] = []
            failed_responses: list[str] = []
            state = {"version": 1, "with_image": False, "status": "draft"}
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
                                "id": USER_ID,
                                "login_email": "student@example.edu",
                                "display_name": "测试同学",
                                "status": "active",
                                "campus_verification_status": "verified",
                            },
                        },
                    )
                elif url.endswith("/api/v1/catalog/categories"):
                    fulfill_json(
                        route,
                        [
                            {
                                "id": CATEGORY_ID,
                                "code": "books",
                                "slug": "books",
                                "name": "教材书籍",
                                "display_order": 0,
                                "children": [],
                            }
                        ],
                    )
                elif url.endswith("/api/v1/campus/status"):
                    fulfill_json(
                        route,
                        {
                            "status": "verified",
                            "verification_id": "verification",
                            "campus_id": CAMPUS_ID,
                            "campus_email": "student@example.edu",
                            "verified_at": "2026-09-01T00:00:00Z",
                            "expires_at": "2027-09-01T00:00:00Z",
                            "appeal": None,
                        },
                    )
                elif url.endswith("/api/v1/product-images/uploads"):
                    fulfill_json(
                        route,
                        {
                            "id": UPLOAD_ID,
                            "original_filename": "book.png",
                            "media_type": "image/png",
                            "size_bytes": len(PIXEL),
                            "width": 1,
                            "height": 1,
                            "expires_at": "2026-09-20T08:00:00Z",
                            "preview_url": f"/api/v1/product-images/uploads/{UPLOAD_ID}/preview",
                        },
                        201,
                    )
                elif "/images/" in url:
                    route.fulfill(status=200, content_type="image/png", body=PIXEL)
                elif url.endswith("/api/v1/seller/products") and request.method == "POST":
                    fulfill_json(route, product("draft", 1, False), 201)
                elif url.endswith(f"/api/v1/seller/products/{PRODUCT_ID}") and request.method == "PATCH":
                    state["version"] += 1
                    state["with_image"] = True
                    fulfill_json(
                        route,
                        product(str(state["status"]), int(state["version"]), True),
                    )
                elif url.endswith(f"/api/v1/seller/products/{PRODUCT_ID}/submit"):
                    state["version"] += 1
                    state["status"] = "pending_review"
                    fulfill_json(
                        route,
                        product("pending_review", int(state["version"]), True),
                    )
                elif url.endswith("/api/v1/seller/products") and request.method == "GET":
                    fulfill_json(
                        route,
                        {
                            "items": [
                                product(
                                    str(state["status"]),
                                    int(state["version"]),
                                    bool(state["with_image"]),
                                )
                            ]
                        },
                    )
                else:
                    route.continue_()

            page.route("**/api/v1/**", api)
            page.goto(f"{BASE_URL}/sell", wait_until="networkidle")
            page.get_by_role("heading", name="发布一件校园好物").wait_for()
            page.get_by_label("商品标题").fill("高等数学教材")
            page.get_by_label("详细描述").fill(
                "有少量课堂笔记，页面完整，没有缺页和明显污损。"
            )
            page.get_by_label("售价").fill("18.50")
            page.get_by_label("原价（可选）").fill("49.00")
            page.get_by_role("button", name="下一步").click()
            page.locator('input[type="file"]').set_input_files(
                {"name": "book.png", "mimeType": "image/png", "buffer": PIXEL}
            )
            page.get_by_label("交付说明").fill("工作日傍晚东门自提")
            page.get_by_label("接受合理议价").check()
            page.get_by_role("button", name="下一步").click()
            page.get_by_role("button", name="提交审核").click()
            page.wait_for_url("**/my-products")
            page.get_by_text("待审核", exact=True).wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=OUTPUT / f"stage5-publish-{width}.png", full_page=True)
            assert not console_errors, console_errors
            assert not failed_responses, failed_responses
            page.close()
        browser.close()


if __name__ == "__main__":
    run()
