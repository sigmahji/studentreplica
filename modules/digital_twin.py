"""Digital twin helpers: PDF extract, academic model, radar/timeline data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pypdf import PdfReader

from storage.twin_schema import clone_twin, empty_twin, legacy_profile_to_twin

EDUCATION_LEVELS: list[str] = [
    "Middle School",
    "High School / Secondary",
    "Undergraduate (Year 1)",
    "Undergraduate (Year 2)",
    "Undergraduate (Year 3)",
    "Undergraduate (Year 4)",
    "Undergraduate (Year 5)",
    "Undergraduate (Year 6)",
    "Graduate / Masters",
    "Doctorate / PhD",
    "Bootcamp / Certificate",
]

# Suggested subjects by study level (students can still add custom ones)
SUBJECT_PRESETS: dict[str, list[str]] = {
    "Middle School": [
        "Mathematics",
        "Science",
        "English",
        "Social Studies",
        "Computer Basics",
    ],
    "High School / Secondary": [
        "Mathematics",
        "Physics",
        "Chemistry",
        "Biology",
        "English",
        "Computer Science",
    ],
    "Undergraduate (Year 1)": [
        "Programming Fundamentals",
        "Calculus",
        "Physics",
        "English Composition",
        "Introduction to Computing",
    ],
    "Undergraduate (Year 2)": [
        "Data Structures",
        "OOP",
        "Discrete Mathematics",
        "Database Systems",
        "Digital Logic Design",
    ],
    "Undergraduate (Year 3)": [
        "Algorithms",
        "Software Engineering",
        "Operating Systems",
        "Computer Networks",
        "Web Development",
    ],
    "Undergraduate (Year 4)": [
        "Machine Learning",
        "Capstone Project",
        "Cloud Computing",
        "Information Security",
        "Mobile Development",
    ],
    "Graduate / Masters": [
        "Research Methods",
        "Advanced Algorithms",
        "Distributed Systems",
        "Thesis Seminar",
    ],
    "Doctorate / PhD": [
        "Research Seminar",
        "Dissertation",
        "Advanced Topics",
        "Teaching Practicum",
    ],
    "Bootcamp / Certificate": [
        "Python",
        "Web Fundamentals",
        "Git & Collaboration",
        "SQL",
        "Career Prep",
    ],
}

GRADE_SCALE_OPTIONS: list[str] = [
    "Percentage (0-100)",
    "GPA (0-4.0)",
    "Letter (A-F)",
]


def extract_text_from_pdf(uploaded_file) -> str:
    """Extract raw text from an uploaded PDF file."""
    try:
        reader = PdfReader(uploaded_file)
        text = ""
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        return f"Error reading PDF: {exc}"


def build_digital_twin_prompt(academic_text: str) -> str:
    """Build prompt to turn extracted academic text into structured JSON."""
    return f"""
Analyze this student's academic background and return ONLY a valid JSON object.
Schema:
{{
  "name": "Student Name or Candidate",
  "degree": "Degree / Program",
  "verified_skills": ["Skill 1", "Skill 2"],
  "core_courses": ["Course 1", "Course 2"],
  "experience_level": "Beginner / Intermediate / Advanced",
  "strengths_summary": "Short 2-sentence summary of academic capability."
}}

Student Document Text:
{academic_text}
"""


def get_demo_student() -> dict[str, Any]:
    """Zero-latency fallback student profile for hackathon demo."""
    return {
        "name": "Muhammad Owais",
        "degree": "B.S. Software Engineering",
        "verified_skills": [
            "Python",
            "C++",
            "Java",
            "Object-Oriented Programming",
            "Data Structures & Algorithms",
            "Database Systems",
            "Android Basics",
            "Git",
        ],
        "core_courses": [
            "Data Structures",
            "OOP",
            "Digital Logic Design",
            "Database Management Systems",
            "Software Engineering Principles",
        ],
        "experience_level": "Undergraduate (Year 3)",
        "strengths_summary": (
            "Strong foundation in core computing principles, algorithmic"
            " problem solving, and object-oriented application design."
        ),
    }


def get_demo_student_b() -> dict[str, Any]:
    """Second demo student with a contrasting academic profile."""
    return {
        "name": "Ayesha Khan",
        "degree": "B.S. Business Analytics",
        "verified_skills": [
            "Excel",
            "SQL",
            "Statistics",
            "Tableau",
            "Communication",
            "Python Basics",
        ],
        "core_courses": [
            "Business Statistics",
            "Marketing Analytics",
            "Financial Accounting",
            "Data Visualization",
        ],
        "experience_level": "Undergraduate (Year 2)",
        "strengths_summary": (
            "Strong quantitative reasoning and storytelling with data;"
            " growing interest in product analytics roles."
        ),
    }


def suggested_subjects(education_level: str) -> list[str]:
    """Return preset subject names for a study level."""
    return list(
        SUBJECT_PRESETS.get(education_level, SUBJECT_PRESETS["Undergraduate (Year 2)"])
    )


def _normalize_grade_to_score(grade: str | float | int | None) -> float | None:
    """Map a grade entry to 0-100 when possible."""
    if grade is None or grade == "":
        return None
    if isinstance(grade, (int, float)):
        value = float(grade)
        if 0 <= value <= 4.0:
            return round((value / 4.0) * 100, 1)
        return max(0.0, min(100.0, value))

    text = str(grade).strip().upper()
    letter_map = {
        "A+": 95,
        "A": 90,
        "A-": 85,
        "B+": 80,
        "B": 75,
        "B-": 70,
        "C+": 65,
        "C": 60,
        "C-": 55,
        "D": 50,
        "F": 30,
    }
    if text in letter_map:
        return float(letter_map[text])
    try:
        value = float(text.replace("%", ""))
    except ValueError:
        return None
    if 0 <= value <= 4.0:
        return round((value / 4.0) * 100, 1)
    return max(0.0, min(100.0, value))


def compute_academic_stats(twin: dict[str, Any]) -> dict[str, Any]:
    """Deterministic academic summary from courses/grades in the twin."""
    courses = twin.get("academic", {}).get("courses", []) or []
    scored: list[tuple[str, float]] = []
    for course in courses:
        if isinstance(course, dict):
            name = str(course.get("name") or "Unknown")
            score = (
                course.get("score")
                if "score" in course
                else _normalize_grade_to_score(course.get("grade"))
            )
        else:
            name = str(course)
            score = None
        if score is not None:
            scored.append((name, score))

    if not scored:
        return {
            "subject_count": len(courses),
            "graded_count": 0,
            "average_score": None,
            "strongest": [],
            "weakest": [],
            "at_risk": [],
        }

    average = round(sum(s for _, s in scored) / len(scored), 1)
    ranked = sorted(scored, key=lambda x: x[1], reverse=True)
    return {
        "subject_count": len(courses),
        "graded_count": len(scored),
        "average_score": average,
        "strongest": [{"subject": n, "score": s} for n, s in ranked[:3]],
        "weakest": [{"subject": n, "score": s} for n, s in ranked[-3:][::-1]],
        "at_risk": [{"subject": n, "score": s} for n, s in scored if s < 60],
    }


def skill_radar_points(twin: dict[str, Any]) -> list[dict[str, Any]]:
    """Build radar-chart points from skills; fall back to course scores."""
    points: list[dict[str, Any]] = []
    for skill in twin.get("skills", []) or []:
        if isinstance(skill, dict) and skill.get("name"):
            points.append(
                {
                    "label": str(skill["name"]),
                    "value": float(
                        skill["proficiency"]
                        if skill.get("proficiency") is not None
                        else 0
                    ),
                }
            )
    if points:
        return points[:8]

    for course in twin.get("academic", {}).get("courses", []) or []:
        if not isinstance(course, dict):
            continue
        score = (
            course.get("score")
            if "score" in course
            else _normalize_grade_to_score(course.get("grade"))
        )
        if score is None:
            continue
        points.append({"label": str(course.get("name")), "value": score})
    return points[:8]


def progress_timeline(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten twin snapshots into a timeline for the History UI."""
    timeline: list[dict[str, Any]] = []
    for snap in snapshots:
        twin = snap.get("twin") or {}
        stats = compute_academic_stats(twin)
        skills = twin.get("skills") or []
        timeline.append(
            {
                "version": snap.get("version"),
                "label": snap.get("label") or f"v{snap.get('version')}",
                "created_at": snap.get("created_at"),
                "skill_count": len(skills),
                "completed_milestones": len(twin.get("progress_events", [])),
                "average_score": stats.get("average_score"),
                "education_level": (twin.get("profile") or {}).get("education_level"),
            }
        )
    return timeline


def build_twin_from_onboarding(
    *,
    name: str,
    education_level: str,
    institution: str,
    degree: str,
    interests: list[str],
    career_goals: list[str],
    subjects: list[dict[str, Any]],
    skills: list[dict[str, Any]] | None = None,
    study_habits: list[str] | None = None,
    profile_details: dict[str, Any] | None = None,
    learning_preferences: dict[str, Any] | None = None,
    achievements: list[str] | None = None,
    existing_twin: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a twin without discarding previously recorded progress."""
    twin = clone_twin(existing_twin) if existing_twin else empty_twin()
    twin["profile"]["name"] = name.strip()
    twin["profile"]["education_level"] = education_level
    twin["profile"]["experience_level"] = education_level
    twin["profile"]["institution"] = institution.strip()
    twin["profile"]["degree"] = degree.strip()
    twin["profile"]["interests"] = [i for i in interests if i]
    twin["profile"]["career_goals"] = [g for g in career_goals if g]
    for key in (
        "field_of_study",
        "city",
        "country",
        "university_city",
        "graduation_date",
        "work_preference",
    ):
        if profile_details is not None and key in profile_details:
            twin["profile"][key] = str(profile_details[key] or "").strip()
    if learning_preferences is not None:
        twin["learning_preferences"] = learning_preferences
    if achievements is not None:
        twin["achievements"] = achievements

    courses: list[dict[str, Any]] = []
    grades_map: dict[str, Any] = {}
    derived_skills: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    if existing_twin and existing_twin.get("academic", {}).get("semesters"):
        subjects = existing_twin["academic"]["courses"]
    for subject in subjects:
        sub_name = str(subject.get("name") or "").strip()
        if not sub_name:
            continue
        grade = subject.get("grade")
        courses.append({**subject, "name": sub_name, "grade": grade})
        grades_map[sub_name] = grade
        score = (
            subject.get("score")
            if "score" in subject
            else _normalize_grade_to_score(grade)
        )
        if score is None:
            continue
        derived_skills.append(
            {
                "name": sub_name,
                "proficiency": int(score) if score is not None else 50,
                "evidence": f"course_grade:{grade}",
                "last_updated": now,
            }
        )

    twin["academic"]["courses"] = courses
    twin["academic"]["grades"] = grades_map
    twin["academic"]["study_habits"] = study_habits or []

    stats = compute_academic_stats(twin)
    twin["academic"]["strengths"] = [
        f"{s['subject']} ({s['score']})" for s in stats.get("strongest", [])
    ]
    twin["academic"]["weaknesses"] = [
        f"{s['subject']} ({s['score']})" for s in stats.get("weakest", [])
    ]

    if skills is not None:
        twin["skills"] = skills
    elif existing_twin and existing_twin.get("skills"):
        twin["skills"] = existing_twin["skills"]
    else:
        twin["skills"] = derived_skills

    avg = stats.get("average_score")
    twin["profile"]["strengths_summary"] = f"{name} is at {education_level}" + (
        f" with average academic score {avg}/100." if avg is not None else "."
    )
    return twin


def seed_demo_twin(which: str = "a") -> dict[str, Any]:
    """Build a full twin document from a demo legacy profile."""
    profile = get_demo_student() if which != "b" else get_demo_student_b()
    twin = legacy_profile_to_twin(profile)
    # Attach sample grades so AI academic analysis has signal
    graded = []
    sample_grades = [88, 92, 75, 81, 70, 85]
    for idx, course in enumerate(twin["academic"]["courses"]):
        grade = sample_grades[idx % len(sample_grades)]
        course["grade"] = grade
        graded.append(course)
        twin["academic"]["grades"][course["name"]] = grade
    twin["academic"]["courses"] = graded
    twin["profile"]["education_level"] = profile["experience_level"]
    twin["profile"]["institution"] = "Demo University"
    stats = compute_academic_stats(twin)
    twin["academic"]["strengths"] = [
        f"{s['subject']} ({s['score']})" for s in stats["strongest"]
    ]
    twin["academic"]["weaknesses"] = [
        f"{s['subject']} ({s['score']})" for s in stats["weakest"]
    ]
    return twin
