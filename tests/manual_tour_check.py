"""Browser QA for the tour on an isolated mock-only server and database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from playwright.sync_api import Page, expect, sync_playwright

from modules.onboarding_tour import TOUR_STEPS


OUTPUT = Path("data/qa_output/tour")
PASSWORD = "synthetic-tour-password"


def check_step(page: Page, index: int) -> None:
    """Check that the guide and the actual selected workspace tab agree."""
    step = TOUR_STEPS[index]
    expect(page.locator(".tour-copy h3")).to_have_text(step.title)
    expect(page.get_by_role("tab", name=step.section, exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.locator(".tour-count")).to_have_text(f"{index + 1} / {len(TOUR_STEPS)}")
    expect(page.get_by_test_id("stException")).to_have_count(0)


def check_mobile_layout(page: Page) -> None:
    """Check the guide's controls fit and its text does not overflow."""
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    buttons = page.locator(".st-key-guided_tour button").evaluate_all(
        "buttons => buttons.filter(b => b.getBoundingClientRect().width > 0)"
        ".map(b => { const r = b.getBoundingClientRect(); "
        "return {text: b.innerText, left: r.left, right: r.right, height: r.height, "
        "scroll: b.scrollWidth, client: b.clientWidth}; })"
    )
    fits = all(
        button["left"] >= 0 and button["right"] <= page.viewport_size["width"] + 1
        and button["height"] >= 39.5 and button["scroll"] <= button["client"] + 1
        for button in buttons
    )
    if not fits:
        page.screenshot(path=str(OUTPUT / "mobile_layout_failure.png"))
    assert fits, json.dumps(buttons)
    assert page.locator(".tour-copy").evaluate(
        "e => e.scrollWidth <= e.clientWidth + 1"
    )


def close_mobile_sidebar(page: Page) -> None:
    """Use the native collapse control when a resized sidebar is still expanded."""
    page.wait_for_timeout(400)
    collapse = page.get_by_test_id("stSidebarCollapseButton")
    button = collapse.get_by_role("button")
    box = button.bounding_box() if button.count() else None
    if box and 0 <= box["x"] + box["width"] / 2 <= page.viewport_size["width"]:
        button.click()
    expect(page.locator(".st-key-guided_tour")).to_be_visible()


def sign_in(page: Page, username: str, *, create: bool) -> None:
    """Create or authenticate only synthetic QA accounts."""
    page.get_by_text("Create account" if create else "Log in", exact=True).click()
    page.get_by_label("Username", exact=True).fill(username)
    page.get_by_label("Password", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Continue", exact=True).click()
    expect(page.get_by_role("tab", name="Profile", exact=True)).to_be_attached()


def main() -> None:
    """Verify signup, actual tab switching, both themes, mobile and re-login."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8512")
    url = parser.parse_args().url
    parsed = urlsplit(url)
    if parsed.hostname not in ("localhost", "127.0.0.1") or parsed.port == 8501:
        raise ValueError("Use an isolated local QA server, never the main app.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    username = "tour-browser-" + uuid4().hex[:8]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(30000)
        page.goto(url, wait_until="domcontentloaded")
        expect(page.get_by_text("Offline / mock AI mode", exact=False)).to_be_visible()
        sign_in(page, username, create=True)
        check_step(page, 0)
        page.get_by_label("Full name", exact=True).fill("Tour Example Student")
        page.screenshot(path=str(OUTPUT / "desktop_light.png"))
        page.locator(".st-key-guided_tour").get_by_role("button", name="Next").click()
        check_step(page, 1)
        page.locator(".st-key-guided_tour").get_by_role("button", name="Back").click()
        check_step(page, 0)
        expect(page.get_by_label("Full name", exact=True)).to_have_value(
            "Tour Example Student"
        )

        page.get_by_text("Dark", exact=True).click()
        check_step(page, 0)
        page.screenshot(path=str(OUTPUT / "desktop_dark.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        close_mobile_sidebar(page)
        check_mobile_layout(page)
        page.screenshot(path=str(OUTPUT / "mobile_dark.png"))
        for index in range(1, len(TOUR_STEPS)):
            page.locator(".st-key-guided_tour").get_by_role("button", name="Next").click()
            check_step(page, index)
            check_mobile_layout(page)
        page.locator(".st-key-guided_tour").get_by_role(
            "button", name="Start my profile"
        ).click()
        expect(page.locator(".st-key-guided_tour")).to_have_count(0)
        expect(page.get_by_role("tab", name="Profile", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        print("Real signup, Back/Next, all eight selected tabs and completion passed.")

        page.reload(wait_until="domcontentloaded")
        sign_in(page, username, create=False)
        expect(page.locator(".st-key-guided_tour")).to_have_count(0)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Quick tour").click()
        check_step(page, 0)
        page.set_viewport_size({"width": 360, "height": 800})
        close_mobile_sidebar(page)
        check_mobile_layout(page)
        page.screenshot(path=str(OUTPUT / "mobile_light.png"))
        page.get_by_label("Full name", exact=True).fill("First Account Private Draft")
        page.locator(".st-key-guided_tour").get_by_role("button", name="Skip tour").click()
        expect(page.locator(".st-key-guided_tour")).to_have_count(0)

        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Log out", exact=True).click()
        sign_in(page, "tour-browser-second-" + uuid4().hex[:8], create=True)
        check_step(page, 0)
        expect(page.get_by_label("Full name", exact=True)).to_have_value("")
        expect(page.get_by_test_id("stException")).to_have_count(0)
        print("Re-login, replay, skip, second-account isolation and responsive checks passed.")
        print(f"Screenshots: {OUTPUT.resolve()}")
        browser.close()


if __name__ == "__main__":
    main()
