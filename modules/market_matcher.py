"""Local requisition catalog and deterministic student-to-role matching."""

import json
from pathlib import Path
from typing import TypedDict
import re


class JobRequisition(TypedDict):
    """Schema for a reference role, not an advertised vacancy."""

    id: str
    title: str
    company: str
    location: str
    required_skills: list[str]
    description: str
    field: str


class MatchResult(TypedDict):
    """Schema for the result of a skills-based requisition match."""

    match_score: int
    matched_skills: list[str]
    missing_skills: list[str]


def get_local_job_catalog() -> list[JobRequisition]:
    """Load reference profiles spanning academic and vocational fields."""
    path = Path(__file__).resolve().parents[1] / "data" / "career_roles.json"
    with path.open(encoding="utf-8") as source:
        roles = json.load(source)
    return [
        {
            **role,
            "company": "Career reference (not a live vacancy)",
            "location": "Location researched in Career Plan",
            "description": "Example entry pathway; check local eligibility and requirements.",
        }
        for role in roles
    ]


def calculate_match(student_skills: list[str], job_skills: list[str]) -> MatchResult:
    """Calculate a case-insensitive skills match and the resulting capability gap."""
    normalized_student_skills = {
        skill.strip().casefold() for skill in student_skills if skill.strip()
    }
    normalized_job_skills = {
        skill.strip().casefold() for skill in job_skills if skill.strip()
    }

    matched_skill_keys = normalized_student_skills.intersection(normalized_job_skills)
    missing_skill_keys = normalized_job_skills.difference(normalized_student_skills)

    matched_skills = [
        skill for skill in job_skills if skill.strip().casefold() in matched_skill_keys
    ]
    missing_skills = [
        skill for skill in job_skills if skill.strip().casefold() in missing_skill_keys
    ]
    match_score = (
        int((len(matched_skill_keys) / len(normalized_job_skills)) * 100)
        if normalized_job_skills
        else 0
    )

    return {
        "match_score": match_score,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
    }


def canonical_skill(name: str) -> str:
    """Small explicit alias map; no fuzzy or AI-invented skill equivalence."""
    text = " ".join(name.strip().casefold().split())
    aliases = {
        "python programming": "python",
        "python programming skills": "python",
        "basic knowledge of python programming": "python",
        "programming in python": "python",
        "ms excel": "excel",
        "microsoft excel": "excel",
        "structured query language": "sql",
        "oop": "object-oriented programming",
        "object oriented programming": "object-oriented programming",
        "dsa": "data structures and algorithms",
        "data structures & algorithms": "data structures and algorithms",
        "problem-solving": "problem solving",
        "problem-solving skills": "problem solving",
    }
    return aliases.get(text, text)


def rank_jobs(twin: dict, jobs: list[dict]) -> list[dict]:
    """Score proficiency-weighted coverage, separately from interest relevance."""
    skills = {}
    for skill in twin.get("skills", []):
        if isinstance(skill, dict):
            name = canonical_skill(skill["name"])
            skills[name] = max(
                skills.get(name, 0),
                max(0, min(100, float(skill.get("proficiency", 0)))),
            )
    profile = twin.get("profile", {})
    interest_words = set(
        re.findall(
            r"[a-z]{3,}",
            " ".join(
                profile.get("interests", []) + profile.get("career_goals", [])
            ).casefold(),
        )
    ) - {"and", "the", "with", "jobs", "career"}
    ranked = []
    for job in jobs:
        required = list(
            dict.fromkeys(
                s.strip() for s in job.get("required_skills", []) if s.strip()
            )
        )
        required = list({canonical_skill(s): s for s in required}.values())
        score = (
            round(
                sum(skills.get(canonical_skill(s), 0) for s in required) / len(required)
            )
            if required
            else None
        )
        matched = [s for s in required if skills.get(canonical_skill(s), 0) >= 60]
        missing = [s for s in required if skills.get(canonical_skill(s), 0) < 60]
        interest_match = bool(
            interest_words
            & set(
                re.findall(
                    r"[a-z]{3,}",
                    (job["title"] + " " + job.get("description", "")).casefold(),
                )
            )
        )
        ranked.append(
            {
                **job,
                "match_score": score,
                "matched_skills": matched,
                "missing_skills": missing,
                "interest_match": interest_match,
                "near_match": score is not None and 50 <= score < 70,
                "strong_match": score is not None and score >= 70,
            }
        )
    return sorted(
        ranked, key=lambda j: (j["match_score"] or 0, j["interest_match"]), reverse=True
    )
