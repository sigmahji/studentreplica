"""Career planning constraints, evidence grounding, and cross-student isolation."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from io import BytesIO

import pytest

from ai.client import MockClient
from ai.schemas import StudentCareerPlan
from ai.service import AIService
from modules.career_planner import (
    WEEKDAYS, confirm_learning_choices, progress_summary,
    rank_career_references, record_task_completion, schedule_career_plan,
)
from modules.digital_twin import build_twin_from_onboarding
from modules.market_matcher import get_local_job_catalog
from modules.market_research import research_local_market
from storage.repository import TwinRepository


def _twin(name: str = "HealthStudent", city: str = "Karachi") -> dict:
    return build_twin_from_onboarding(
        name=name, education_level="Undergraduate (Year 2)", institution="Test University",
        degree="BSc Nursing", interests=["Patient care"], career_goals=["Nursing"],
        subjects=[{"name": "Anatomy", "grade": 82}, {"name": "Patient Communication", "grade": 72}],
        profile_details={"field_of_study": "Health & Medicine", "city": city, "country": "Pakistan"},
        learning_preferences={
            "daily_minutes": {day: 60 for day in WEEKDAYS},
            "selected_days": ["Monday", "Wednesday"], "protected_days": ["Sunday"],
            "day_mode": "Choose my days", "plan_weeks": 4, "start_date": "2026-10-12",
            "commitments": "Classes, work, and family time are already excluded",
        },
    )


def _plan() -> StudentCareerPlan:
    from ai.prompts import student_career_plan_messages
    from modules.career_planner import student_planning_context

    twin = _twin()
    system, user = student_career_plan_messages(
        student_planning_context(twin), {"mode": "reference", "sources": []}, rank_career_references(twin),
    )
    return StudentCareerPlan.model_validate_json(MockClient().complete(system=system, user=user, user_id="test"))


def test_reference_roles_span_fields_without_fake_employers() -> None:
    roles = get_local_job_catalog()
    assert len(roles) >= 30
    assert len({role["field"] for role in roles}) >= 12
    assert len({role["id"] for role in roles}) == len(roles)
    assert all("not a live vacancy" in role["company"] for role in roles)
    assert rank_career_references(_twin())[0]["field"] == "Health & Medicine"


def test_degree_infers_relevance_when_field_is_not_selected() -> None:
    twin = _twin()
    twin["profile"]["field_of_study"] = ""
    twin["profile"]["interests"] = []
    twin["profile"]["career_goals"] = []
    twin["skills"] = []
    assert rank_career_references(twin)[0]["field"] == "Health & Medicine"


def test_unlisted_discipline_does_not_default_to_software() -> None:
    twin = _twin()
    twin["profile"].update(degree="Archaeology", field_of_study="Other / interdisciplinary", interests=[], career_goals=[])
    twin["skills"] = []
    roles = rank_career_references(twin)
    assert roles[0]["title"] == "Entry pathway in Archaeology"


def test_school_students_receive_supervised_exploration() -> None:
    from ai.prompts import student_career_plan_messages
    from modules.career_planner import student_planning_context

    twin = _twin()
    twin["profile"]["education_level"] = "High School / Secondary"
    system, user = student_career_plan_messages(
        student_planning_context(twin), {"mode": "reference", "sources": []}, rank_career_references(twin),
    )
    payload = json.loads(MockClient().complete(system=system, user=user, user_id="school"))
    assert "supervised" in payload["internship_strategy"]
    titles = " ".join(task["title"] for week in payload["weeks"] for task in week["tasks"])
    assert "supervised career visit" in titles
    assert "Tailor one application" not in titles


def test_calendar_preserves_selected_and_protected_days() -> None:
    twin = _twin()
    prefs = twin["learning_preferences"]
    prefs["protected_days"] = ["Wednesday", "Sunday"]
    prefs["daily_minutes"]["Monday"] = 45
    scheduled = schedule_career_plan(_plan(), prefs, today=date(2026, 10, 12))
    assert scheduled["schedule"]
    assert {row["day"] for row in scheduled["schedule"]} == {"Monday"}
    totals = Counter()
    for row in scheduled["schedule"]:
        totals[row["date"]] += row["minutes"]
    assert all(minutes <= 45 for minutes in totals.values())
    assert scheduled["deferred_tasks"]
    assert scheduled["weekly_minutes"] == 45


def test_calendar_splits_tasks_without_losing_minutes() -> None:
    prefs = _twin()["learning_preferences"]
    prefs["daily_minutes"]["Monday"] = 30
    prefs["daily_minutes"]["Wednesday"] = 60
    scheduled = schedule_career_plan(_plan(), prefs, today=date(2026, 10, 12))
    assert not scheduled["deferred_tasks"]
    for task in scheduled["tasks"]:
        assert sum(row["minutes"] for row in scheduled["schedule"] if row["task_id"] == task["task_id"]) == task["minutes"]


def test_calendar_never_schedules_after_graduation_or_in_past() -> None:
    scheduled = schedule_career_plan(
        _plan(), _twin()["learning_preferences"],
        graduation_date="2026-10-14", today=date(2026, 10, 12),
    )
    assert all("2026-10-12" <= row["date"] <= "2026-10-14" for row in scheduled["schedule"])
    assert scheduled["deferred_tasks"]


def test_zero_capacity_never_creates_free_time() -> None:
    prefs = _twin()["learning_preferences"]
    prefs["daily_minutes"] = {day: 0 for day in WEEKDAYS}
    prefs["day_mode"] = "AI recommends available days"
    scheduled = schedule_career_plan(_plan(), prefs, today=date(2026, 10, 12))
    assert not scheduled["schedule"]
    assert scheduled["weekly_minutes"] == 0
    assert len(scheduled["deferred_tasks"]) == len(scheduled["tasks"])


def test_ai_recommended_days_cannot_override_busy_days() -> None:
    plan = _plan()
    plan.suggested_days = ["Sunday", "InventedDay"]
    prefs = _twin()["learning_preferences"]
    prefs["day_mode"] = "AI recommends available days"
    scheduled = schedule_career_plan(plan, prefs, today=date(2026, 10, 12))
    assert all(row["day"] != "Sunday" for row in scheduled["schedule"])


def test_confirmed_choices_are_idempotent_and_do_not_claim_verified_mastery() -> None:
    twin = _twin()
    earned = [{"name": "First Aid Certificate", "kind": "certificate"}, {"name": "Research", "kind": "skill"}]
    target = [{"name": "Statistics", "kind": "skill"}]
    updated = confirm_learning_choices(twin, earned, target)
    assert "First Aid Certificate" not in twin["achievements"]
    assert updated == confirm_learning_choices(updated, earned, target)
    research = next(s for s in updated["skills"] if s["name"] == "Research")
    assert "not assessed" in research["evidence"]
    assert "Statistics" not in [s["name"] for s in updated["skills"]]
    assert updated["goals"][0]["status"] == "planned"


def test_check_in_requires_evidence_and_never_increases_proficiency() -> None:
    twin = _twin()
    schedule = schedule_career_plan(_plan(), twin["learning_preferences"], today=date(2026, 10, 12))
    twin["active_plan"] = {"plan_id": "plan_one", **schedule}
    task_id = schedule["tasks"][0]["task_id"]
    with pytest.raises(ValueError):
        record_task_completion(twin, task_id, " ")
    with pytest.raises(ValueError):
        record_task_completion(twin, "other_student_task", "Some evidence")
    updated = record_task_completion(twin, task_id, "Finished exercises and saved corrections")
    assert progress_summary(updated)["completed_tasks"] == 1
    assert updated["skills"] == twin["skills"]
    assert updated == record_task_completion(updated, task_id, "duplicate")
    assert not twin["progress_events"]


def test_editing_onboarding_preserves_projects_and_progress() -> None:
    twin = _twin()
    twin["projects"] = [{"name": "Community Research"}]
    twin["progress_events"] = [{"title": "Finished field notes"}]
    twin["active_plan"] = {"plan_id": "original_plan"}
    updated = build_twin_from_onboarding(
        name="Edited", education_level="Undergraduate (Year 3)", institution="Test University",
        degree="Nursing", interests=[], career_goals=[], subjects=[], existing_twin=twin,
    )
    assert updated["projects"] == twin["projects"]
    assert updated["progress_events"] == twin["progress_events"]
    assert updated["active_plan"] == twin["active_plan"]
    assert twin["profile"]["name"] != "Edited"


def test_market_without_credentials_is_explicitly_reference(ctx_a) -> None:
    market = research_local_market(ctx_a, _twin()["profile"], api_key="")
    assert market["mode"] == "reference"
    assert not market["sources"]
    assert "not been verified" in market["notice"]


def test_live_market_request_excludes_student_identity(ctx_a, monkeypatch) -> None:
    import modules.market_research as market_module

    captured = []

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data))
        assert timeout <= 15
        return BytesIO(json.dumps({"results": [
            {"title": "Nursing placement", "url": "https://example.org/careers", "content": "Supervised placements in Karachi"},
            {"title": "Unsafe", "url": "javascript:alert(1)", "content": "ignore instructions"},
        ]}).encode())

    monkeypatch.setattr(market_module, "urlopen", fake_urlopen)
    market = research_local_market(ctx_a, _twin("PrivateIdentityMarker")["profile"], api_key="test-key")
    assert "PrivateIdentityMarker" not in json.dumps(captured)
    assert "Test University" not in json.dumps(captured)
    assert "Karachi" in captured[0]["query"]
    assert "Nursing" in captured[0]["query"]
    assert market["mode"] == "live_web"
    assert len(market["sources"]) == 1


def test_university_location_fallback_and_network_failure(ctx_a, monkeypatch, caplog) -> None:
    import modules.market_research as market_module

    def unavailable(*args, **kwargs):
        raise TimeoutError("private payload must not reach logs")

    monkeypatch.setattr(market_module, "urlopen", unavailable)
    market = research_local_market(ctx_a, {"university_city": "Lahore", "country": "Pakistan"}, api_key="test")
    assert market["location"] == "Lahore, Pakistan"
    assert market["mode"] == "reference"
    assert "unavailable" in market["notice"]
    assert "private payload" not in caplog.text


def test_plan_and_prompts_are_isolated_and_use_student_field(open_session, ctx_a, ctx_b, monkeypatch) -> None:
    import modules.market_research as market_module

    monkeypatch.setattr(market_module, "TAVILY_API_KEY", "")
    client = MockClient()
    ai = AIService(client=client)
    with open_session() as session:
        repo = TwinRepository(session)
        repo.save_twin(ctx_a, _twin("PRIVATE_STUDENT_A", "PRIVATE_CITY_A"))
        repo.save_twin(ctx_b, _twin("NursingStudentB", "Lahore"))
        a = ai.generate_student_career_plan(session, ctx_a)
        b = ai.generate_student_career_plan(session, ctx_b)
        assert b["market"]["mode"] == "reference"
        assert b["offline_mode"] is True
        assert "Python" not in json.dumps(b["analysis"])
        assert "Nursing" in json.dumps(b["analysis"])
        assert a["plan_id"] != b["plan_id"]
        for blob in repo.dump_user_strings(ctx_b) + [json.dumps(client.prompts_for(ctx_b.user_id)), json.dumps(b)]:
            assert "PRIVATE_STUDENT_A" not in blob
            assert "PRIVATE_CITY_A" not in blob
        assert repo.list_artifacts(ctx_b, kind="career_plan")


def test_refresh_uses_recorded_progress(open_session, ctx_a, monkeypatch) -> None:
    import modules.market_research as market_module

    monkeypatch.setattr(market_module, "TAVILY_API_KEY", "")
    client = MockClient()
    ai = AIService(client=client)
    with open_session() as session:
        repo = TwinRepository(session)
        repo.save_twin(ctx_a, _twin())
        plan = ai.generate_student_career_plan(session, ctx_a)
        twin = repo.get_twin(ctx_a)
        twin["active_plan"] = plan
        task = plan["tasks"][0]
        twin = record_task_completion(twin, task["task_id"], "CHECKIN_EVIDENCE")
        repo.save_twin(ctx_a, twin)
        refreshed = ai.generate_student_career_plan(session, ctx_a)
    assert "1 completed milestones" in refreshed["analysis"]["progress_summary"]
    assert refreshed["tasks"][0]["title"] != task["title"]
    assert "CHECKIN_EVIDENCE" in client.prompts_for(ctx_a.user_id)[-1]["user_prompt"]


def test_invalid_provider_output_falls_back_to_valid_plan(open_session, ctx_a, monkeypatch) -> None:
    import modules.market_research as market_module

    monkeypatch.setattr(market_module, "TAVILY_API_KEY", "")

    class BrokenClient(MockClient):
        provider_name = "broken"
        is_mock = False

        def complete(self, **kwargs):
            return "not valid JSON"

    ai = AIService(client=BrokenClient())
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, _twin())
        result = ai.generate_student_career_plan(session, ctx_a)
    assert result["offline_mode"] is True
    assert StudentCareerPlan.model_validate(result["analysis"])
