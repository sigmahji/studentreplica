"""Transparent offline planning examples built from the supplied student context."""

from __future__ import annotations

import json
from typing import Any

from modules.digital_twin import compute_academic_stats


def _block(prompt: str, label: str, default: Any) -> Any:
    marker = f"{label}_BEGIN\n"
    if marker not in prompt:
        return default
    try:
        return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]
    except (ValueError, TypeError):
        return default


def mock_student_career_plan(prompt: str) -> dict[str, Any]:
    """Build field-specific examples without implying a live AI or market analysis."""
    twin = _block(prompt, "STUDENT_CONTEXT", {})
    market = _block(prompt, "MARKET_CONTEXT", {})
    references = _block(prompt, "ROLE_REFERENCES", [])
    profile = twin.get("profile", {})
    school_student = profile.get("education_level") in ("Middle School", "High School / Secondary")
    prefs = twin.get("learning_preferences", {})
    role = references[0] if references else {
        "title": "Explore an entry pathway in your field", "required_skills": ["Research", "Communication"],
        "missing_skills": ["Research"], "skill_coverage": 0,
    }
    gaps = role.get("missing_skills", []) or role["required_skills"][:2]
    skills = [str(s["name"]) for s in twin.get("skills", []) if isinstance(s, dict) and s.get("name")]
    stats = compute_academic_stats(twin)
    progress = twin.get("progress_summary", {})
    goals = [g.get("name", "") for g in twin.get("goals", []) if isinstance(g, dict)]
    focus = (goals or gaps)[0]
    weak = stats.get("at_risk", [])
    weeks = []
    recent_titles = {e.get("title") for e in progress.get("recent_milestones", [])}
    for number in range(1, max(1, min(12, int(prefs.get("plan_weeks", 4)))) + 1):
        skill = (goals or gaps)[(number - 1) % len(goals or gaps)]
        practice = f"Practice {skill}: exercise set {number}"
        if practice in recent_titles:
            practice = f"Extend {skill}: applied exercise set {number}"
        title = f"Review {weak[0]['subject']}: weak-topic set {number}" if weak and number == 1 else practice
        categories = ("project", "internship", "career")
        category = categories[(number - 1) % len(categories)]
        second = {
            "project": f"Create a {skill} work sample for {role['title']}",
            "internship": f"Research two eligible supervised placements for {role['title']}",
            "career": f"Tailor one application and practice interview answers for {role['title']}",
        }[category]
        if school_student and category in ("internship", "career"):
            second = (
                f"Ask a teacher about a supervised career visit related to {role['title']}"
                if category == "internship" else "Compare two further-study paths with a teacher or counselor"
            )
        if second in recent_titles:
            second = f"Improve the next version: {second}"
        weeks.append({
            "week": number, "focus": f"{skill} and {category} preparation",
            "tasks": [
                {"title": title, "minutes": 45, "category": "academic" if weak and number == 1 else "skill",
                 "evidence_required": "Save completed exercises and a short note explaining corrections.",
                 "resource": f"Your {skill} course materials or an official introductory guide"},
                {"title": second, "minutes": 30, "category": category,
                 "evidence_required": "Record a work sample or checked opportunity links and eligibility notes.",
                 "resource": "University careers office, professional body, or employer careers pages"},
            ],
        })
    return {
        "assessment": "needs_adjustment" if weak else "exploring" if skills else "insufficient_data",
        "assessment_reason": (
            f"Offline planning example for {profile.get('name') or 'this student'} in "
            f"{profile.get('degree') or profile.get('field_of_study') or 'their field'}. "
            + ("Reported grades suggest reviewing weaker subjects. " if weak else "Validate your direction through work samples and career conversations. ")
            + f"The reference role skill coverage is {role.get('skill_coverage', 0)}%; this is not a hiring probability."
        ),
        "market_summary": (
            f"Location: {market.get('location') or 'not provided'}. "
            + ("Web source links are available, but offline mode cannot assess market trends. Review each source."
               if market.get("sources") else "Current local demand is unverified; these are general reference pathways.")
        ),
        "career_directions": [
            {"role": r["title"], "fit_reason": "Reference pathway selected from your field and reported skills; confirm it matches your interests.",
             "skill_gaps": r.get("missing_skills", [])[:6], "next_step": "Review eligibility and compare two real role descriptions.", "source_ids": []}
            for r in (references[:3] or [role])
        ],
        "earned_options": [
            {"name": s, "kind": "skill", "rationale": "A field-relevant possibility; select only if you have actually learned or practiced it."}
            for s in list(dict.fromkeys(skills + role["required_skills"]))[:10]
        ],
        "target_options": [
            {"name": s, "kind": "skill", "rationale": f"A suggested gap for the reference pathway {role['title']}."}
            for s in gaps[:6]
        ] + [{"name": f"Work sample for {role['title']}", "kind": "project", "rationale": "Develop relevant evidence for future opportunities."}],
        "suggested_days": [day for day, minutes in prefs.get("daily_minutes", {}).items() if minutes > 0 and day not in prefs.get("protected_days", [])][:3],
        "weeks": weeks,
        "internship_strategy": (
            "Ask a teacher or counselor about supervised career visits and age-appropriate exploration. Prioritize schoolwork and check eligibility with a responsible adult."
            if school_student else "During study, build one relevant work sample, ask your university careers office about supervised placements, and verify local eligibility before applying."
        ),
        "graduation_strategy": f"Before {profile.get('graduation_date') or 'graduation'}, collect work evidence, check local professional requirements, prepare applications and practice interviews. Employment cannot be guaranteed.",
        "progress_summary": f"You recorded {progress.get('total_recorded_milestones', 0)} completed milestones; {progress.get('completed_tasks', 0)} of {progress.get('total_tasks', 0)} tasks in the active roadmap. Next focus: {focus}. This is self-reported progress, not verified proficiency.",
        "evidence_used": ["profile", "academic.courses", "skills", "goals", "learning_preferences", "progress_summary"],
        "confidence": 0.35,
        "notice": "Offline example plan, not a live AI assessment. Verify local requirements; outcomes are not guaranteed.",
    }


def mock_coach_reply(prompt: str) -> dict[str, Any]:
    """Summarize actual recorded work and the next scheduled task offline."""
    context = _block(prompt, "STUDENT_CONTEXT", {})
    summary = context.get("progress_summary", {})
    done = {
        event.get("task_id") for event in context.get("progress_events", [])
        if event.get("plan_id") == context.get("active_plan_id")
    }
    pending = [task for task in context.get("active_schedule", []) if task.get("task_id") not in done]
    next_action = (
        f"Your next scheduled task is {pending[0]['title']} on {pending[0]['date']}. "
        if pending else "Review your career plan and choose your next learning goal. "
    )
    return {
        "reply": (
            f"Offline coaching example for {context.get('profile', {}).get('name') or 'this student'}: "
            f"you have {summary.get('total_recorded_milestones', 0)} recorded milestones and "
            f"{summary.get('completed_tasks', 0)} of {summary.get('total_tasks', 0)} current tasks completed. "
            + next_action + "Keep your protected time free and record evidence for your next check-in."
        ),
        "suggested_followups": ["Review my career direction", "Plan my next learning cycle"],
        "evidence_used": ["progress_summary", "active_schedule", "learning_preferences"],
        "confidence": 0.35,
        "notice": "Offline coaching example, not a live AI reply. Progress is self-reported.",
    }
