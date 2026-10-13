"""A resumable first-visit tour, persisted independently for each account."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Literal

import streamlit as st

from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository


@dataclass(frozen=True)
class TourStep:
    """One destination in the existing student workflow."""

    section: str
    title: str
    detail: str


TOUR_STEPS = (
    TourStep(
        "Profile", "Start with your studies",
        "Your degree, university, interests, location and graduation target.",
    ),
    TourStep(
        "Semesters", "Establish your academic baseline",
        "Completed semesters, grades, core subjects and current coursework.",
    ),
    TourStep(
        "Career Plan", "Choose your next priorities",
        "Your career direction, weak foundations and study time after other commitments.",
    ),
    TourStep(
        "Learning", "Turn learning into evidence",
        "Free or paid courses, practice and an 80% assessment target.",
    ),
    TourStep(
        "Jobs", "Explore your opportunities",
        "Internships, roles, your location and the skills still needed for each opportunity.",
    ),
    TourStep(
        "CV Studio", "Bring your achievements together",
        "Your actual education, skills and projects, with an optional photo and PDF or Word export.",
    ),
    TourStep(
        "Dashboard", "Check your direction",
        "Recorded progress, skill coverage and your next academic or career priorities.",
    ),
    TourStep(
        "History", "Keep your growth in view",
        "Earlier snapshots, completed milestones and changes in your academic progress.",
    ),
)

TourStatus = Literal["in_progress", "skipped", "completed"]


@dataclass(frozen=True)
class TourState:
    """Only navigation preferences; never academic or assessed achievements."""

    step: int = 0
    status: TourStatus = "in_progress"


def load_tour_state(ctx: UserContext) -> TourState | None:
    """Read the latest tour record belonging only to this student."""
    with session_scope() as session:
        records = TwinRepository(session).list_artifacts(ctx, kind="onboarding_tour")
    if not records:
        return None
    payload = records[0]["payload"]
    step, status = payload.get("step"), payload.get("status")
    if type(step) is not int or not 0 <= step < len(TOUR_STEPS):
        return TourState()
    if status not in ("in_progress", "skipped", "completed"):
        return TourState()
    return TourState(step=step, status=status)


def save_tour_state(
    ctx: UserContext, step: int, status: TourStatus = "in_progress"
) -> TourState:
    """Save navigation progress without changing the twin or its snapshots."""
    if type(step) is not int or not 0 <= step < len(TOUR_STEPS):
        raise ValueError("Invalid tour step")
    if status not in ("in_progress", "skipped", "completed"):
        raise ValueError("Invalid tour status")
    with session_scope() as session:
        TwinRepository(session).save_artifact(
            ctx, "onboarding_tour", {"version": 1, "step": step, "status": status}
        )
    return TourState(step=step, status=status)


def _navigate_tour(ctx: UserContext, step: int, status: TourStatus = "in_progress") -> None:
    save_tour_state(ctx, step, status)
    st.session_state["workspace_tab"] = (
        TOUR_STEPS[step].section if status == "in_progress" else "Profile"
    )
    st.rerun()


def render_guided_tour(ctx: UserContext, *, automatic: bool) -> str:
    """Render optional guidance and return the main tab's default destination."""
    state = load_tour_state(ctx)
    with st.sidebar:
        st.divider()
        if st.button("Quick tour", icon=":material/explore:", key="tour_restart"):
            _navigate_tour(ctx, 0)

    if state is None and automatic:
        state = save_tour_state(ctx, 0)
    if state is None or state.status != "in_progress":
        return st.session_state.get("workspace_tab", "Dashboard")

    step = TOUR_STEPS[state.step]
    last = state.step == len(TOUR_STEPS) - 1
    with st.container(key="guided_tour"):
        st.markdown(
            '<div class="tour-topline"><span class="section-kicker">'
            f'Getting started / {escape(step.section)}</span>'
            f'<span class="tour-count">{state.step + 1} / {len(TOUR_STEPS)}</span></div>'
            '<div class="tour-copy" aria-live="polite">'
            f'<h3>{escape(step.title)}</h3><p>{escape(step.detail)}</p></div>',
            unsafe_allow_html=True,
        )
        st.progress((state.step + 1) / len(TOUR_STEPS))
        with st.container(horizontal=True, key="tour_actions"):
            if st.button(
                "Back", icon=":material/arrow_back:", key="tour_back",
                help="Previous tour step", disabled=state.step == 0,
            ):
                _navigate_tour(ctx, state.step - 1)
            if last:
                if st.button(
                    "Start my profile", type="primary", icon=":material/person:",
                    key="tour_finish",
                ):
                    _navigate_tour(ctx, state.step, "completed")
            else:
                if st.button(
                    "Next", type="primary", icon=":material/arrow_forward:",
                    key="tour_next", help=f"Next: {TOUR_STEPS[state.step + 1].section}",
                ):
                    _navigate_tour(ctx, state.step + 1)
                if st.button(
                    "Skip tour", icon=":material/close:", key="tour_skip",
                ):
                    _navigate_tour(ctx, state.step, "skipped")
    return step.section
