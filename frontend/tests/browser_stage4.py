"""Stage 4 real-browser smoke test; run while API and Vite are available locally."""

from pathlib import Path

from playwright.sync_api import sync_playwright


OUTPUT = Path(__file__).parents[1] / ".tmp"


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
            page.goto(
                "http://127.0.0.1:5173/market?category=books&condition=good",
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
            assert not console_errors, console_errors
            assert not failed_responses, failed_responses
            page.close()
        browser.close()


if __name__ == "__main__":
    run()
