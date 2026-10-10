"""Optional visual QA: run against an isolated mock-mode server, never production."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from playwright.sync_api import sync_playwright
from PIL import Image
import pypdfium2

from modules.cv_exports import cv_facts, export_docx, export_pdf, sanitize_photo
from storage.twin_schema import empty_twin


def main() -> None:
    """Capture desktop/mobile screens and a synthetic CV, without real student data."""
    output = Path("data/qa_output")
    output.mkdir(parents=True, exist_ok=True)
    twin = empty_twin("Sam Example")
    twin["profile"].update(
        degree="Software Engineering",
        institution="Example University",
        education_level="Undergraduate (Year 2)",
        city="Karachi",
        country="Pakistan",
    )
    twin["skills"] = [
        {"name": "Python", "evidence": "Student-confirmed"},
        {"name": "SQL", "evidence": "Student-confirmed"},
    ]
    twin["projects"] = [
        {
            "name": "Course Planner",
            "description": "Built a semester planning project using Python and SQL.",
            "evidence": "Student-reported project",
        }
    ]
    twin["learning_courses"] = [
        {
            "title": "Introduction to Programming",
            "skill": "Python",
            "status": "passed",
            "assessment_offline": False,
            "passed_at": "2026-10-10",
            "attempts": [{"passed": True, "practice_only": False, "score": 80}],
            "url": "https://cs50.harvard.edu/python/",
        }
    ]
    raw = BytesIO()
    Image.new("RGB", (600, 750), (32, 133, 118)).save(raw, format="PNG")
    photo = sanitize_photo(raw.getvalue())
    facts = cv_facts(twin)
    for label, image in (("no_photo", None), ("photo", photo)):
        (output / f"cv_{label}.pdf").write_bytes(export_pdf(twin, facts, image))
        (output / f"cv_{label}.docx").write_bytes(export_docx(twin, facts, image))
        pdf = pypdfium2.PdfDocument(output / f"cv_{label}.pdf")
        for index in range(len(pdf)):
            pdf[index].render(scale=1.6).to_pil().save(
                output / f"cv_{label}_{index + 1}.png"
            )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
        )
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000}, device_scale_factor=1
        )
        page.goto("http://localhost:8510", wait_until="networkidle")
        page.get_by_role("tab", name="Quick demo (no password)").click()
        page.get_by_role("button", name="Demo student A (SE)", exact=True).click()
        try:
            page.get_by_role("tab", name="Semesters", exact=True).wait_for(
                timeout=30000
            )
        except Exception:
            page.screenshot(path=str(output / "browser_failure.png"), full_page=True)
            print(
                page.locator("body")
                .inner_text()[:3000]
                .encode("ascii", "backslashreplace")
                .decode()
            )
            raise
        page.get_by_role("tab", name="Semesters", exact=True).click()
        page.screenshot(path=str(output / "semesters_desktop.png"), full_page=True)
        page.get_by_role("tab", name="Learning", exact=True).click()
        page.screenshot(path=str(output / "learning_desktop.png"), full_page=True)
        page.get_by_role("tab", name="CV Studio", exact=True).click()
        page.get_by_role("button", name="Download PDF", exact=True).wait_for()
        page.screenshot(path=str(output / "cv_desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "cv_mobile.png"), full_page=True)
        page.get_by_role("tab", name="Learning", exact=True).click()
        page.screenshot(path=str(output / "learning_mobile.png"), full_page=True)
        assert page.get_by_test_id("stException").count() == 0
        print("Visual QA saved to data/qa_output; no Streamlit exceptions.")
        browser.close()


if __name__ == "__main__":
    main()
