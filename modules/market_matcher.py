"""Local requisition catalog and deterministic student-to-role matching."""

from typing import TypedDict


class JobRequisition(TypedDict):
    """Schema for an entry-level software engineering requisition."""

    id: str
    title: str
    company: str
    location: str
    required_skills: list[str]
    description: str


class MatchResult(TypedDict):
    """Schema for the result of a skills-based requisition match."""

    match_score: int
    matched_skills: list[str]
    missing_skills: list[str]


def get_local_job_catalog() -> list[JobRequisition]:
    """Return a curated catalog of entry-level roles in Pakistan's local tech markets."""
    return [
        {
            "id": "job_isb_001",
            "title": "Junior Backend Python Engineer",
            "company": "Northstar Digital Systems",
            "location": "Islamabad (Hybrid)",
            "required_skills": ["Python", "FastAPI", "PostgreSQL", "REST APIs", "Docker", "Git"],
            "description": "Develop backend services, implement RESTful APIs, and support database-backed product features under senior guidance.",
        },
        {
            "id": "job_rwp_002",
            "title": "Junior Android Mobile Developer",
            "company": "Twin Cities Mobility Labs",
            "location": "Rawalpindi (On-site)",
            "required_skills": ["Kotlin", "Android SDK", "Jetpack Compose", "REST APIs", "SQLite", "Git"],
            "description": "Build and test Android application features, integrate service APIs, and contribute to mobile release quality.",
        },
        {
            "id": "job_lhr_003",
            "title": "Data Engineering Intern",
            "company": "Lahore DataWorks",
            "location": "Lahore (Hybrid)",
            "required_skills": ["Python", "SQL", "Pandas", "ETL", "PostgreSQL", "Git"],
            "description": "Assist with data ingestion pipelines, validate structured datasets, and prepare transformations for analytics workflows.",
        },
        {
            "id": "job_lhr_004",
            "title": "Associate QA Automation Engineer",
            "company": "Punjab Cloud Technologies",
            "location": "Lahore (On-site)",
            "required_skills": ["Python", "Selenium", "API Testing", "PyTest", "Git", "CI/CD"],
            "description": "Create automated tests, verify API behavior, and support continuous integration quality gates for web products.",
        },
    ]


def calculate_match(
    student_skills: list[str], job_skills: list[str]
) -> MatchResult:
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
