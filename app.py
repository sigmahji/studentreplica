"""StudentReplica - Streamlit entry point.

Session stores user_id (+ UI flags only). Twin data always reloads by user_id.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st
from modules.ui import render_shell, render_bullets
from modules.dashboard_ui import render_dashboard, render_progress_chart

from ai.service import get_ai_service, reset_ai_service
from modules.digital_twin import (
    EDUCATION_LEVELS,
    build_twin_from_onboarding,
    compute_academic_stats,
    progress_timeline,
    seed_demo_twin,
)
from modules.market_matcher import get_local_job_catalog
from modules.career_planner import WEEKDAYS, confirm_learning_choices
from modules.planning_ui import analyze_student, render_career_plan
from modules.academics import DEGREE_SUBJECTS, degree_key, subject_options
from modules.academic_ui import render_academics
from modules.learning_ui import render_learning
from modules.market_ui import render_market
from modules.cv_ui import render_cv_studio
from storage.auth import create_account, get_account_by_user_id, login_account
from storage.context import UserContext
from storage.database import init_db, session_scope
from storage.repository import TwinRepository
from storage.twin_schema import twin_to_legacy_profile

st.set_page_config(
    page_title="StudentReplica",
    page_icon=str(
        Path(__file__).resolve().parent / "assets" / "studentreplica-logo.png"
    ),
    layout="wide",
)
init_db()

if "ai_force_mock" not in st.session_state:
    st.session_state["ai_force_mock"] = False
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

_ai = get_ai_service(force_mock=bool(st.session_state["ai_force_mock"]))

render_shell()

if _ai.offline_mode:
    st.warning(
        "**Offline / mock AI mode** - example responses. "
        "The configured AI provider is unavailable or mock mode is enabled."
    )


def _ctx() -> UserContext:
    uid = st.session_state.get("user_id")
    if not uid:
        raise RuntimeError("No authenticated user_id in session")
    return UserContext(user_id=str(uid), session_id="streamlit")


def _load_twin() -> dict | None:
    with session_scope() as session:
        return TwinRepository(session).get_twin(_ctx())


def _save_twin(twin: dict, label: str = "ui_save") -> None:
    with session_scope() as session:
        TwinRepository(session).save_twin(_ctx(), twin, label=label)


def _latest_artifact_payload(kind: str) -> dict | None:
    with session_scope() as session:
        artifacts = TwinRepository(session).list_artifacts(_ctx(), kind=kind)
    return artifacts[0]["payload"] if artifacts else None


# ---------------------------------------------------------------------------
# Auth gate — create account or log in (isolated twin per account)
# ---------------------------------------------------------------------------
if not st.session_state["logged_in"]:
    st.markdown("### Welcome — create an account or sign in")
    st.caption("Each account gets a private digital twin. Student data never mixes.")
    auth_tab, demo_tab = st.tabs(["Create / Login", "Quick demo (no password)"])

    with auth_tab:
        mode = st.radio("I want to", ["Create account", "Log in"], horizontal=True)
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        display_name = ""
        if mode == "Create account":
            display_name = st.text_input("Display name (optional)")
        if st.button("Continue", type="primary"):
            with session_scope() as session:
                if mode == "Create account":
                    result = create_account(
                        session,
                        username=username,
                        password=password,
                        display_name=display_name,
                    )
                else:
                    result = login_account(
                        session, username=username, password=password
                    )
            if result.ok and result.user_id:
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = result.user_id
                st.success(result.message)
                st.rerun()
            else:
                st.error(result.message)

    with demo_tab:
        st.write("Load a demo twin under a temporary isolated session (for judges).")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Demo student A (SE)"):
                from storage.context import new_user_context

                ctx = new_user_context(session_id="demo-a")
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = ctx.user_id
                with session_scope() as session:
                    TwinRepository(session).save_twin(
                        ctx, seed_demo_twin("a"), label="demo_a"
                    )
                st.rerun()
        with col_b:
            if st.button("Demo student B (Analytics)"):
                from storage.context import new_user_context

                ctx = new_user_context(session_id="demo-b")
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = ctx.user_id
                with session_scope() as session:
                    TwinRepository(session).save_twin(
                        ctx, seed_demo_twin("b"), label="demo_b"
                    )
                st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Authenticated app
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Account")
    with session_scope() as session:
        acct = get_account_by_user_id(session, st.session_state["user_id"])
    account_label = acct.username if acct else "demo session"
    st.write(f"Signed in as **{account_label}**")
    if acct:
        st.caption(f"Display name: {acct.display_name}")
    if st.button("Log out"):
        force_mock = st.session_state.get("ai_force_mock", False)
        theme = st.session_state.get("ui_theme", "Light")
        st.session_state.clear()
        st.session_state["ai_force_mock"] = force_mock
        st.session_state["ui_theme"] = theme
        st.session_state["logged_in"] = False
        st.rerun()

    st.markdown("---")
    st.markdown("### AI")
    st.caption(
        f"Provider: `{_ai.client.provider_name}` "
        f"({'offline' if _ai.offline_mode else 'live configured'})"
    )
    if _ai.client.model_name:
        st.caption(f"Model: `{_ai.client.model_name}`")
    if _ai.offline_mode and not st.session_state["ai_force_mock"]:
        if st.button("Reconnect AI"):
            reset_ai_service()
            st.rerun()
    st.session_state["ai_force_mock"] = st.checkbox(
        "Force mock AI",
        value=bool(st.session_state["ai_force_mock"]),
    )

twin = _load_twin()
profile = twin_to_legacy_profile(twin) if twin else None

(
    tab_dash,
    tab_onboard,
    tab_academic,
    tab_plan,
    tab_learning,
    tab_market,
    tab_cv,
    tab_history,
) = st.tabs(
    [
        "Dashboard",
        "Profile",
        "Semesters",
        "Career Plan",
        "Learning",
        "Jobs",
        "CV Studio",
        "History",
    ]
)

# ---- Onboarding: study level + subjects/grades ----
with tab_onboard:
    st.markdown("### Build your digital twin")
    saved_profile = (twin or {}).get("profile", {})
    saved_preferences = (twin or {}).get("learning_preferences", {})
    degree_choices = list(DEGREE_SUBJECTS) + ["Other"]
    selected_degree = st.selectbox(
        "Degree / program",
        degree_choices,
        index=degree_choices.index(
            degree_key(saved_profile.get("degree", "")) or "Other"
        ),
    )

    with st.container():
        name = st.text_input(
            "Full name",
            value=(twin or {}).get("profile", {}).get("name", "") if twin else "",
        )
        _default_level = (
            (twin or {}).get("profile", {}).get("education_level")
            if twin
            else "Undergraduate (Year 3)"
        )
        if _default_level not in EDUCATION_LEVELS:
            _default_level = "Undergraduate (Year 3)"
        education_level = st.selectbox(
            "Level of studies",
            EDUCATION_LEVELS,
            index=EDUCATION_LEVELS.index(_default_level),
        )
        institution = st.text_input(
            "Institution / School",
            value=(
                (twin or {}).get("profile", {}).get("institution", "") if twin else ""
            ),
        )
        degree = (
            saved_profile.get("degree", selected_degree)
            if degree_key(saved_profile.get("degree", "")) == selected_degree
            else selected_degree
        )
        if selected_degree == "Other":
            degree = st.text_input(
                "Program / Degree / Track",
                value=saved_profile.get("degree", ""),
                key="degree_name_Other",
                max_chars=150,
            )
        fields = (
            [""]
            + sorted({job["field"] for job in get_local_job_catalog()})
            + ["Other / interdisciplinary"]
        )
        saved_field = saved_profile.get("field_of_study", "")
        if saved_field not in fields:
            fields.append(saved_field)
        field_of_study = st.selectbox(
            "Field of study", fields, index=fields.index(saved_field)
        )
        if field_of_study == "Other / interdisciplinary":
            field_of_study = (
                st.text_input("Other field of study", max_chars=150) or field_of_study
            )
        loc1, loc2, loc3 = st.columns(3)
        city = loc1.text_input(
            "Your city", value=saved_profile.get("city", ""), max_chars=100
        )
        university_city = loc2.text_input(
            "University / school city",
            value=saved_profile.get("university_city", ""),
            max_chars=100,
        )
        country = loc3.text_input(
            "Country", value=saved_profile.get("country", ""), max_chars=80
        )
        work_modes = ["Local or remote", "Local", "Remote"]
        work_preference = st.radio(
            "Work preference",
            work_modes,
            index=work_modes.index(
                saved_profile.get("work_preference", "Local or remote")
            ),
            horizontal=True,
        )
        graduation = st.date_input(
            "Expected graduation / course completion",
            value=(
                date.fromisoformat(saved_profile["graduation_date"])
                if saved_profile.get("graduation_date")
                else None
            ),
        )
        interests_raw = st.text_input(
            "Interests (comma-separated)",
            value=(
                ", ".join((twin or {}).get("profile", {}).get("interests", []))
                if twin
                else ""
            ),
        )
        goals_raw = st.text_input(
            "Career goals (comma-separated)",
            value=(
                ", ".join((twin or {}).get("profile", {}).get("career_goals", []))
                if twin
                else ""
            ),
        )
        earned_skills = st.text_input(
            "Skills I have learned (comma-separated)",
            value=", ".join(
                s["name"] for s in (twin or {}).get("skills", []) if isinstance(s, dict)
            ),
        )
        achievements_raw = st.text_area(
            "Certificates / achievements already earned (one per line)",
            value="\n".join(str(a) for a in (twin or {}).get("achievements", [])),
            max_chars=3000,
        )
        desired_skills = st.text_input(
            "Skills / qualifications I want to earn (comma-separated)",
            value=", ".join(
                goal["name"]
                for goal in (twin or {}).get("goals", [])
                if isinstance(goal, dict)
                and goal.get("kind") in ("skill", "certificate")
            ),
        )

        st.markdown("#### Initial subjects & grades")
        saved_courses = (twin or {}).get("academic", {}).get("courses", [])
        n_subjects = st.number_input(
            "How many subjects to enter?",
            min_value=1,
            max_value=12,
            value=min(12, len(saved_courses)) if saved_courses else 3,
        )
        subjects: list[dict] = []
        for i in range(int(n_subjects)):
            c1, c2 = st.columns([2, 1])
            default_name = (
                saved_courses[i].get("name", "") if i < len(saved_courses) else ""
            )
            with c1:
                choices = subject_options(degree)
                chosen_subject = st.selectbox(
                    f"Subject choice {i + 1}",
                    choices,
                    index=(
                        choices.index(default_name)
                        if default_name in choices
                        else (
                            len(choices) - 1
                            if default_name
                            else min(i, len(choices) - 2)
                        )
                    ),
                    key=f"subject_choice_{selected_degree}_{i}",
                )
                sub_name = (
                    st.text_input(
                        f"Subject {i + 1}", value=default_name, key=f"sub_name_{i}"
                    )
                    if chosen_subject == "Other"
                    else chosen_subject
                )
            with c2:
                grade = st.text_input(
                    f"Grade {i + 1}",
                    value=(
                        str(saved_courses[i].get("grade") or "")
                        if i < len(saved_courses)
                        else ""
                    ),
                    key=f"sub_grade_{i}",
                    placeholder="e.g. 85, 3.7, B+",
                )
            subjects.append({"name": sub_name, "grade": grade})

        habits = st.multiselect(
            "Study habits",
            [
                "Daily practice",
                "Group study",
                "Flashcards",
                "Project-based learning",
                "Tutorials / videos",
                "Past papers",
            ],
            default=(twin or {}).get("academic", {}).get("study_habits", []),
        )
        st.markdown("#### Free time for your roadmap")
        day_modes = ["Choose my days", "AI recommends available days"]
        day_mode = st.radio(
            "Study-day preference",
            day_modes,
            index=day_modes.index(saved_preferences.get("day_mode", day_modes[0])),
            horizontal=True,
        )
        selected_days = []
        if day_mode == "Choose my days":
            selected_days = st.multiselect(
                "Preferred study days",
                WEEKDAYS,
                default=saved_preferences.get(
                    "selected_days", ["Tuesday", "Thursday", "Saturday"]
                ),
            )
        protected_days = st.multiselect(
            "Protected days / no extra study",
            WEEKDAYS,
            default=saved_preferences.get("protected_days", ["Sunday"]),
        )
        commitments = st.text_input(
            "Other commitments",
            value=saved_preferences.get("commitments", ""),
            max_chars=1000,
        )
        daily_minutes = {}
        time_columns = st.columns(4)
        for i, day in enumerate(WEEKDAYS):
            daily_minutes[day] = time_columns[i % 4].number_input(
                f"{day} free minutes",
                min_value=0,
                max_value=240,
                step=15,
                value=int(
                    saved_preferences.get("daily_minutes", {}).get(
                        day, 60 if day in selected_days else 0
                    )
                ),
                help="Time remaining after classes, work, travel, sleep, and personal activities.",
            )
        start_date = st.date_input(
            "Roadmap start date",
            value=max(
                date.today(),
                date.fromisoformat(
                    saved_preferences.get("start_date") or date.today().isoformat()
                ),
            ),
            min_value=date.today(),
        )
        plan_weeks = st.number_input(
            "Roadmap weeks",
            min_value=1,
            max_value=12,
            value=int(saved_preferences.get("plan_weeks", 4)),
        )
        submitted = st.button(
            "Save twin & analyze", type="primary", icon=":material/check:"
        )

    if submitted:
        new_twin = build_twin_from_onboarding(
            name=name or "Student",
            education_level=education_level,
            institution=institution,
            degree=degree,
            interests=[x.strip() for x in interests_raw.split(",") if x.strip()],
            career_goals=[x.strip() for x in goals_raw.split(",") if x.strip()],
            subjects=subjects,
            study_habits=habits,
            profile_details={
                "field_of_study": field_of_study,
                "city": city,
                "university_city": university_city,
                "country": country,
                "work_preference": work_preference,
                "graduation_date": graduation.isoformat() if graduation else "",
            },
            learning_preferences={
                **saved_preferences,
                "day_mode": day_mode,
                "selected_days": selected_days,
                "protected_days": protected_days,
                "daily_minutes": daily_minutes,
                "commitments": commitments,
                "start_date": start_date.isoformat(),
                "plan_weeks": int(plan_weeks),
            },
            achievements=[
                line.strip() for line in achievements_raw.splitlines() if line.strip()
            ],
            existing_twin=twin,
        )
        new_twin = confirm_learning_choices(
            new_twin,
            [
                {"name": s.strip(), "kind": "skill"}
                for s in earned_skills.split(",")
                if s.strip()
            ],
            [
                {"name": s.strip(), "kind": "skill"}
                for s in desired_skills.split(",")
                if s.strip()
            ],
        )
        _save_twin(new_twin, label="onboarding")
        twin = _load_twin()
        profile = twin_to_legacy_profile(twin)
        st.success("Twin saved for your account only.")
        analyze_student(_ctx(), _ai)
        stats = compute_academic_stats(twin)
        if stats.get("average_score") is not None:
            st.metric("Academic average (normalized /100)", stats["average_score"])

with tab_academic:
    render_academics(_ctx(), _ai)

# ---- Twin Dashboard ----
with tab_dash:
    render_dashboard(_ctx(), _ai)

with tab_plan:
    render_career_plan(_ctx(), _ai)

with tab_learning:
    render_learning(_ctx(), _ai)

# ---- Market Matcher ----
with tab_market:
    selected_job = render_market(_ctx(), _ai)

# ---- CV Studio ----
with tab_cv:
    render_cv_studio(_ctx(), _ai, selected_job)

# ---- History / timeline ----
with tab_history:
    st.markdown("### Progress history")
    st.caption("Versioned twin snapshots for this account only.")
    with session_scope() as session:
        snaps = TwinRepository(session).list_snapshots(_ctx())
    timeline = progress_timeline(snaps)
    if not timeline:
        st.info("No snapshots yet — save your twin to start history.")
    else:
        render_progress_chart(snaps, key="history_progress")
        for item in timeline:
            with st.expander(
                f"Version {item['version']} | {item['label'].replace('_', ' ').title()}"
            ):
                st.caption(item.get("created_at"))
                a, b, c = st.columns(3)
                a.metric("Skills", item["skill_count"])
                b.metric("Milestones", item.get("completed_milestones", 0))
                c.metric(
                    "Academic average",
                    (
                        item["average_score"]
                        if item.get("average_score") is not None
                        else "Not graded"
                    ),
                )
        if len(timeline) >= 2:
            st.markdown("#### Compare latest vs previous")
            latest, prev = timeline[0], timeline[1]
            c1, c2 = st.columns(2)
            for column, title, point in (
                (c1, "Latest", latest),
                (c2, "Previous", prev),
            ):
                with column:
                    st.markdown(f"**{title} - version {point['version']}**")
                    render_bullets(
                        [
                            f"Skills tracked: {point['skill_count']}",
                            f"Completed milestones: {point['completed_milestones']}",
                            f"Academic average: {point['average_score'] if point['average_score'] is not None else 'Not graded'}",
                        ]
                    )
