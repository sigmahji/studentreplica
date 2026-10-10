"""Visual QA against an isolated server; only synthetic student data is used."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from uuid import uuid4

from playwright.sync_api import Page, sync_playwright
from sqlalchemy import select

from ai.client import MockClient
from ai.service import AIService
from modules.digital_twin import build_twin_from_onboarding
from storage.auth import create_account
from storage.context import UserContext
from storage.database import init_db, session_scope
from storage.models import TwinSnapshot
from storage.repository import TwinRepository

QA_DB = "sqlite:///D:/ST_Replica/studentreplica/data/qa_ui_review.db"
OUTPUT = Path("data/qa_output")


def verify_branding(page: Page) -> None:
    """Check the real page title, favicon and responsive logo lockups."""
    assert page.title() == "StudentReplica"
    assert page.locator(".app-brand .brand-word").inner_text() == "StudentReplica"
    assert page.locator(".sidebar-brand .brand-word").inner_text() == "StudentReplica"
    assert page.locator(".brand-logo").evaluate_all(
        "images => images.length === 2 && images.every(i => i.complete && i.naturalWidth > 0)"
    )
    assert page.locator(".brand-lockup").evaluate_all(
        "elements => elements.every(e => { const r = e.getBoundingClientRect(); "
        "if (r.right <= 0 || r.left >= innerWidth) return true; "
        "const icon = e.querySelector('img').getBoundingClientRect(); "
        "const word = e.querySelector('.brand-word').getBoundingClientRect(); "
        "return icon.right < word.left && word.right <= innerWidth; })"
    )
    href = page.locator('link[rel*="icon"]').first.get_attribute("href")
    assert href
    response = page.request.get(urljoin(page.url, href))
    assert response.status == 200
    assert response.body().startswith(b"\x89PNG")


def seed_review_student() -> tuple[str, str]:
    """Create an isolated test account and an explicitly synthetic progress history."""
    username = "visual-review-" + uuid4().hex[:8]
    password = "synthetic-review-password"
    init_db(QA_DB)
    with session_scope(QA_DB) as session:
        result = create_account(
            session, username=username, password=password, display_name="Sam Example"
        )
        ctx = UserContext(user_id=result.user_id, session_id="visual-review")
        twin = build_twin_from_onboarding(
            name="Sam Example",
            education_level="Undergraduate (Year 2)",
            institution="Example University",
            degree="Software Engineering",
            interests=["Backend development"],
            career_goals=["Software Engineer"],
            subjects=[
                {"name": "Programming Fundamentals", "grade": "86"},
                {"name": "Database Systems", "grade": "58"},
            ],
            skills=[
                {"name": "Python", "proficiency": 70},
                {"name": "SQL", "proficiency": 55},
                {"name": "Git", "proficiency": 65},
            ],
            study_habits=["Daily practice"],
            profile_details={
                "city": "Karachi",
                "country": "Pakistan",
                "field_of_study": "Computing & IT",
            },
        )
        repo = TwinRepository(session)
        titles = [
            "Completed Python functions practice",
            "Built a SQL revision notebook",
            "Finished a Git branching exercise",
            "Reviewed database normalization",
            "Submitted a small API project",
        ]
        for index in range(6):
            if index:
                twin["progress_events"].append(
                    {
                        "title": titles[index - 1],
                        "completed_on": (
                            datetime.now(timezone.utc) - timedelta(days=6 - index)
                        )
                        .date()
                        .isoformat(),
                        "verification": "student_reported",
                        "task_id": f"qa-{index}",
                    }
                )
            repo.save_twin(ctx, twin, label="synthetic_practice_progress")
        snapshots = session.scalars(
            select(TwinSnapshot)
            .where(TwinSnapshot.user_id == ctx.user_id)
            .order_by(TwinSnapshot.version)
        ).all()
        for index, snapshot in enumerate(snapshots):
            snapshot.created_at = datetime.now(timezone.utc) - timedelta(days=6 - index)
        AIService(client=MockClient(record_prompts=False)).generate_twin_insights(
            session, ctx
        )
    return username, password


def main() -> None:
    """Capture both themes, responsive layouts, dropdowns and rendered chart pixels."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    username, password = seed_review_student()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        page = browser.new_page(
            viewport={"width": 1440, "height": 1050}, device_scale_factor=1
        )
        page.goto("http://localhost:8510", wait_until="networkidle")
        page.get_by_text("Log in", exact=True).click()
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Continue", exact=True).click()
        page.get_by_role("tab", name="Dashboard", exact=True).wait_for(timeout=30000)
        page.wait_for_timeout(2500)
        verify_branding(page)
        page.screenshot(path=str(OUTPUT / "dashboard_light.png"), full_page=True)
        page.locator(".insight-heading").first.scroll_into_view_if_needed()
        page.screenshot(path=str(OUTPUT / "insights_light.png"), full_page=True)
        page.get_by_role(
            "tab", name="Dashboard", exact=True
        ).scroll_into_view_if_needed()
        assert page.locator(".js-plotly-plot .scatterlayer path").count() > 0
        assert page.locator(".insight-heading").count() == 3
        assert page.get_by_test_id("stJson").count() == 0
        metrics = page.get_by_test_id("stMetricValue").evaluate_all(
            "els => els.filter(e => e.getBoundingClientRect().width > 0).map(e => ({text: e.innerText, x:e.getBoundingClientRect().x, width:e.getBoundingClientRect().width, scroll:e.scrollWidth}))"
        )
        print("Visible dashboard metrics:", metrics)
        page.get_by_text("Dark", exact=True).click()
        page.wait_for_timeout(2000)
        assert (
            page.get_by_test_id("stApp").evaluate(
                "e => getComputedStyle(e).backgroundColor"
            )
            == "rgb(37, 41, 46)"
        )
        page.screenshot(path=str(OUTPUT / "dashboard_dark.png"), full_page=True)
        verify_branding(page)
        page.get_by_role("tab", name="Jobs", exact=True).click()
        page.screenshot(path=str(OUTPUT / "jobs_dark.png"), full_page=True)
        assert page.get_by_text(
            "Learning references, not advertised vacancies.", exact=False
        ).is_visible()
        page.get_by_text("Light", exact=True).click()
        page.wait_for_timeout(1500)
        page.get_by_role("tab", name="Profile", exact=True).click()
        assert page.get_by_label("Program / Degree / Track", exact=True).count() == 0
        page.get_by_test_id("stSelectbox").filter(
            has_text="Degree / program"
        ).get_by_role("combobox").fill("Other")
        page.get_by_role("option", name="Other", exact=True).click()
        page.get_by_label("Program / Degree / Track", exact=True).wait_for()
        page.get_by_test_id("stSelectbox").filter(
            has_text="Degree / program"
        ).get_by_role("combobox").fill("Software Engineering")
        page.get_by_role("option", name="Software Engineering", exact=True).click()
        page.wait_for_timeout(1000)
        assert page.get_by_label("Program / Degree / Track", exact=True).count() == 0
        page.get_by_role("tab", name="Semesters", exact=True).click()
        assert page.get_by_label("Other semester subject 1", exact=True).count() == 0
        page.get_by_test_id("stSelectbox").filter(
            has_text="Semester subject 1"
        ).get_by_role("combobox").fill("Other")
        page.get_by_role("option", name="Other", exact=True).click()
        page.get_by_label("Other semester subject 1", exact=True).wait_for()
        page.screenshot(path=str(OUTPUT / "semester_conditional.png"), full_page=True)
        page.get_by_role("tab", name="Dashboard", exact=True).click()
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(1500)
        collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
        box = collapse.bounding_box() if collapse.count() else None
        if box and 0 <= box["x"] < 390:
            collapse.click()
        page.wait_for_timeout(500)
        verify_branding(page)
        page.screenshot(path=str(OUTPUT / "dashboard_mobile.png"), full_page=True)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth + 2"
        )
        page.get_by_role("tab", name="Jobs", exact=True).click()
        page.screenshot(path=str(OUTPUT / "jobs_mobile.png"), full_page=True)
        assert page.get_by_test_id("stException").count() == 0
        browser.close()
    print("Desktop/mobile visual review completed using synthetic data only.")


if __name__ == "__main__":
    main()
