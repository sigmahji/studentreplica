"""Degree-aware academic records, explicit grading, and prerequisite evidence."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

# Suggested foundations, not a substitute for a university's official curriculum.
DEGREE_SUBJECTS: dict[str, tuple[str, ...]] = {
    "Computer Science": (
        "Programming Fundamentals",
        "Mathematics",
        "Discrete Mathematics",
        "Data Structures",
        "Algorithms",
        "Database Systems",
        "Operating Systems",
        "Computer Networks",
        "Machine Learning",
    ),
    "Software Engineering": (
        "Programming Fundamentals",
        "Object-Oriented Programming",
        "Data Structures",
        "Algorithms",
        "Database Systems",
        "Software Requirements",
        "Software Testing",
        "Software Design",
        "Web Development",
    ),
    "Information Technology": (
        "Programming Fundamentals",
        "Database Systems",
        "Computer Networks",
        "Operating Systems",
        "Information Security",
        "Web Development",
    ),
    "Data Science / Business Analytics": (
        "Mathematics",
        "Statistics",
        "Programming Fundamentals",
        "Database Systems",
        "Data Visualization",
        "Machine Learning",
        "Business Statistics",
    ),
    "Business Administration": (
        "Financial Accounting",
        "Economics",
        "Business Statistics",
        "Marketing",
        "Organizational Behavior",
        "Operations Management",
        "Business Law",
    ),
    "Accounting / Finance": (
        "Financial Accounting",
        "Management Accounting",
        "Economics",
        "Business Mathematics",
        "Corporate Finance",
        "Auditing",
        "Taxation",
    ),
    "Electrical Engineering": (
        "Calculus",
        "Physics",
        "Circuit Analysis",
        "Digital Logic",
        "Electronics",
        "Signals and Systems",
        "Control Systems",
    ),
    "Mechanical Engineering": (
        "Calculus",
        "Physics",
        "Engineering Mechanics",
        "Thermodynamics",
        "Fluid Mechanics",
        "Materials Science",
        "Machine Design",
    ),
    "Civil Engineering": (
        "Calculus",
        "Engineering Mechanics",
        "Structural Analysis",
        "Surveying",
        "Soil Mechanics",
        "Fluid Mechanics",
        "Construction Management",
    ),
    "Medicine": (
        "Anatomy",
        "Physiology",
        "Biochemistry",
        "Pathology",
        "Pharmacology",
        "Microbiology",
        "Clinical Skills",
    ),
    "Nursing": (
        "Anatomy",
        "Physiology",
        "Nursing Fundamentals",
        "Pharmacology",
        "Clinical Skills",
        "Community Health",
        "Patient Safety",
    ),
    "Pharmacy": (
        "Chemistry",
        "Biochemistry",
        "Physiology",
        "Pharmacology",
        "Pharmaceutics",
        "Medicinal Chemistry",
        "Patient Safety",
    ),
    "Psychology": (
        "Introduction to Psychology",
        "Statistics",
        "Research Methods",
        "Developmental Psychology",
        "Cognitive Psychology",
        "Ethics",
    ),
    "Law": (
        "Legal Research",
        "Constitutional Law",
        "Contract Law",
        "Criminal Law",
        "Tort Law",
        "Legal Writing",
        "Professional Ethics",
    ),
    "Education": (
        "Educational Psychology",
        "Curriculum Design",
        "Assessment",
        "Teaching Methods",
        "Research Methods",
        "Inclusive Education",
    ),
    "Arts / Design": (
        "Design Fundamentals",
        "Drawing",
        "Color Theory",
        "Typography",
        "Art History",
        "Visual Communication",
        "Portfolio Development",
    ),
    "Architecture": (
        "Design Fundamentals",
        "Architectural Drawing",
        "Building Construction",
        "Structures",
        "Environmental Design",
        "History of Architecture",
    ),
    "Media / Communication": (
        "Media Writing",
        "Communication Theory",
        "Research Methods",
        "Media Ethics",
        "Digital Storytelling",
        "Video Production",
    ),
    "Biology / Biotechnology": (
        "Biology",
        "Chemistry",
        "Genetics",
        "Microbiology",
        "Biochemistry",
        "Statistics",
        "Research Methods",
    ),
    "Agriculture": (
        "Biology",
        "Chemistry",
        "Soil Science",
        "Crop Science",
        "Plant Pathology",
        "Agricultural Economics",
        "Research Methods",
    ),
    "Mathematics / Physics": (
        "Calculus",
        "Linear Algebra",
        "Differential Equations",
        "Statistics",
        "Classical Mechanics",
        "Research Methods",
    ),
    "English / Humanities": (
        "Academic Writing",
        "Literary Analysis",
        "Research Methods",
        "Critical Thinking",
        "Communication",
        "Ethics",
    ),
    "Hospitality / Tourism": (
        "Hospitality Operations",
        "Customer Service",
        "Food Safety",
        "Marketing",
        "Financial Accounting",
        "Event Management",
    ),
}

LEARNING_PATHS: dict[str, dict[str, list[str]]] = {
    "Computing": {
        "Python": ["Programming Fundamentals"],
        "Web Development": ["Programming Fundamentals"],
        "Machine Learning": [
            "Programming Fundamentals",
            "Statistics",
            "Linear Algebra",
        ],
        "Cloud Computing": ["Computer Networks", "Operating Systems"],
        "Cybersecurity": ["Computer Networks", "Operating Systems"],
        "Data Analysis": ["Statistics"],
        "SQL": ["Database Systems"],
        "Software Testing": ["Programming Fundamentals"],
        "Git": [],
    },
    "Business": {
        "Financial Modeling": ["Financial Accounting"],
        "Business Analytics": ["Business Statistics"],
        "Digital Marketing": ["Marketing"],
        "Excel": [],
        "Project Management": [],
        "SQL": [],
        "Data Visualization": ["Statistics"],
    },
    "Engineering": {
        "CAD": ["Engineering Mechanics"],
        "Engineering Simulation": ["Calculus", "Physics"],
        "Quality Assurance": ["Statistics"],
        "Project Management": [],
        "Technical Writing": [],
        "Python": [],
        "Sustainable Design": ["Physics"],
    },
    "Health": {
        "Clinical Reasoning": ["Anatomy", "Physiology"],
        "Medication Safety": ["Pharmacology"],
        "Evidence-Based Practice": ["Research Methods"],
        "Patient Communication": [],
        "Health Informatics": [],
        "Research Methods": [],
        "Public Health": [],
    },
    "Creative": {
        "Portfolio Development": ["Design Fundamentals"],
        "UX Research": ["Research Methods"],
        "Digital Storytelling": [],
        "Accessible Design": ["Design Fundamentals"],
        "Typography": ["Design Fundamentals"],
        "Project Management": [],
    },
    "Law": {
        "Legal Writing": ["Legal Research"],
        "Contract Analysis": ["Contract Law"],
        "Case Analysis": ["Legal Research"],
        "Professional Ethics": [],
        "Legal Technology Literacy": [],
    },
    "Education": {
        "Lesson Planning": ["Teaching Methods"],
        "Inclusive Education": ["Educational Psychology"],
        "Learning Assessment": ["Assessment"],
        "Digital Teaching": [],
        "Classroom Research": ["Research Methods"],
    },
    "Life Sciences": {
        "Laboratory Safety": [],
        "Data Analysis": ["Statistics"],
        "Bioinformatics": ["Genetics", "Statistics"],
        "Scientific Writing": ["Research Methods"],
        "Quality Control": ["Chemistry"],
    },
    "Agriculture": {
        "Sustainable Farming": ["Soil Science", "Crop Science"],
        "Precision Agriculture": ["Statistics"],
        "Farm Business Planning": ["Agricultural Economics"],
        "Research Methods": [],
        "Field Data Collection": [],
    },
    "Hospitality": {
        "Guest Experience": ["Customer Service"],
        "Food Safety": [],
        "Event Planning": ["Event Management"],
        "Revenue Management": ["Financial Accounting"],
        "Digital Marketing": ["Marketing"],
    },
    "General": {
        "Research Methods": [],
        "Data Literacy": ["Statistics"],
        "Academic Writing": [],
        "Professional Communication": [],
        "Project Management": [],
        "Digital Literacy": [],
        "Presentation Skills": [],
        "Ethical AI Literacy": [],
    },
}


def degree_key(degree: str) -> str | None:
    """Resolve common degree names without requiring a particular institution."""
    text = degree.casefold()
    aliases = {
        "BSc Nursing": "Nursing",
        "B.S. Business Analytics": "Data Science / Business Analytics",
    }
    if degree in aliases:
        return aliases[degree]
    for key in DEGREE_SUBJECTS:
        if key.casefold() in text or any(
            part.strip().casefold() in text for part in key.split(" / ")
        ):
            return key
    return None


def subject_options(degree: str) -> list[str]:
    """Return suggested core subjects plus a custom-subject escape hatch."""
    return list(
        DEGREE_SUBJECTS.get(
            degree_key(degree) or "",
            ("Research Methods", "Communication", "Statistics"),
        )
    ) + ["Other"]


def semester_limit(education_level: str, year: int = 1) -> int:
    """Two semesters per year; undergraduate level takes precedence."""
    match = re.search(r"Year (\d+)", education_level)
    return 2 * max(1, min(8, int(match.group(1)) if match else int(year)))


def grade_score(value: Any, scale: str) -> float | None:
    """Validate rather than guess the scale of a reported grade."""
    if value is None or not str(value).strip():
        return None
    letters = {
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
    if scale == "Letter (A-F)":
        if str(value).strip().upper() not in letters:
            raise ValueError("Use A+, A, A-, B+, B, B-, C+, C, C-, D, or F.")
        return float(letters[str(value).strip().upper()])
    try:
        number = float(str(value).replace("%", "").strip())
    except ValueError as exc:
        raise ValueError("Enter a numeric grade for this scale.") from exc
    maximum = 4 if scale == "GPA (0-4.0)" else 100
    if not 0 <= number <= maximum:
        raise ValueError(f"Grade must be between 0 and {maximum}.")
    return round(number / maximum * 100, 1)


def save_semester(
    twin: dict[str, Any],
    *,
    year: int,
    current_semester: int | None,
    number: int,
    courses: list[dict[str, Any]],
    scale: str,
) -> dict[str, Any]:
    """Upsert a semester, preserving other semesters and all learning evidence."""
    result = deepcopy(twin)
    maximum = semester_limit(result["profile"].get("education_level", ""), year)
    if not 1 <= number <= maximum or (
        current_semester is not None and not 1 <= current_semester <= maximum
    ):
        raise ValueError(f"Your year allows semesters 1 to {maximum}.")
    semesters = result.setdefault("academic", {}).setdefault("semesters", [])
    if any(s["number"] > maximum for s in semesters):
        raise ValueError(
            "Existing semesters exceed this year. Correct your study year first; no records were removed."
        )
    if current_semester is not None and (
        number > current_semester
        or any(s["number"] > current_semester for s in semesters)
    ):
        raise ValueError("Completed semesters must precede your current semester.")
    normalized = []
    if len(courses) > 16:
        raise ValueError("Enter up to 16 subjects per semester.")
    for row in courses:
        name = str(
            row.get("custom_subject")
            if row.get("name") == "Other"
            else row.get("name") or ""
        ).strip()
        if not name:
            continue
        score = grade_score(row.get("grade"), scale)
        if current_semester != number and score is None:
            raise ValueError(f"Add a grade for completed subject {name}.")
        if any(c["name"].casefold() == name.casefold() for c in normalized):
            raise ValueError("A subject can appear only once within a semester.")
        normalized.append(
            {
                "name": name[:150],
                "grade": row.get("grade", ""),
                "score": score,
                "core": bool(row.get("core", True)),
                "semester": number,
                "grade_scale": scale,
            }
        )
    if not normalized:
        raise ValueError("Add at least one subject.")
    record = {
        "number": number,
        "status": "current" if number == current_semester else "completed",
        "courses": normalized,
        "grade_scale": scale,
    }
    semesters[:] = sorted(
        [s for s in semesters if s["number"] != number] + [record],
        key=lambda s: s["number"],
    )
    for semester in semesters:
        semester["status"] = (
            "current" if semester["number"] == current_semester else "completed"
        )
        if semester["status"] == "completed" and any(
            c.get("score") is None for c in semester["courses"]
        ):
            raise ValueError(
                f"Add final grades to semester {semester['number']} before marking it completed or advancing your current semester."
            )
    academic = result["academic"]
    # Preserve pre-semester records explicitly, rather than silently replacing them.
    if "legacy_courses" not in academic:
        academic["legacy_courses"] = academic.get("courses", [])
    academic.update(
        {
            "study_year": year,
            "current_semester": current_semester,
            "semester_limit": maximum,
        }
    )
    academic["courses"] = [c for s in semesters for c in s["courses"]]
    academic["grades"] = {
        f"S{c['semester']}: {c['name']}": c["grade"] for c in academic["courses"]
    }
    return result


def academic_priorities(twin: dict[str, Any]) -> dict[str, Any]:
    """Use latest subject attempt; retain original grades after remediation."""
    from modules.digital_twin import _normalize_grade_to_score

    latest = {}
    for course in sorted(
        twin.get("academic", {}).get("courses", []), key=lambda c: c.get("semester", 0)
    ):
        name = course["name"].casefold()
        score = (
            course.get("score")
            if "score" in course
            else _normalize_grade_to_score(course.get("grade"))
        )
        previous = latest.get(name)
        if score is None and previous:
            previous_score = (
                previous.get("score")
                if "score" in previous
                else _normalize_grade_to_score(previous.get("grade"))
            )
            course = {**course, "score": previous_score}
        latest[name] = course
    assessed = {
        c.get("skill", "").casefold()
        for c in twin.get("learning_courses", [])
        if c.get("status") == "passed" and not c.get("assessment_offline")
    }
    weak, current = [], []
    active = twin.get("academic", {}).get("current_semester")
    for course in latest.values():
        score = (
            course.get("score")
            if "score" in course
            else _normalize_grade_to_score(course.get("grade"))
        )
        item = {
            "subject": course["name"],
            "score": score,
            "core": course.get("core", True),
            "semester": course.get("semester"),
            "remediation_assessed": course["name"].casefold() in assessed,
        }
        if score is not None and score < 60 and not item["remediation_assessed"]:
            weak.append(item)
        if active is not None and course.get("semester") == active:
            current.append(item)
    return {
        "weak_subjects": sorted(weak, key=lambda c: (not c["core"], c["score"])),
        "current_subjects": current,
    }


def learning_options(twin: dict[str, Any]) -> list[dict[str, Any]]:
    """Degree-relevant options with conservative, explainable prerequisites."""
    key = degree_key(twin.get("profile", {}).get("degree", "")) or ""
    if key in (
        "Computer Science",
        "Software Engineering",
        "Information Technology",
        "Data Science / Business Analytics",
    ):
        group = "Computing"
    elif key in ("Business Administration", "Accounting / Finance"):
        group = "Business"
    elif "Engineering" in key:
        group = "Engineering"
    elif key in ("Medicine", "Nursing", "Pharmacy"):
        group = "Health"
    elif key in ("Arts / Design", "Architecture", "Media / Communication"):
        group = "Creative"
    elif key in ("Law", "Education", "Agriculture"):
        group = key
    elif key == "Biology / Biotechnology":
        group = "Life Sciences"
    elif key == "Hospitality / Tourism":
        group = "Hospitality"
    else:
        group = "General"
    weak = {
        c["subject"].casefold(): c for c in academic_priorities(twin)["weak_subjects"]
    }
    known = {
        s["name"].casefold(): s.get("proficiency", 0)
        for s in twin.get("skills", [])
        if isinstance(s, dict)
    }
    for course in twin.get("academic", {}).get("courses", []):
        if course.get("score") is not None:
            known[course["name"].casefold()] = course["score"]
    options = []
    for name, prerequisites in (
        LEARNING_PATHS[group] | LEARNING_PATHS["General"]
    ).items():
        blocked = [
            p
            for p in prerequisites
            if p.casefold() in weak or known.get(p.casefold(), 0) < 60
        ]
        options.append(
            {
                "name": name,
                "kind": "skill",
                "prerequisites": prerequisites,
                "foundations_first": blocked,
                "rationale": (
                    "Build these foundations first: " + ", ".join(blocked)
                    if blocked
                    else "Relevant next step for your degree; confirm readiness with an assessment."
                ),
            }
        )
    present = {o["name"].casefold() for o in options}
    for subject in DEGREE_SUBJECTS.get(key, ()):
        if subject.casefold() not in present:
            options.append(
                {
                    "name": subject,
                    "kind": "skill",
                    "prerequisites": [],
                    "foundations_first": [],
                    "rationale": "Degree foundation; use your institution's syllabus to choose relevant units.",
                }
            )
    for item in academic_priorities(twin)["weak_subjects"]:
        options.insert(
            0,
            {
                "name": item["subject"],
                "kind": "skill",
                "prerequisites": [],
                "foundations_first": [],
                "rationale": f"Priority academic recovery: reported score {item['score']}/100.",
            },
        )
    return options


def prioritize_academic_work(plan: Any, twin: dict[str, Any]) -> Any:
    """Guarantee academic recovery precedes optional work within the same time cap."""
    from ai.schemas import LearningTask

    result = plan.model_copy(deep=True)
    priorities = academic_priorities(twin)
    weak = priorities["weak_subjects"]
    current = priorities["current_subjects"]
    goals = {g.get("name", "").casefold() for g in twin.get("goals", [])}
    foundations = list(
        dict.fromkeys(
            p
            for o in learning_options(twin)
            if o["name"].casefold() in goals
            for p in o["foundations_first"]
        )
    )
    for week in result.weeks:
        required = []
        if weak:
            subject = weak[(week.week - 1) % len(weak)]["subject"]
            required.append(
                LearningTask(
                    title=f"Recover {subject}: foundation practice {week.week}",
                    minutes=30,
                    category="academic",
                    evidence_required="Correct a problem set, explain the concepts, then complete a formative assessment in Learning & Assessments.",
                    resource=f"Your {subject} lecture notes, instructor feedback and verified course resources",
                )
            )
        if current:
            subject = current[(week.week - 1) % len(current)]["subject"]
            if not required or subject not in required[0].title:
                required.append(
                    LearningTask(
                        title=f"Current semester: {subject} practice {week.week}",
                        minutes=30,
                        category="academic",
                        evidence_required="Complete the week's coursework, record one difficult concept, and ask your coach for help.",
                        resource=f"Your current {subject} syllabus and course materials",
                    )
                )
        if foundations and len(required) < 2:
            subject = foundations[(week.week - 1) % len(foundations)]
            if not any(subject in task.title for task in required):
                required.append(
                    LearningTask(
                        title=f"Foundation before advanced goals: {subject} ({week.week})",
                        minutes=30,
                        category="academic",
                        evidence_required="Explain the concept and complete introductory exercises before advancing.",
                        resource=f"Verified introductory {subject} resources in Learning & Assessments",
                    )
                )
        if required:
            week.tasks = (required + week.tasks)[:4]
    return result
