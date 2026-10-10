"""Conditional fields, progress fidelity, safe insights and opportunity states."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from streamlit.testing.v1 import AppTest

from modules.dashboard_ui import progress_figure, progress_points
from modules.digital_twin import skill_radar_points
from modules.market_research import sources_from_tools, validate_openings
from modules.market_ui import job_search_links
from modules.ui import theme_colors
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def render_app(db, open_session, ctx, monkeypatch) -> AppTest:
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    with open_session() as session:
        twin = empty_twin("Workspace Test Student")
        twin["profile"].update(
            degree="Software Engineering", education_level="Undergraduate (Year 2)"
        )
        TwinRepository(session).save_twin(ctx, twin)
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    app.session_state["logged_in"] = True
    app.session_state["user_id"] = ctx.user_id
    app.session_state["ai_force_mock"] = True
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    return app


def test_other_inputs_appear_only_when_selected(
    db, open_session, ctx_a, monkeypatch
) -> None:
    app = render_app(db, open_session, ctx_a, monkeypatch)
    assert not any(f.label == "Program / Degree / Track" for f in app.text_input)
    assert not any(f.label == "Subject 1" for f in app.text_input)
    assert not any(f.label == "Other semester subject 1" for f in app.text_input)
    next(f for f in app.selectbox if f.label == "Degree / program").set_value(
        "Other"
    ).run()
    assert any(f.label == "Program / Degree / Track" for f in app.text_input)
    next(f for f in app.selectbox if f.label == "Subject choice 1").set_value(
        "Other"
    ).run()
    assert any(f.label == "Subject 1" for f in app.text_input)
    next(f for f in app.selectbox if f.label == "Semester subject 1").set_value(
        "Other"
    ).run()
    assert any(f.label == "Other semester subject 1" for f in app.text_input)
    next(f for f in app.selectbox if f.label == "Semester subject 1").set_value(
        "Programming Fundamentals"
    ).run()
    assert not any(f.label == "Other semester subject 1" for f in app.text_input)
    next(f for f in app.selectbox if f.label == "Field of study").set_value(
        "Other / interdisciplinary"
    ).run()
    assert any(f.label == "Other field of study" for f in app.text_input)
    assert not app.exception


def test_theme_and_readable_insights_survive_reruns(
    db, open_session, ctx_a, monkeypatch
) -> None:
    app = render_app(db, open_session, ctx_a, monkeypatch)
    next(f for f in app.radio if f.label == "Appearance").set_value("Dark").run()
    assert app.session_state["ui_theme"] == "Dark"
    assert any("--tc-bg:#25292e" in item.value for item in app.markdown)
    next(b for b in app.button if b.label == "Generate Twin Insights").click().run()
    assert not app.exception
    assert not app.get("json")
    assert any(
        "Strengths" in item.value and "insight-heading" in item.value
        for item in app.markdown
    )
    assert app.get("plotly_chart")
    app.run()
    assert app.session_state["ui_theme"] == "Dark"
    next(f for f in app.radio if f.label == "Appearance").set_value("Light").run()
    assert app.session_state["ui_theme"] == "Light"


def test_saving_known_program_preserves_the_students_actual_degree_label(
    db, open_session, ctx_a, monkeypatch
) -> None:
    app = render_app(db, open_session, ctx_a, monkeypatch)
    with open_session() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx_a)
        twin["profile"]["degree"] = "B.S. Software Engineering"
        repo.save_twin(ctx_a, twin)
    app.run()
    next(b for b in app.button if b.label == "Save twin & analyze").click().run()
    assert not app.exception
    with open_session() as session:
        assert (
            TwinRepository(session).get_twin(ctx_a)["profile"]["degree"]
            == "B.S. Software Engineering"
        )


def test_jobs_have_search_actions_and_visible_role_matches_without_live_api(
    db, open_session, ctx_a, monkeypatch
) -> None:
    app = render_app(db, open_session, ctx_a, monkeypatch)
    assert any("No live search yet" in item.value for item in app.info)
    assert any(
        "Learning references, not advertised vacancies" in item.value
        for item in app.caption
    )
    links = app.get("link_button")
    assert any(link.proto.label == "LinkedIn openings" for link in links)
    assert sum(metric.label == "Skill coverage" for metric in app.metric) >= 1


def test_progress_chart_contains_only_recorded_totals_and_keeps_missing_grades() -> (
    None
):
    now = datetime.now(timezone.utc)
    first = empty_twin("Progress Student")
    latest = empty_twin("Progress Student")
    latest["skills"] = [{"name": "Python", "proficiency": 60}]
    latest["progress_events"] = [{"title": "Finished a practice task"}]
    snapshots = [
        {
            "version": 2,
            "created_at": now.isoformat(),
            "label": "task_completed",
            "twin": latest,
        },
        {
            "version": 1,
            "created_at": (now - timedelta(days=40)).isoformat(),
            "label": "created",
            "twin": first,
        },
    ]
    points = progress_points(snapshots)
    assert [p["completed_milestones"] for p in points] == [0, 1]
    assert [p["skill_count"] for p in points] == [0, 1]
    assert [p["average_score"] for p in points] == [None, None]
    assert len(progress_points(snapshots, 30)) == 1
    figure = progress_figure(points, "Milestones", theme_colors("Dark"))
    assert list(figure.data[0].y) == [0, 1]
    assert (
        len(
            progress_figure(points, "Academic average", theme_colors("Light")).data[0].y
        )
        == 0
    )


def test_job_links_are_location_scoped_and_do_not_include_private_details() -> None:
    profile = {
        "name": "PRIVATE_NAME",
        "degree": "Nursing",
        "university_city": "Karachi",
        "country": "Pakistan",
        "career_goals": ["Nurse"],
        "national_id": "PRIVATE_IDENTIFIER",
    }
    links = job_search_links(profile)
    assert "PRIVATE" not in str(links)
    assert parse_qs(urlsplit(links[0][1]).query)["location"] == ["Karachi, Pakistan"]
    assert "Nurse" in links[1][1]


def test_radar_does_not_turn_zero_or_unknown_proficiency_into_fifty_percent() -> None:
    twin = empty_twin("Radar Student")
    twin["skills"] = [{"name": "Python", "proficiency": 0}, {"name": "SQL"}]
    assert [point["value"] for point in skill_radar_points(twin)] == [0, 0]


def test_individual_source_pages_are_prioritized_and_punctuation_is_not_a_false_rejection() -> (
    None
):
    articles = [
        {
            "url": f"https://example.org/article/{i}",
            "title": "Career guide",
            "content": "General advice",
        }
        for i in range(7)
    ]
    listing = {
        "url": "https://example.org/jobs/python-intern",
        "title": "Python - Intern",
        "content": "Python - Intern. Requires Python &amp; SQL. Example Company, Karachi.",
    }
    sources = sources_from_tools(
        [{"search_results": {"results": articles + [listing]}}]
    )
    assert sources[0]["url"] == listing["url"]
    opening = {
        "source_id": sources[0]["id"],
        "title": "Python Intern",
        "required_skills": ["Python", "SQL", "UnstatedSkill"],
        "company": "Example Company",
        "location": "Karachi",
        "evidence_quote": listing["content"],
    }
    jobs = validate_openings([opening], sources)
    assert len(jobs) == 1 and jobs[0]["required_skills"] == ["Python", "SQL"]
    opening["title"] = "Invented senior role"
    assert not validate_openings([opening], sources)
