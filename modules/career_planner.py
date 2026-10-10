"""Career planning, constrained scheduling, and user-confirmed progress."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ai.schemas import StudentCareerPlan
from modules.market_matcher import get_local_job_catalog

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def student_planning_context(twin: dict[str, Any]) -> dict[str, Any]:
    """Exclude prior generated plans and retain only this student's facts."""
    from modules.academics import academic_priorities, learning_options

    context = {
        key: deepcopy(twin.get(key, default))
        for key, default in (
            ("profile", {}),
            ("skills", []),
            ("academic", {}),
            ("projects", []),
            ("achievements", []),
            ("goals", []),
            ("learning_preferences", {}),
            ("progress_events", []),
        )
    } | {
        "progress_summary": progress_summary(twin),
        "active_plan_id": twin.get("active_plan", {}).get("plan_id"),
        "active_schedule": deepcopy(
            twin.get("active_plan", {}).get("schedule", [])[:24]
        ),
        "academic_priorities": academic_priorities(twin),
        "learning_catalog": learning_options(twin),
        "learning_courses": [
            {
                k: c.get(k)
                for k in (
                    "skill",
                    "title",
                    "status",
                    "weak_concepts",
                    "prerequisites_to_review",
                )
            }
            for c in twin.get("learning_courses", [])
        ],
    }
    # Semesters are already represented by courses; avoid duplicated prompt payloads.
    context["academic"].pop("legacy_courses", None)
    from modules.digital_twin import compute_academic_stats

    context["academic"]["semesters"] = [
        {
            "number": s["number"],
            "status": s["status"],
            "subject_count": len(s["courses"]),
            "average_score": compute_academic_stats(
                {"academic": {"courses": s["courses"]}}
            )["average_score"],
            "weak_core_subjects": [
                c["name"]
                for c in s["courses"]
                if c.get("core", True)
                and c.get("score") is not None
                and c["score"] < 60
            ],
        }
        for s in twin.get("academic", {}).get("semesters", [])
    ]
    context["progress_events"] = context["progress_events"][-12:]
    return context


def rank_career_references(twin: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank field relevance and exact skill coverage without inventing demand."""
    profile = twin.get("profile", {})
    field = profile.get("field_of_study", "")
    degree = str(profile.get("degree", "")).casefold()
    if not field and any(
        term in degree
        for term in (
            "software",
            "computer",
            "informatics",
            "information technology",
            "data science",
        )
    ):
        field = "Computing & IT"
    interests = " ".join(
        [str(profile.get("degree", ""))]
        + profile.get("interests", [])
        + profile.get("career_goals", [])
    ).casefold()
    words = set(re.findall(r"[a-z]{3,}", interests)) - {
        "and",
        "the",
        "science",
        "bachelor",
        "master",
        "degree",
    }
    skills = {
        str(skill["name"])
        .strip()
        .casefold(): max(0, min(100, float(skill.get("proficiency", 0))))
        for skill in twin.get("skills", [])
        if isinstance(skill, dict) and skill.get("name")
    }
    ranked = []
    for role in get_local_job_catalog():
        required = role["required_skills"]
        coverage = round(
            sum(skills.get(s.casefold(), 0) for s in required) / len(required)
        )
        title_words = set(re.findall(r"[a-z]{3,}", role["title"].casefold()))
        field_words = set(re.findall(r"[a-z]{3,}", role["field"].casefold()))
        interest_match = 3 * len(title_words & words) + len(field_words & words)
        ranked.append(
            {
                "id": role["id"],
                "title": role["title"],
                "field": role["field"],
                "required_skills": required,
                "skill_coverage": coverage,
                "missing_skills": [
                    s for s in required if skills.get(s.casefold(), 0) < 60
                ],
                "_rank": (int(field == role["field"]), interest_match, coverage),
            }
        )
    ranked.sort(key=lambda role: role["_rank"], reverse=True)
    if not any(role["_rank"][0] or role["_rank"][1] for role in ranked):
        label = profile.get("degree") or field or "your field"
        required = [
            str(s["name"])
            for s in twin.get("skills", [])
            if isinstance(s, dict) and s.get("name")
        ][:4]
        required = required or ["Research", "Communication", "Portfolio Development"]
        return [
            {
                "id": "custom_field_reference",
                "title": f"Entry pathway in {label}",
                "field": field or label,
                "required_skills": required,
                "skill_coverage": 0,
                "missing_skills": required,
            }
        ]
    return [{k: v for k, v in role.items() if k != "_rank"} for role in ranked[:6]]


def progress_summary(twin: dict[str, Any]) -> dict[str, Any]:
    """Count reported work; never infer mastery or employment from completion."""
    plan = twin.get("active_plan", {})
    task_ids = {task["task_id"] for task in plan.get("tasks", [])}
    events = twin.get("progress_events", [])
    completed = {
        event.get("task_id")
        for event in events
        if event.get("plan_id") == plan.get("plan_id")
    }
    completed &= task_ids
    return {
        "completed_tasks": len(completed),
        "total_tasks": len(task_ids),
        "completion_percent": (
            round(100 * len(completed) / len(task_ids)) if task_ids else 0
        ),
        "total_recorded_milestones": len(events),
        "recent_milestones": events[-12:],
    }


def schedule_career_plan(
    plan: StudentCareerPlan,
    preferences: dict[str, Any],
    *,
    graduation_date: str = "",
    today: date | None = None,
) -> dict[str, Any]:
    """Place tasks only in free time; split oversized tasks and expose overflow."""
    today = today or date.today()
    start = max(
        today, date.fromisoformat(preferences.get("start_date") or today.isoformat())
    )
    end = date.fromisoformat(graduation_date) if graduation_date else None
    if end is not None and end < today:
        end = None
    capacity = {
        day: max(0, min(240, int(preferences.get("daily_minutes", {}).get(day, 0))))
        for day in WEEKDAYS
    }
    for day in preferences.get("protected_days", []):
        if day in capacity:
            capacity[day] = 0
    selected = preferences.get("selected_days", [])
    if preferences.get("day_mode") == "Choose my days":
        allowed = [day for day in WEEKDAYS if day in selected and capacity[day] > 0]
    else:
        suggested = [
            day for day in plan.suggested_days if day in capacity and capacity[day] > 0
        ]
        allowed = (
            list(dict.fromkeys(suggested))
            or sorted(WEEKDAYS, key=lambda d: capacity[d], reverse=True)[:3]
        )
    allowed = [day for day in allowed if capacity[day] > 0]
    horizon = max(1, min(12, int(preferences.get("plan_weeks", 4))))
    scheduled, tasks, deferred = [], [], []
    for week in plan.weeks:
        if week.week > horizon:
            continue
        slots = []
        for offset in range(7):
            day_date = start + timedelta(days=(week.week - 1) * 7 + offset)
            day = WEEKDAYS[day_date.weekday()]
            if day in allowed and (end is None or day_date <= end):
                slots.append(
                    {
                        "date": day_date.isoformat(),
                        "day": day,
                        "remaining": capacity[day],
                    }
                )
        for index, task in enumerate(week.tasks):
            task_id = f"w{week.week}_t{index + 1}"
            tasks.append({"task_id": task_id, "week": week.week, **task.model_dump()})
            remaining = task.minutes
            for slot in slots:
                minutes = min(remaining, slot["remaining"])
                if minutes:
                    scheduled.append(
                        {
                            "task_id": task_id,
                            "week": week.week,
                            "date": slot["date"],
                            "day": slot["day"],
                            "minutes": minutes,
                            "title": task.title,
                            "category": task.category,
                        }
                    )
                    slot["remaining"] -= minutes
                    remaining -= minutes
                if not remaining:
                    break
            if remaining:
                deferred.append(
                    {
                        "task_id": task_id,
                        "title": task.title,
                        "unscheduled_minutes": remaining,
                    }
                )
    return {
        "start_date": start.isoformat(),
        "selected_days": allowed,
        "weekly_minutes": sum(capacity[day] for day in allowed),
        "tasks": tasks,
        "schedule": scheduled,
        "deferred_tasks": deferred,
    }


def confirm_learning_choices(
    twin: dict[str, Any],
    earned: list[dict[str, str]],
    targets: list[dict[str, str]],
) -> dict[str, Any]:
    """Persist student-confirmed facts and goals without treating suggestions as facts."""
    result = deepcopy(twin)
    now = datetime.now(timezone.utc).isoformat()
    existing_skills = {
        str(s["name"]).casefold()
        for s in result.get("skills", [])
        if isinstance(s, dict)
    }
    for item in earned:
        if item["kind"] == "skill":
            if item["name"].casefold() not in existing_skills:
                result.setdefault("skills", []).append(
                    {
                        "name": item["name"],
                        "proficiency": 50,
                        "evidence": "Student-confirmed; proficiency not assessed",
                        "last_updated": now,
                    }
                )
                existing_skills.add(item["name"].casefold())
        elif item["kind"] == "project":
            if not any(
                p.get("name") == item["name"]
                for p in result.setdefault("projects", [])
                if isinstance(p, dict)
            ):
                result["projects"].append(
                    {"name": item["name"], "evidence": "Student-confirmed"}
                )
        elif item["name"] not in result.setdefault("achievements", []):
            result["achievements"].append(item["name"])
    goals = result.setdefault("goals", [])
    for item in targets:
        if not any(g.get("name") == item["name"] for g in goals if isinstance(g, dict)):
            goals.append(
                {"name": item["name"], "kind": item["kind"], "status": "planned"}
            )
    return result


def record_task_completion(
    twin: dict[str, Any],
    task_id: str,
    evidence: str,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Record a dated, idempotent check-in with evidence for an active plan task."""
    result = deepcopy(twin)
    plan = result.get("active_plan", {})
    task = next((t for t in plan.get("tasks", []) if t["task_id"] == task_id), None)
    if task is None:
        raise ValueError("Choose a task from your current roadmap.")
    evidence = evidence.strip()
    if not evidence or len(evidence) > 2000:
        raise ValueError(
            "Add a completion note or evidence link (up to 2,000 characters)."
        )
    events = result.setdefault("progress_events", [])
    if any(
        e.get("plan_id") == plan["plan_id"] and e.get("task_id") == task_id
        for e in events
    ):
        return result
    events.append(
        {
            "plan_id": plan["plan_id"],
            "task_id": task_id,
            "title": task["title"],
            "category": task["category"],
            "completed_on": (today or date.today()).isoformat(),
            "evidence": evidence,
            "verification": "student_reported",
        }
    )
    return result
