"""Academic stats, onboarding twin build, and AI academic insights."""

from __future__ import annotations

from ai.client import MockClient
from ai.service import AIService
from modules.digital_twin import (
    build_twin_from_onboarding,
    compute_academic_stats,
    seed_demo_twin,
    skill_radar_points,
)
from storage.context import UserContext
from storage.repository import TwinRepository


def test_compute_academic_stats_ranks_subjects() -> None:
    twin = build_twin_from_onboarding(
        name="Sam",
        education_level="Undergraduate (Year 2)",
        institution="Test U",
        degree="SE",
        interests=["AI"],
        career_goals=["Backend"],
        subjects=[
            {"name": "Data Structures", "grade": 92},
            {"name": "OOP", "grade": 88},
            {"name": "Digital Logic", "grade": 55},
        ],
    )
    stats = compute_academic_stats(twin)
    assert stats["graded_count"] == 3
    assert round(float(stats["average_score"]), 1) == 78.3
    assert stats["at_risk"][0]["subject"] == "Digital Logic"
    assert skill_radar_points(twin)


def test_letter_and_gpa_grades() -> None:
    twin = build_twin_from_onboarding(
        name="Sam",
        education_level="High School / Secondary",
        institution="HS",
        degree="",
        interests=[],
        career_goals=[],
        subjects=[
            {"name": "Math", "grade": "A"},
            {"name": "Physics", "grade": "3.5"},
        ],
    )
    stats = compute_academic_stats(twin)
    assert stats["graded_count"] == 2
    assert stats["average_score"] is not None


def test_ai_insight_uses_academic_performance(
    open_session, ctx_a: UserContext
) -> None:
    twin = seed_demo_twin("a")
    ai = AIService(client=MockClient(), offline_mode=True)
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, twin, label="academic_test")
        insight = ai.generate_twin_insights(session, ctx_a)
    assert insight.academic_summary
    assert insight.subject_insights or insight.study_level_fit
    assert "academic.courses" in insight.evidence_used or insight.evidence_used
