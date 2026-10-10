"""Semester boundaries, prerequisites, formative evidence, and account isolation."""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader
from docx import Document

from ai.client import MockClient
from ai.schemas import CourseAssessment
from ai.service import AIService
from modules.academics import (
    academic_priorities,
    grade_score,
    learning_options,
    save_semester,
    semester_limit,
    subject_options,
)
from modules.cv_exports import (
    cv_facts,
    export_docx,
    export_pdf,
    sanitize_photo,
    select_facts,
)
from modules.digital_twin import build_twin_from_onboarding, compute_academic_stats
from modules.learning import course_resources, enroll_course, grade_assessment
from modules.market_matcher import rank_jobs
from modules.market_research import sources_from_tools, validate_openings
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def student(name: str = "AlphaStudent") -> dict:
    twin = empty_twin(name)
    twin["profile"].update(
        degree="Software Engineering",
        education_level="Undergraduate (Year 2)",
        institution="Example University",
    )
    return twin


def semester(
    twin: dict,
    number: int = 1,
    current: int | None = None,
    name: str = "Programming Fundamentals",
    grade: str = "42",
    core: bool = True,
) -> dict:
    return save_semester(
        twin,
        year=2,
        current_semester=current,
        number=number,
        courses=[{"name": name, "grade": grade, "core": core}],
        scale="Percentage (0-100)",
    )


def quiz() -> CourseAssessment:
    return CourseAssessment(
        skill="Programming Fundamentals",
        preparation="Review functions, variables and loops.",
        questions=[
            {
                "question": f"Question {i}: which answer is correct?",
                "options": ["A", "B", "C", "D"],
                "answer_index": i % 4,
                "concept": f"Concept {i}",
                "explanation": "The correct option follows the stated rule.",
            }
            for i in range(5)
        ],
    )


def ready_course() -> tuple[dict, str]:
    twin = enroll_course(
        semester(student()),
        "Programming Fundamentals",
        "Introductory Programming",
        "https://www.open.edu/openlearn/",
    )
    course = twin["learning_courses"][0]
    course["assessment_id"] = 123
    course["status"] = "quiz_ready"
    return twin, course["id"]


def test_second_year_allows_four_completed_semesters() -> None:
    twin = student()
    for number in range(1, 5):
        twin = semester(twin, number, name=f"Custom Subject {number}", grade="80")
    assert len(twin["academic"]["semesters"]) == 4
    assert semester_limit(twin["profile"]["education_level"]) == 4
    with pytest.raises(ValueError):
        semester(twin, 5)


def test_current_semester_supports_ungraded_courses_and_blocks_future() -> None:
    twin = semester(student(), 3, current=3, name="Algorithms", grade="")
    assert twin["academic"]["current_semester"] == 3
    assert twin["academic"]["semesters"][0]["status"] == "current"
    assert academic_priorities(twin)["current_subjects"][0]["score"] is None
    with pytest.raises(ValueError):
        semester(twin, 4, current=3)
    with pytest.raises(ValueError, match="final grades"):
        semester(twin, 1, current=4, grade="70")


def test_semester_upsert_preserves_records_and_progress() -> None:
    twin = semester(student(), 1, grade="50")
    twin["progress_events"] = [{"title": "Existing work"}]
    twin = semester(twin, 2, name="Data Structures", grade="75")
    updated = semester(twin, 1, grade="80")
    assert len(updated["academic"]["semesters"]) == 2
    assert updated["academic"]["courses"][1]["name"] == "Data Structures"
    assert updated["progress_events"] == twin["progress_events"]
    assert twin["academic"]["courses"][0]["grade"] == "50"


def test_legacy_courses_are_retained_for_explicit_assignment() -> None:
    twin = student()
    twin["academic"]["courses"] = [{"name": "Earlier Subject", "grade": 80}]
    updated = semester(twin)
    assert updated["academic"]["legacy_courses"][0]["name"] == "Earlier Subject"


def test_degree_subjects_are_not_computing_only() -> None:
    assert "Anatomy" in subject_options("BSc Nursing")
    assert "Circuit Analysis" in subject_options("Electrical Engineering")
    assert "Contract Law" in subject_options("Law")
    assert "Other" in subject_options("Unlisted Custom Degree")


@pytest.mark.parametrize(
    "value,scale,expected",
    [
        (3, "Percentage (0-100)", 3),
        (3, "GPA (0-4.0)", 75),
        ("B+", "Letter (A-F)", 80),
        ("", "Percentage (0-100)", None),
    ],
)
def test_grade_scales_are_explicit(value, scale, expected) -> None:
    assert grade_score(value, scale) == expected


@pytest.mark.parametrize(
    "value,scale",
    [
        (101, "Percentage (0-100)"),
        (4.1, "GPA (0-4.0)"),
        ("Q", "Letter (A-F)"),
        ("NaN", "Percentage (0-100)"),
    ],
)
def test_invalid_grade_rejected(value, scale) -> None:
    with pytest.raises(ValueError):
        grade_score(value, scale)


def test_completed_subject_requires_grade_and_custom_subject_is_supported() -> None:
    with pytest.raises(ValueError):
        semester(student(), grade="")
    updated = save_semester(
        student(),
        year=2,
        current_semester=None,
        number=1,
        courses=[
            {
                "name": "Other",
                "custom_subject": "Specialized Robotics",
                "grade": "3",
                "core": True,
            }
        ],
        scale="GPA (0-4.0)",
    )
    assert updated["academic"]["courses"][0]["name"] == "Specialized Robotics"
    assert compute_academic_stats(updated)["average_score"] == 75


def test_core_weaknesses_and_prerequisites_come_first() -> None:
    twin = semester(student())
    twin = semester(twin, 2, name="Art Elective", grade="30", core=False)
    assert (
        academic_priorities(twin)["weak_subjects"][0]["subject"]
        == "Programming Fundamentals"
    )
    option = next(o for o in learning_options(twin) if o["name"] == "Machine Learning")
    assert "Programming Fundamentals" in option["foundations_first"]
    enrolled = enroll_course(
        twin, "Machine Learning", "ML Course", "https://www.coursera.org/"
    )
    assert (
        "Programming Fundamentals"
        in enrolled["learning_courses"][0]["prerequisites_to_review"]
    )
    assert any(g["name"] == "Programming Fundamentals" for g in enrolled["goals"])


def test_course_discovery_respects_budget() -> None:
    assert all(r["cost"] == "Free" for r in course_resources("Anatomy", "Free only"))
    paid = course_resources("Financial Modeling", "Free and paid")
    assert any("Paid" in r["cost"] for r in paid)
    assert all(r["url"].startswith("https://") for r in paid)
    assert any(r["type"] == "Course / learning materials" for r in paid)


def test_four_of_five_passes_without_rewriting_university_grade() -> None:
    twin, identifier = ready_course()
    updated, result = grade_assessment(
        twin, identifier, 123, quiz(), [0, 1, 2, 3, 1], offline=False
    )
    assert result["score"] == 80
    assert result["passed"]
    assert updated["learning_courses"][0]["status"] == "passed"
    assert updated["academic"]["courses"][0]["grade"] == "42"
    assert not academic_priorities(updated)["weak_subjects"]
    assert updated["skills"][0]["proficiency"] == 60
    assert updated["progress_events"][0]["verification"] == "app_assessment"
    assert any(
        f["section"] == "Assessed Learning" and "80%" in f["text"]
        for f in cv_facts(updated)
    )
    assert not twin["progress_events"]


def test_failed_assessment_tracks_concepts_without_awarding_skill() -> None:
    twin, identifier = ready_course()
    updated, result = grade_assessment(
        twin, identifier, 123, quiz(), [0, 1, 2, 0, 1], offline=False
    )
    assert result["score"] == 60
    assert not result["passed"]
    assert result["weak_concepts"] == ["Concept 3", "Concept 4"]
    assert not updated["skills"] and not updated["progress_events"]
    assert not any(f["section"] == "Assessed Learning" for f in cv_facts(updated))
    with pytest.raises(ValueError):
        grade_assessment(
            updated, identifier, 123, quiz(), [0, 1, 2, 3, 0], offline=False
        )


def test_incomplete_answers_and_wrong_assessment_rejected() -> None:
    twin, identifier = ready_course()
    with pytest.raises(ValueError):
        grade_assessment(
            twin, identifier, 123, quiz(), [0, 1, None, 3, 0], offline=False
        )
    with pytest.raises(ValueError):
        grade_assessment(twin, identifier, 999, quiz(), [0, 1, 2, 3, 0], offline=False)


def test_offline_pass_is_practice_not_assessed_achievement() -> None:
    twin, identifier = ready_course()
    updated, result = grade_assessment(
        twin, identifier, 123, quiz(), [0, 1, 2, 3, 0], offline=True
    )
    assert result["passed"] and result["practice_only"]
    assert not updated["skills"] and not updated["progress_events"]
    assert not any(f["section"] == "Assessed Learning" for f in cv_facts(updated))
    assert academic_priorities(updated)["weak_subjects"]


def test_assessment_payloads_and_artifacts_are_isolated(
    open_session, ctx_a, ctx_b, caplog
) -> None:
    client = MockClient()
    ai = AIService(client=client)
    ids = []
    with open_session() as session:
        repo = TwinRepository(session)
        for ctx, name in (
            (ctx_a, "PRIVATE_ALPHA_TOKEN"),
            (ctx_b, "PRIVATE_BETA_TOKEN"),
        ):
            twin = enroll_course(
                student(name), "Python", f"Course for {name}", "https://ocw.mit.edu/"
            )
            repo.save_twin(ctx, twin)
            ids.append(
                ai.generate_course_assessment(
                    session,
                    ctx,
                    twin["learning_courses"][0]["id"],
                    "Completed loops and functions.",
                )["id"]
            )
        with pytest.raises(ValueError):
            ai.submit_course_assessment(session, ctx_b, ids[0], [1] * 5)
        ai.submit_course_assessment(session, ctx_b, ids[1], [1] * 5)
        b_data = json.dumps(repo.dump_user_strings(ctx_b))
        assert "PRIVATE_ALPHA_TOKEN" not in b_data
        assert "PRIVATE_ALPHA_TOKEN" not in json.dumps(
            client.prompts_for(ctx_b.user_id)
        )
        assert "PRIVATE_ALPHA_TOKEN" not in caplog.text
        repo.save_artifact(ctx_a, "cv_photo", {"jpeg_base64": "ALPHA_PHOTO"})
        repo.save_artifact(ctx_b, "cv_photo", {"jpeg_base64": "BETA_PHOTO"})
        repo.delete_artifacts(ctx_b, kind="cv_photo")
        assert repo.list_artifacts(ctx_a, kind="cv_photo")
        assert not repo.list_artifacts(ctx_b, kind="cv_photo")


def test_academic_priority_enforced_in_ai_plan(
    open_session, ctx_a, monkeypatch
) -> None:
    monkeypatch.setattr("modules.market_research.TAVILY_API_KEY", "")
    twin = semester(student())
    twin = semester(twin, 4, current=4, name="Database Systems", grade="")
    twin["learning_preferences"] = {
        "plan_weeks": 2,
        "day_mode": "Choose my days",
        "selected_days": ["Monday"],
        "protected_days": ["Sunday"],
        "daily_minutes": {"Monday": 30},
    }
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, twin)
        payload = AIService(client=MockClient()).generate_student_career_plan(
            session, ctx_a
        )
    assert payload["schedule"][0]["title"].startswith(
        "Recover Programming Fundamentals"
    )
    assert all(
        row["minutes"] <= 30 and row["day"] == "Monday" for row in payload["schedule"]
    )
    assert payload["deferred_tasks"]
    assert any("Current semester" in t["title"] for t in payload["tasks"])


def test_cv_ai_cannot_invent_facts_and_exports_are_real() -> None:
    twin, identifier = ready_course()
    twin, _ = grade_assessment(
        twin, identifier, 123, quiz(), [0, 1, 2, 3, 0], offline=False
    )
    facts = select_facts(cv_facts(twin), ["employer_invented", "degree_invented"])
    pdf = export_pdf(twin, facts)
    docx = export_docx(twin, facts)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    assert "AlphaStudent" in text and "Introductory Programming" in text
    assert "100%" in text and "Not an accredited certificate" in text
    assert "employer_invented" not in text
    document = Document(BytesIO(docx))
    assert "AlphaStudent" in " ".join(p.text for p in document.paragraphs)


def test_photo_sanitization_and_export() -> None:
    output = BytesIO()
    Image.new("RGB", (1000, 800), "teal").save(output, format="PNG")
    safe = sanitize_photo(output.getvalue())
    with Image.open(BytesIO(safe)) as photo:
        assert photo.width <= 600 and photo.height <= 600 and photo.format == "JPEG"
    assert export_pdf(student(), cv_facts(student()), safe).startswith(b"%PDF")
    assert export_docx(student(), cv_facts(student()), safe).startswith(b"PK")
    with pytest.raises(ValueError):
        sanitize_photo(b"not an image")


def test_long_cv_paginates_without_overflow() -> None:
    twin = student("VeryLongName" * 15)
    facts = [
        {
            "id": f"f{i}",
            "section": "Projects",
            "text": "Long project description " * 20,
            "url": "",
        }
        for i in range(35)
    ]
    assert len(PdfReader(BytesIO(export_pdf(twin, facts))).pages) > 1


def test_live_sources_come_from_tool_metadata_not_generated_urls() -> None:
    tools = [
        {
            "search_results": {
                "results": [
                    {
                        "title": "Python Intern",
                        "url": "https://example.com/jobs/python",
                        "content": "L0: Python Intern\nL1: Requires Python and SQL",
                    },
                    {"title": "Bad", "url": "javascript:alert(1)", "content": "Bad"},
                ]
            }
        }
    ]
    sources = sources_from_tools(tools)
    assert len(sources) == 1 and "L0:" not in sources[0]["snippet"]
    openings = [
        {
            "source_id": "source_1",
            "title": "Python Intern",
            "required_skills": ["Python", "SQL", "InventedSkill"],
            "company": "InventedCompany",
            "location": "InventedPlace",
            "evidence_quote": "Requires Python and SQL",
        }
    ]
    jobs = validate_openings(openings, sources)
    assert jobs[0]["required_skills"] == ["Python", "SQL"]
    assert jobs[0]["company"] == "Not supplied"
    openings[0]["evidence_quote"] = "Invented evidence"
    assert not validate_openings(openings, sources)


def test_match_scores_use_proficiency_and_interest_separately() -> None:
    twin = student()
    twin["skills"] = [
        {"name": "Python", "proficiency": 80},
        {"name": "SQL", "proficiency": 40},
    ]
    twin["profile"]["interests"] = ["design"]
    jobs = [
        {"title": "Python Developer", "required_skills": ["Python", "SQL"]},
        {"title": "Design Intern", "required_skills": ["Design"]},
        {"title": "Unknown requirements", "required_skills": []},
    ]
    ranked = rank_jobs(twin, jobs)
    assert ranked[0]["match_score"] == 60 and ranked[0]["near_match"]
    assert ranked[0]["missing_skills"] == ["SQL"]
    assert next(j for j in ranked if j["title"] == "Design Intern")["interest_match"]
    assert (
        next(j for j in ranked if j["title"] == "Unknown requirements")["match_score"]
        is None
    )


def test_matching_normalizes_explicit_aliases_without_fuzzy_equivalence() -> None:
    twin = student()
    twin["skills"] = [
        {"name": "Python", "proficiency": 80},
        {"name": "MS Excel", "proficiency": 60},
    ]
    jobs = [
        {
            "title": "Analyst",
            "required_skills": ["Python programming skills", "Microsoft Excel"],
        },
        {"title": "C++ Developer", "required_skills": ["C++"]},
    ]
    ranked = rank_jobs(twin, jobs)
    assert ranked[0]["match_score"] == 70
    assert ranked[1]["match_score"] == 0


@pytest.mark.parametrize(
    "matched,missing,score", [([], ["Python"], 0), (["Python"], [], 100)]
)
def test_ai_cannot_overwrite_empty_computed_match_lists(
    open_session, ctx_a, matched, missing, score
) -> None:
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, student())
        explanation = AIService(client=MockClient()).explain_career_match(
            session,
            ctx_a,
            {"title": "Python Developer", "required_skills": ["Python"]},
            match_score=score,
            matched_skills=matched,
            missing_skills=missing,
        )
    assert explanation.matched_skills == matched
    assert explanation.missing_skills == missing


def test_onboarding_edit_preserves_semester_structure() -> None:
    twin = semester(student())
    updated = build_twin_from_onboarding(
        name="Edited",
        education_level="Undergraduate (Year 2)",
        institution="Example University",
        degree="Software Engineering",
        interests=[],
        career_goals=[],
        subjects=[],
        existing_twin=twin,
    )
    assert updated["academic"]["semesters"] == twin["academic"]["semesters"]
    assert updated["academic"]["courses"] == twin["academic"]["courses"]


def test_ungraded_retake_does_not_erase_a_previous_weakness() -> None:
    twin = semester(student(), grade="42")
    twin = semester(twin, 3, current=3, grade="")
    priority = academic_priorities(twin)
    assert priority["weak_subjects"][0]["score"] == 42
    assert priority["current_subjects"][0]["subject"] == "Programming Fundamentals"


def test_onboarding_preserves_explicit_percentage_and_never_infers_ungraded_skill() -> (
    None
):
    twin = semester(student(), grade="3")
    twin = semester(twin, 3, current=3, name="Algorithms", grade="")
    updated = build_twin_from_onboarding(
        name="Edited",
        education_level="Undergraduate (Year 2)",
        institution="Example University",
        degree="Software Engineering",
        interests=[],
        career_goals=[],
        subjects=[],
        existing_twin=twin,
    )
    assert updated["skills"][0]["proficiency"] == 3
    assert not any(s["name"] == "Algorithms" for s in updated["skills"])
