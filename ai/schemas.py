"""Pydantic models for every structured AI output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class NextAction(BaseModel):
    """A prioritized next step grounded in twin evidence."""

    action: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)
    priority: int = Field(ge=1, le=3)


class SubjectInsight(BaseModel):
    """Per-subject academic assessment grounded in reported grades."""

    subject: str
    grade: str = ""
    assessment: str = ""
    recommendation: str = ""


class TwinInsight(BaseModel):
    """AI Twin Insight Report including academic performance analysis."""

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    academic_summary: str = Field(
        default="",
        description="Overall academic performance narrative for this student",
    )
    subject_insights: list[SubjectInsight] = Field(default_factory=list)
    study_level_fit: str = Field(
        default="",
        description="How performance aligns with the student's study level",
    )
    evidence_used: list[str] = Field(
        default_factory=list,
        description="Twin data points the model claims to have used",
    )
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    notice: str = Field(default="AI-generated, verify important details")

    @field_validator("next_actions")
    @classmethod
    def _cap_actions(cls, value: list[NextAction]) -> list[NextAction]:
        return value[:3]


class CareerMatchExplanation(BaseModel):
    """AI explanation layered on a deterministic match score."""

    fit_summary: str
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence_used: list[str] = Field(default_factory=list)
    match_score: int = Field(ge=0, le=100)
    score_source: Literal["deterministic"] = "deterministic"
    notice: str = Field(default="AI-generated, verify important details")


class RoadmapWeek(BaseModel):
    """One week in a skill-gap learning roadmap."""

    week: int = Field(ge=1)
    focus: str
    resources: list[str] = Field(default_factory=list)
    milestone: str


class SkillGapRoadmap(BaseModel):
    """Week-by-week plan to close skill gaps for a target role."""

    target_role: str
    weeks: list[RoadmapWeek] = Field(default_factory=list)
    overall_milestone: str = ""
    evidence_used: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    notice: str = Field(default="AI-generated, verify important details")


class CVContent(BaseModel):
    """Tailored CV + cover letter grounded only in twin facts."""

    cv_markdown: str = ""
    cover_letter_markdown: str = ""
    missing_information: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    fabricated: bool = Field(
        default=False,
        description="Must remain False; model must not invent facts",
    )
    notice: str = Field(default="AI-generated, verify important details")


class CoachReply(BaseModel):
    """Career/academic coach reply grounded in one student's twin."""

    reply: str
    suggested_followups: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    notice: str = Field(default="AI-generated, verify important details")


class SkillDelta(BaseModel):
    """Estimated skill change for a what-if scenario."""

    skill: str
    delta: int = Field(ge=-100, le=100)
    reasoning: str


class WhatIfSimulation(BaseModel):
    """Estimated effect of a hypothetical action on the twin."""

    scenario: str
    estimated_skill_changes: list[SkillDelta] = Field(default_factory=list)
    career_match_impact: str = ""
    is_estimate: Literal[True] = True
    reasoning: str = ""
    evidence_used: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notice: str = Field(
        default="Estimate only — AI-generated, verify important details"
    )


class LearningOption(BaseModel):
    """An option a student must confirm before it becomes a twin fact."""

    name: str = Field(min_length=1, max_length=150)
    kind: Literal["skill", "certificate", "project", "achievement"]
    rationale: str = Field(min_length=1, max_length=600)


class CareerDirection(BaseModel):
    """A career hypothesis supported by student facts and cited market evidence."""

    role: str = Field(min_length=1, max_length=150)
    fit_reason: str = Field(min_length=1, max_length=1000)
    skill_gaps: list[str] = Field(default_factory=list, max_length=8)
    next_step: str = Field(min_length=1, max_length=600)
    source_ids: list[str] = Field(default_factory=list, max_length=6)


class LearningTask(BaseModel):
    """A measurable task whose date and time budget are enforced in Python."""

    title: str = Field(min_length=1, max_length=200)
    minutes: int = Field(ge=15, le=180)
    category: Literal["academic", "skill", "project", "internship", "career"]
    evidence_required: str = Field(min_length=1, max_length=500)
    resource: str = Field(default="", max_length=400)


class CareerPlanWeek(BaseModel):
    """A week of actionable preparation, before calendar constraints are applied."""

    week: int = Field(ge=1, le=12)
    focus: str = Field(min_length=1, max_length=300)
    tasks: list[LearningTask] = Field(min_length=1, max_length=4)


class StudentCareerPlan(BaseModel):
    """Cross-discipline analysis, student choices, and an adaptive rolling plan."""

    assessment: Literal[
        "on_track", "needs_adjustment", "exploring", "insufficient_data"
    ]
    assessment_reason: str = Field(min_length=1, max_length=1800)
    market_summary: str = Field(min_length=1, max_length=1800)
    career_directions: list[CareerDirection] = Field(min_length=1, max_length=4)
    earned_options: list[LearningOption] = Field(default_factory=list, max_length=12)
    target_options: list[LearningOption] = Field(default_factory=list, max_length=12)
    suggested_days: list[str] = Field(default_factory=list, max_length=7)
    weeks: list[CareerPlanWeek] = Field(min_length=1, max_length=12)
    internship_strategy: str = Field(min_length=1, max_length=1600)
    graduation_strategy: str = Field(min_length=1, max_length=1600)
    progress_summary: str = Field(min_length=1, max_length=1200)
    evidence_used: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notice: str = "AI-generated guidance; outcomes are not guaranteed."

    @field_validator("weeks")
    @classmethod
    def _unique_weeks(cls, weeks: list[CareerPlanWeek]) -> list[CareerPlanWeek]:
        if len({week.week for week in weeks}) != len(weeks):
            raise ValueError("Week numbers must be unique")
        weeks = sorted(weeks, key=lambda week: week.week)
        if [week.week for week in weeks] != list(range(1, len(weeks) + 1)):
            raise ValueError("Weeks must be consecutive starting at week 1")
        return weeks


class QuizQuestion(BaseModel):
    """One application-focused question; the answer is server-side only."""

    question: str = Field(min_length=10, max_length=700)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=10, max_length=1000)
    concept: str = Field(min_length=1, max_length=150)


class CourseAssessment(BaseModel):
    """Short formative assessment, not an accredited certification."""

    skill: str = Field(min_length=1, max_length=150)
    preparation: str = Field(min_length=1, max_length=1500)
    questions: list[QuizQuestion] = Field(min_length=5, max_length=5)
    evidence_used: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.6, ge=0, le=1)
    notice: str = "AI-generated formative quiz, not an accredited certification."


class CVSelection(BaseModel):
    """AI can select and order facts, but cannot write new biographical claims."""

    fact_ids: list[str] = Field(default_factory=list, max_length=80)
    rationale: str = Field(max_length=1600)
    evidence_used: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=0.6, ge=0, le=1)


class MarketOpening(BaseModel):
    """Extracted listing; URL and skills must be supported by search evidence."""

    source_id: str
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(default="Not supplied", max_length=150)
    location: str = Field(default="Not supplied", max_length=150)
    required_skills: list[str] = Field(default_factory=list, max_length=12)


class MarketAnalysis(BaseModel):
    """Cited openings and cautious advice about emerging skills."""

    openings: list[MarketOpening] = Field(default_factory=list, max_length=8)
    emerging_advice: str = Field(max_length=1800)
    source_ids: list[str] = Field(default_factory=list, max_length=8)
    evidence_used: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.5, ge=0, le=1)
    notice: str = (
        "AI-generated; verify opening status, requirements and eligibility with the employer."
    )


# Map task names → schema classes for the service layer
SCHEMA_BY_TASK: dict[str, type[BaseModel]] = {
    "twin_insight": TwinInsight,
    "career_match": CareerMatchExplanation,
    "skill_gap_roadmap": SkillGapRoadmap,
    "cv_content": CVContent,
    "coach_reply": CoachReply,
    "what_if": WhatIfSimulation,
    "student_career_plan": StudentCareerPlan,
    "course_assessment": CourseAssessment,
    "market_analysis": MarketAnalysis,
    "cv_selection": CVSelection,
}
