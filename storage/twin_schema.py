"""Canonical twin document shape and helpers (in-memory dicts, not ORM)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


def empty_twin(name: str = "") -> dict[str, Any]:
    """Return a blank twin document with the product schema."""
    return {
        "profile": {
            "name": name,
            "education_level": "",
            "institution": "",
            "degree": "",
            "interests": [],
            "career_goals": [],
            "experience_level": "",
            "strengths_summary": "",
            "field_of_study": "",
            "city": "",
            "country": "",
            "university_city": "",
            "graduation_date": "",
            "work_preference": "Local or remote",
        },
        "skills": [],
        "academic": {
            "semesters": [],
            "current_semester": None,
            "courses": [],
            "grades": {},
            "strengths": [],
            "weaknesses": [],
            "study_habits": [],
        },
        "projects": [],
        "achievements": [],
        "goals": [],
        "learning_preferences": {},
        "learning_courses": [],
        "progress_events": [],
        "meta": {
            "twin_version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def legacy_profile_to_twin(profile: dict[str, Any]) -> dict[str, Any]:
    """Map the existing demo/profile dict into the canonical twin schema."""
    twin = empty_twin(name=str(profile.get("name") or ""))
    twin["profile"]["degree"] = str(profile.get("degree") or "")
    twin["profile"]["education_level"] = str(profile.get("experience_level") or "")
    twin["profile"]["experience_level"] = str(profile.get("experience_level") or "")
    twin["profile"]["strengths_summary"] = str(profile.get("strengths_summary") or "")
    twin["skills"] = [
        {
            "name": skill,
            "proficiency": 70,
            "evidence": "legacy_verified_skill",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        for skill in profile.get("verified_skills", [])
    ]
    twin["academic"]["courses"] = [
        {"name": course, "grade": None} for course in profile.get("core_courses", [])
    ]
    return twin


def twin_to_legacy_profile(twin: dict[str, Any]) -> dict[str, Any]:
    """Project a twin into the legacy profile shape used by current modules."""
    profile = twin.get("profile", {})
    skills = twin.get("skills", [])
    courses = twin.get("academic", {}).get("courses", [])
    return {
        "name": profile.get("name", ""),
        "degree": profile.get("degree", ""),
        "verified_skills": [
            s["name"] if isinstance(s, dict) else str(s) for s in skills
        ],
        "core_courses": [c["name"] if isinstance(c, dict) else str(c) for c in courses],
        "experience_level": profile.get("experience_level", ""),
        "strengths_summary": profile.get("strengths_summary", ""),
    }


def skill_names(twin: dict[str, Any]) -> list[str]:
    """Extract skill name strings from a twin document."""
    names: list[str] = []
    for item in twin.get("skills", []):
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def clone_twin(twin: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy a twin so callers cannot mutate repository-owned data."""
    return deepcopy(twin)
