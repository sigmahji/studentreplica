"""Semester editor; each save is explicitly scoped to the signed-in student."""

from __future__ import annotations

import streamlit as st

from ai.service import AIService
from modules.academics import (
    academic_priorities,
    save_semester,
    semester_limit,
    subject_options,
)
from modules.digital_twin import GRADE_SCALE_OPTIONS
from modules.planning_ui import analyze_student
from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository


def render_academics(ctx: UserContext, ai: AIService) -> None:
    """Edit completed and current semesters without dropping prior records."""
    st.markdown("### My Semesters")
    with session_scope() as session:
        twin = TwinRepository(session).get_twin(ctx)
    if not twin:
        st.info("Save your profile first.")
        return
    academic = twin.get("academic", {})
    level = twin["profile"].get("education_level", "")
    year = st.number_input(
        "Academic year",
        1,
        8,
        (
            semester_limit(level) // 2
            if "Year " in level
            else int(academic.get("study_year", 1))
        ),
        disabled="Year " in level,
    )
    maximum = semester_limit(level, year)
    st.caption(
        f"{twin['profile'].get('degree', '')} | Up to {maximum} semesters for this study year"
    )
    current = st.selectbox(
        "Currently enrolled semester",
        [None] + list(range(1, maximum + 1)),
        index=(
            ([None] + list(range(1, maximum + 1))).index(
                academic.get("current_semester")
            )
            if academic.get("current_semester") in range(1, maximum + 1)
            else 0
        ),
        format_func=lambda n: (
            "Between semesters / all entered semesters completed"
            if n is None
            else f"Semester {n}"
        ),
    )
    number = st.selectbox(
        "Semester to add / update", range(1, (current or maximum) + 1)
    )
    saved = next(
        (s for s in academic.get("semesters", []) if s["number"] == number), {}
    )
    options = subject_options(twin["profile"].get("degree", ""))
    rows = []
    for course in saved.get("courses", []):
        rows.append(
            {
                "name": course["name"] if course["name"] in options else "Other",
                "custom_subject": "" if course["name"] in options else course["name"],
                "grade": (
                    str(course["grade"]) if course.get("grade") is not None else ""
                ),
                "core": course.get("core", True),
            }
        )
    if not rows:
        rows = [{"name": options[0], "custom_subject": "", "grade": "", "core": True}]
    scale = st.selectbox(
        "Semester grade scale",
        GRADE_SCALE_OPTIONS,
        index=GRADE_SCALE_OPTIONS.index(
            saved.get("grade_scale", GRADE_SCALE_OPTIONS[0])
        ),
    )
    scope = f"semester_{ctx.user_id}_{number}_{twin['profile'].get('degree')}"
    count = st.number_input(
        "Number of subjects",
        min_value=1,
        max_value=20,
        value=len(rows),
        key=f"{scope}_count",
    )
    edited = []
    for i in range(int(count)):
        row = (
            rows[i]
            if i < len(rows)
            else {"name": options[0], "grade": "", "core": True}
        )
        subject_col, grade_col, core_col = st.columns([3, 1, 1])
        with subject_col:
            chosen = st.selectbox(
                f"Semester subject {i + 1}",
                options,
                index=options.index(row["name"]),
                key=f"{scope}_subject_{i}",
            )
            custom = ""
            if chosen == "Other":
                custom = st.text_input(
                    f"Other semester subject {i + 1}",
                    value=row.get("custom_subject", ""),
                    max_chars=150,
                    key=f"{scope}_custom_{i}",
                )
        grade = grade_col.text_input(
            f"Semester grade {i + 1}",
            value=row["grade"],
            key=f"{scope}_grade_{i}",
        )
        core = core_col.checkbox(
            f"Core subject {i + 1}",
            value=row["core"],
            key=f"{scope}_core_{i}",
        )
        edited.append(
            {"name": chosen, "custom_subject": custom, "grade": grade, "core": core}
        )
    if st.button("Save semester & update guidance", type="primary"):
        try:
            with session_scope() as session:
                repo = TwinRepository(session)
                updated = save_semester(
                    repo.get_twin(ctx),
                    year=year,
                    current_semester=current,
                    number=number,
                    courses=edited,
                    scale=scale,
                )
                repo.save_twin(ctx, updated, label=f"semester_{number}_updated")
            analyze_student(ctx, ai)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    for semester in academic.get("semesters", []):
        with st.expander(
            f"Semester {semester['number']} | {semester['status'].title()}"
        ):
            st.dataframe(semester["courses"], hide_index=True, use_container_width=True)
    if academic.get("legacy_courses"):
        with st.expander("Earlier records awaiting semester assignment"):
            st.dataframe(academic["legacy_courses"], hide_index=True)
    priorities = academic_priorities(twin)
    if priorities["weak_subjects"]:
        st.warning(
            "Academic recovery priorities: "
            + ", ".join(c["subject"] for c in priorities["weak_subjects"])
        )
    if priorities["current_subjects"]:
        st.write(
            "Current semester focus:",
            ", ".join(c["subject"] for c in priorities["current_subjects"]),
        )
