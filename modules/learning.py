"""Course selection and deterministic, auditable 80% formative assessment."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

from ai.schemas import CourseAssessment


def course_resources(skill: str, budget: str = "Free only") -> list[dict[str, str]]:
    """Official course discovery links, clearly labelled rather than invented courses."""
    query = quote_plus(skill[:150])
    curated = [
        (
            ("python", "programming fundamentals", "object-oriented programming"),
            "Harvard CS50: Introduction to Programming with Python",
            "https://cs50.harvard.edu/python/",
        ),
        (
            ("statistics", "business statistics", "data literacy"),
            "Khan Academy: Statistics and probability",
            "https://www.khanacademy.org/math/statistics-probability",
        ),
        (
            ("anatomy", "physiology", "health informatics", "public health"),
            "Khan Academy: Health and medicine",
            "https://www.khanacademy.org/science/health-and-medicine",
        ),
        (
            ("linear algebra", "machine learning"),
            "MIT OpenCourseWare: Linear Algebra",
            "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/",
        ),
        (
            ("physics", "engineering mechanics", "classical mechanics"),
            "MIT OpenCourseWare: Classical Mechanics",
            "https://ocw.mit.edu/courses/8-01sc-classical-mechanics-fall-2016/",
        ),
        (
            ("financial accounting", "management accounting", "financial modeling"),
            "OpenLearn: Introduction to bookkeeping and accounting",
            "https://www.open.edu/openlearn/money-business/introduction-bookkeeping-and-accounting/content-section-0",
        ),
    ]
    resources = [
        {
            "title": title,
            "url": url,
            "cost": "Free",
            "type": "Course / learning materials",
        }
        for tags, title, url in curated
        if skill.casefold() in tags
    ]
    resources += [
        {
            "title": f"OpenLearn: {skill}",
            "url": f"https://www.open.edu/openlearn/search-results?as_q={query}",
            "cost": "Free",
            "type": "Course search",
        },
        {
            "title": f"MIT OpenCourseWare: {skill}",
            "url": f"https://ocw.mit.edu/search/?q={query}",
            "cost": "Free",
            "type": "Course search",
        },
    ]
    if budget != "Free only":
        resources += [
            {
                "title": f"Coursera: {skill}",
                "url": f"https://www.coursera.org/search?query={query}",
                "cost": "Paid / varies; check provider",
                "type": "Course search",
            },
            {
                "title": f"edX: {skill}",
                "url": f"https://www.edx.org/search?q={query}",
                "cost": "Paid / audit varies; check provider",
                "type": "Course search",
            },
        ]
    return resources


def enroll_course(
    twin: dict[str, Any], skill: str, title: str, url: str
) -> dict[str, Any]:
    """Record the student's chosen learning resource without claiming completion."""
    from modules.academics import learning_options

    result = deepcopy(twin)
    if not skill.strip() or not title.strip():
        raise ValueError("Choose a skill and enter the actual course or unit title.")
    if not url.startswith("https://") or len(url) > 2000:
        raise ValueError("Use the course provider's HTTPS link.")
    options = learning_options(twin)
    option = next((o for o in options if o["name"].casefold() == skill.casefold()), {})
    blocked = option.get("foundations_first", [])
    result.setdefault("learning_courses", []).append(
        {
            "id": str(uuid4()),
            "skill": skill[:150],
            "title": title[:200],
            "url": url,
            "status": "learning",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "prerequisites_to_review": blocked,
        }
    )
    for prerequisite in blocked:
        if not any(
            g.get("name") == prerequisite for g in result.setdefault("goals", [])
        ):
            result["goals"].insert(
                0,
                {
                    "name": prerequisite,
                    "kind": "skill",
                    "status": "planned",
                    "reason": f"Foundation for {skill}",
                },
            )
    if not any(g.get("name") == skill for g in result.setdefault("goals", [])):
        result["goals"].append(
            {"name": skill[:150], "kind": "skill", "status": "planned"}
        )
    return result


def grade_assessment(
    twin: dict[str, Any],
    course_id: str,
    assessment_id: int,
    assessment: CourseAssessment,
    answers: list[int],
    *,
    offline: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Grade exactly once; an offline example never grants assessed proficiency."""
    result = deepcopy(twin)
    course = next(
        (c for c in result.get("learning_courses", []) if c["id"] == course_id), None
    )
    if course is None or course.get("assessment_id") != assessment_id:
        raise ValueError(
            "Assessment does not belong to this course or is no longer active."
        )
    if any(a.get("assessment_id") == assessment_id for a in course.get("attempts", [])):
        raise ValueError(
            "This attempt was already submitted. Start a new assessment to try again."
        )
    if len(answers) != len(assessment.questions) or any(
        type(a) is not int or not 0 <= a < 4 for a in answers
    ):
        raise ValueError("Answer every question before submitting.")
    correct = sum(
        answer == question.answer_index
        for answer, question in zip(answers, assessment.questions)
    )
    score = correct / len(answers) * 100
    passed = correct * 100 >= len(answers) * 80
    weaknesses = [
        q.concept for a, q in zip(answers, assessment.questions) if a != q.answer_index
    ]
    feedback = {
        "assessment_id": assessment_id,
        "score": score,
        "passed": passed,
        "practice_only": offline,
        "weak_concepts": weaknesses,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
        "explanations": [q.explanation for q in assessment.questions],
    }
    course.setdefault("attempts", []).append(feedback)
    course["status"] = (
        "practice_completed"
        if offline and passed
        else "passed" if passed else "needs_review"
    )
    course["assessment_offline"] = offline
    course["weak_concepts"] = weaknesses
    if passed and not offline:
        course["passed_at"] = feedback["completed_at"]
        skill = next(
            (
                s
                for s in result.setdefault("skills", [])
                if s["name"].casefold() == course["skill"].casefold()
            ),
            None,
        )
        # A short quiz does not establish professional mastery. Store the score separately.
        evidence = f"StudentReplica formative assessment: {score:g}%; {course['title']} (not accredited)"
        if skill:
            skill.update(
                {
                    "proficiency": max(skill.get("proficiency", 0), 60),
                    "assessment_score": score,
                    "evidence": evidence,
                    "last_updated": feedback["completed_at"],
                }
            )
        else:
            result["skills"].append(
                {
                    "name": course["skill"],
                    "proficiency": 60,
                    "assessment_score": score,
                    "evidence": evidence,
                    "last_updated": feedback["completed_at"],
                }
            )
        for goal in result.get("goals", []):
            if goal.get("name", "").casefold() == course["skill"].casefold():
                goal["status"] = "assessed"
        result.setdefault("progress_events", []).append(
            {
                "course_id": course_id,
                "task_id": assessment_id,
                "title": f"Passed {course['skill']} formative assessment ({score:g}%)",
                "category": "academic",
                "completed_on": feedback["completed_at"][:10],
                "verification": "app_assessment",
                "evidence": course["url"],
            }
        )
    return result, feedback
