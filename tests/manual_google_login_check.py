"""Check the unconfigured Google sign-in screen on an isolated QA server."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    """Review both themes at desktop/mobile sizes, without calling Google."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8514")
    url = parser.parse_args().url
    parsed = urlsplit(url)
    if parsed.hostname not in ("localhost", "127.0.0.1") or parsed.port == 8501:
        raise ValueError("Use an isolated QA server, never the main app.")
    output = Path("data/qa_output/google-login")
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        expect.set_options(timeout=30000)
        browser = playwright.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        for theme in ("Light", "Dark"):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1100}, reduced_motion="reduce",
            )
            page = context.new_page()
            page.set_default_timeout(30000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url, wait_until="domcontentloaded")
            google_button = page.locator(".st-key-google_sign_in").get_by_role("button")
            expect(google_button).to_be_visible()
            expect(google_button).to_contain_text("Continue with Google")
            page.get_by_text(theme, exact=True).click()
            page.wait_for_timeout(300)
            expect(page.get_by_role("button", name="Stop", exact=True)).to_have_count(0)
            for device, size in (
                ("desktop", {"width": 1440, "height": 1100}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                page.set_viewport_size(size)
                page.wait_for_timeout(500)
                if device == "mobile":
                    sidebar = page.get_by_test_id("stSidebar")
                    collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
                    if sidebar.get_attribute("aria-expanded") == "true":
                        collapse.click()
                    expect(sidebar).to_have_attribute("aria-expanded", "false")
                button = page.locator(".st-key-google_sign_in").get_by_role("button")
                expect(button).to_be_visible()
                expect(button).to_be_disabled()
                expect(page.get_by_role("button", name="Continue", exact=True)).to_be_enabled()
                expect(page.get_by_label("Username", exact=True)).to_be_visible()
                expect(page.get_by_test_id("stException")).to_have_count(0)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert button.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
                page.screenshot(path=str(output / f"{device}-{theme.lower()}.png"), full_page=True)
            assert not errors, errors
            context.close()
        browser.close()
    print("Google sign-in UI: desktop/mobile, light/dark, layout and password controls passed.")


if __name__ == "__main__":
    main()
