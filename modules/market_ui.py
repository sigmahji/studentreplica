"""Source-backed openings, useful search actions, and separate role matches."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlencode

import streamlit as st

from ai.service import AIService, RateLimitExceeded
from modules.career_planner import confirm_learning_choices, rank_career_references
from modules.market_matcher import get_local_job_catalog, rank_jobs
from modules.ui import render_bullets
from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository


def job_search_links(profile: dict) -> list[tuple[str, str]]:
    """Link to real search pages; these links are not claimed to be vacancies."""
    goals = profile.get("career_goals") or []
    title = str(
        goals[0]
        if goals
        else profile.get("degree") or profile.get("field_of_study") or "student"
    )[:150]
    location = ", ".join(
        str(v)
        for v in (
            profile.get("city") or profile.get("university_city"),
            profile.get("country"),
        )
        if v
    )
    if profile.get("work_preference") == "Remote":
        location = "Remote"
    return [
        (
            "LinkedIn openings",
            "https://www.linkedin.com/jobs/search/?"
            + urlencode(
                {"keywords": title + " internship graduate", "location": location}
            ),
        ),
        (
            "Indeed openings",
            "https://www.indeed.com/jobs?"
            + urlencode({"q": title + " entry level", "l": location}),
        ),
    ]


def _explain(ctx: UserContext, ai: AIService, job: dict, *, key: str) -> None:
    if not st.button(
        "Explain fit with AI",
        key=key,
        disabled=job["match_score"] is None,
        icon=":material/auto_awesome:",
    ):
        return
    try:
        with st.spinner("Reviewing your skills against this role..."):
            with session_scope() as session:
                result = ai.explain_career_match(
                    session,
                    ctx,
                    job,
                    match_score=job["match_score"],
                    matched_skills=job["matched_skills"],
                    missing_skills=job["missing_skills"],
                )
        st.write(result.fit_summary)
        st.caption(f"Confidence: {result.confidence:.0%} | {result.notice}")
        render_bullets(result.evidence_used)
    except RateLimitExceeded:
        st.warning("Please wait a minute before another AI explanation.")


def _job_card(
    ctx: UserContext, ai: AIService, job: dict, *, reference: bool = False
) -> None:
    with st.container(border=True):
        heading, coverage = st.columns([3, 1])
        heading.markdown(f"#### {job['title']}")
        heading.caption(
            job.get("field", "Reference role")
            if reference
            else f"{job['company']} | {job['location']}"
        )
        score = job["match_score"]
        coverage.metric(
            "Skill coverage", f"{score}%" if score is not None else "Unscored"
        )
        if score is not None:
            st.progress(score / 100)
        st.write(
            "**Your strengths:** "
            + (", ".join(job["matched_skills"]) or "No matching skills recorded yet")
        )
        st.write(
            "**To develop:** "
            + (
                ", ".join(job["missing_skills"])
                or "No identified gaps / requirements not supplied"
            )
        )
        if not reference:
            if job.get("publisher"):
                st.caption(
                    f"Source: {job['publisher']} | Level: {job.get('experience_level', 'Not supplied')}"
                )
            st.link_button(
                "View source listing", job["url"], icon=":material/open_in_new:"
            )
            st.caption(
                f"Published: {job.get('published_date') or 'Not supplied'} | Verify availability with the employer."
            )
        _explain(
            ctx,
            ai,
            job,
            key=f"explain_{'role' if reference else 'opening'}_{ctx.user_id}_{job['id']}",
        )


def render_market(ctx: UserContext, ai: AIService) -> dict | None:
    """Make opportunities visible without inventing openings or calling AI on reruns."""
    st.markdown("### Opportunities for your next step")
    with session_scope() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx)
        saved = repo.list_artifacts(ctx, kind="live_market")
    if not twin:
        st.info("Add your study details in Profile to find relevant opportunities.")
        return None
    profile = twin["profile"]
    payload = saved[0]["payload"] if saved else None
    location = (
        profile.get("city") or profile.get("university_city") or "Location not added"
    )
    st.caption(
        f"{profile.get('degree') or profile.get('field_of_study') or 'Your field'} | {location} | Skill coverage is not a hiring probability."
    )
    if st.button(
        "Research live jobs & field trends", type="primary", icon=":material/search:"
    ):
        try:
            with st.spinner(
                "Searching individual openings and checking the evidence..."
            ):
                with session_scope() as session:
                    payload = ai.analyze_live_market(session, ctx)
        except RateLimitExceeded:
            st.warning("Please wait a minute before another market search.")
        except Exception as exc:
            logging.getLogger("student_twin.ui").warning(
                "event=market_ui_unavailable user_id=%s err=%s",
                ctx.user_id,
                type(exc).__name__,
            )
            st.warning(
                "Live research is temporarily unavailable. Your saved results and search links remain available."
            )
    search_columns = st.columns(2)
    for column, (label, url) in zip(search_columns, job_search_links(profile)):
        column.link_button(
            label, url, icon=":material/open_in_new:", width="stretch"
        )
    if payload and payload.get("jobs"):
        live_tab, roles_tab = st.tabs(["Source-backed openings", "Role matches"])
    else:
        roles_tab, live_tab = st.tabs(["Role matches", "Source-backed openings"])
    live_selected = None
    with live_tab:
        if not payload:
            st.info("No live search yet. Your role matches are ready in Role matches.")
        else:
            market, analysis = payload["market"], payload["analysis"]
            st.caption(
                f"Researched {market['retrieved_at'][:16]} | {market.get('location') or location}"
            )
            if market["mode"] != "live_web":
                st.warning(market["notice"])
            elif market.get("scope") == "remote":
                st.info(market["notice"])
            if payload.get("offline_mode"):
                st.warning(
                    "Offline analysis. No AI-generated example is shown as a real vacancy."
                )
            modes = [
                "All openings",
                "Strong match (70%+)",
                "Around 60% (50-69%)",
                "My interests",
                "Internship / graduate titles",
            ]
            mode = st.radio("Filter openings", modes, horizontal=True)
            ranked = rank_jobs(twin, payload.get("jobs", []))
            jobs = [
                j
                for j in ranked
                if mode == modes[0]
                or mode == modes[1]
                and j["strong_match"]
                or mode == modes[2]
                and j["near_match"]
                or mode == modes[3]
                and j["interest_match"]
                or mode == modes[4]
                and bool(
                    re.search(
                        r"\b(intern|internship|graduate|junior|trainee|entry.level)\b",
                        j["title"],
                        re.I,
                    )
                )
            ]
            st.caption(
                f"{len(jobs)} openings shown | {len(ranked)} source-backed results"
            )
            if not jobs:
                st.info(
                    "No supported individual listings for this selection. Try All openings, refresh the search, or use the location-based search links above."
                )
            for job in jobs:
                _job_card(ctx, ai, job)
            if jobs:
                chosen = st.selectbox(
                    "Live opening for my career plan / CV",
                    [None] + list(range(len(jobs))),
                    format_func=lambda i: (
                        "Choose an opening (optional)"
                        if i is None
                        else jobs[i]["title"]
                    ),
                )
                if chosen is not None:
                    live_selected = jobs[chosen]
            if analysis.get("emerging_advice"):
                st.markdown("#### Skills worth watching")
                st.write(analysis["emerging_advice"])
                st.caption(
                    f"Confidence: {analysis['confidence']:.0%} | {analysis['notice']}"
                )
            with st.expander("Market sources & reasoning"):
                render_bullets(analysis.get("evidence_used", []))
                for source in market["sources"]:
                    st.link_button(source["title"], source["url"])
                    st.caption(
                        source.get("published_date") or "Publication date not supplied"
                    )
                    st.write(source["snippet"])
    with roles_tab:
        st.caption(
            "Learning references, not advertised vacancies. Ranked for your field, interests and recorded skills."
        )
        references = rank_jobs(twin, rank_career_references(twin))
        for job in references[:4]:
            _job_card(ctx, ai, job, reference=True)
        all_references = rank_jobs(twin, get_local_job_catalog())
        index = st.selectbox(
            "Target role",
            range(len(all_references)),
            format_func=lambda i: f"{all_references[i]['title']} | {all_references[i]['field']} | {all_references[i]['match_score']}%",
        )
        reference_selected = all_references[index]
        if st.button("Explain my role fit with AI"):
            try:
                with session_scope() as session:
                    result = ai.explain_career_match(
                        session,
                        ctx,
                        reference_selected,
                        match_score=reference_selected["match_score"],
                        matched_skills=reference_selected["matched_skills"],
                        missing_skills=reference_selected["missing_skills"],
                    )
                st.write(result.fit_summary)
                st.caption(f"Confidence: {result.confidence:.0%} | {result.notice}")
                render_bullets(result.evidence_used)
            except RateLimitExceeded:
                st.warning("Please wait a minute and try again.")
    target = live_selected or reference_selected
    if st.button("Add target role & gaps to my learning goals", icon=":material/add:"):
        with session_scope() as session:
            repo = TwinRepository(session)
            current = repo.get_twin(ctx)
            current["profile"]["career_goals"] = [target["title"]]
            current = confirm_learning_choices(
                current,
                [],
                [
                    {"name": skill, "kind": "skill"}
                    for skill in target["missing_skills"]
                ],
            )
            repo.save_twin(ctx, current, label="market_target_selected")
        st.rerun()
    return target
