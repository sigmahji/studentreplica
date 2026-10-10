"""Schema validation tests for AI output models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai.schemas import (
    CVContent,
    CareerMatchExplanation,
    CoachReply,
    SkillGapRoadmap,
    TwinInsight,
    WhatIfSimulation,
)


def test_twin_insight_valid() -> None:
    insight = TwinInsight(
        strengths=["Python"],
        weaknesses=["Docker"],
        risks=["No projects"],
        next_actions=[
            {"action": "Build project", "rationale": "Evidence gap", "priority": 1},
            {"action": "Learn Docker", "rationale": "Job gap", "priority": 2},
            {"action": "Set goal", "rationale": "Direction", "priority": 3},
        ],
        evidence_used=["skills"],
        confidence=0.8,
    )
    assert len(insight.next_actions) == 3


def test_twin_insight_caps_actions() -> None:
    insight = TwinInsight(
        next_actions=[
            {"action": f"a{i}", "rationale": "r", "priority": 1} for i in range(5)
        ]
    )
    assert len(insight.next_actions) == 3


def test_career_match_score_bounds() -> None:
    with pytest.raises(ValidationError):
        CareerMatchExplanation(fit_summary="x", match_score=150)


def test_cv_content_defaults() -> None:
    cv = CVContent(cv_markdown="# Name", missing_information=["dates"])
    assert cv.fabricated is False


def test_what_if_is_estimate() -> None:
    sim = WhatIfSimulation(scenario="learn X", reasoning="guess")
    assert sim.is_estimate is True


def test_coach_reply_requires_reply() -> None:
    with pytest.raises(ValidationError):
        CoachReply()  # type: ignore[call-arg]


def test_roadmap_week_order() -> None:
    roadmap = SkillGapRoadmap(
        target_role="Backend Eng",
        weeks=[
            {
                "week": 1,
                "focus": "APIs",
                "resources": ["docs"],
                "milestone": "CRUD done",
            }
        ],
    )
    assert roadmap.weeks[0].week == 1
