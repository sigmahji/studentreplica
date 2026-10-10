"""Streamlit views for personal career direction, roadmaps, and check-ins."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from ai.service import AIService, RateLimitExceeded
from modules.career_planner import (
    confirm_learning_choices,
    progress_summary,
    record_task_completion,
)
from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository
from modules.ui import render_bullets

_logger = logging.getLogger("student_twin.ui")


def analyze_student(ctx: UserContext, ai: AIService) -> dict[str, Any] | None:
    """Run an analysis with a recoverable, personal-data-free UI error."""
    try:
        with st.spinner(
            "Reviewing your progress, career direction, and local opportunities..."
        ):
            with session_scope() as session:
                return ai.generate_student_career_plan(session, ctx)
    except RateLimitExceeded:
        st.warning(
            "You have reached the AI request limit. Please try again in a minute."
        )
    except Exception as exc:
        _logger.warning(
            "event=planning_unavailable user_id=%s err=%s",
            ctx.user_id,
            type(exc).__name__,
        )
        st.warning(
            "Your details are saved. Career planning is temporarily unavailable; please try again."
        )
    return None


def render_career_plan(ctx: UserContext, ai: AIService) -> None:
    """Render only this user's saved analysis and progress."""
    st.markdown("### My Career Plan")
    with session_scope() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx)
        artifacts = repo.list_artifacts(ctx, kind="career_plan")
    if not twin:
        st.info(
            "Add your study details, interests, location, and availability in Profile."
        )
        return
    payload = artifacts[0]["payload"] if artifacts else None
    if st.button("Analyze / refresh career plan", type="primary"):
        updated = analyze_student(ctx, ai)
        if updated:
            payload = updated
    if payload:
        _render_analysis(ctx, twin, payload, ai)
    else:
        st.info("Your first career assessment is ready to generate.")
    if twin.get("active_plan"):
        _render_progress(ctx, twin)
    _render_coach(ctx, ai)


def _render_analysis(
    ctx: UserContext,
    twin: dict[str, Any],
    payload: dict[str, Any],
    ai: AIService,
) -> None:
    analysis = payload["analysis"]
    market = payload["market"]
    if payload.get("offline_mode"):
        st.warning("Offline example plan. Live AI analysis is currently unavailable.")
    st.caption(f"Created {payload['created_at'][:16]} | {analysis['notice']}")
    left, middle, right = st.columns(3)
    left.metric("Direction", analysis["assessment"].replace("_", " ").title())
    middle.metric("Confidence", f"{analysis['confidence']:.0%}")
    right.metric("Available per week", f"{payload['weekly_minutes'] / 60:g} hours")
    st.write(analysis["assessment_reason"])
    st.markdown("#### Your market")
    st.caption(
        f"{market['location'] or 'Location not provided'} | Research date: {market['retrieved_at'][:10]}"
    )
    if market["mode"] != "live_web":
        st.info(market["notice"])
    else:
        st.caption(market["notice"])
    st.write(analysis["market_summary"])
    sources = {source["id"]: source for source in market["sources"]}
    for direction in analysis["career_directions"]:
        st.markdown(f"#### {direction['role']}")
        st.write(direction["fit_reason"])
        if direction["skill_gaps"]:
            st.write("Skills to develop:", ", ".join(direction["skill_gaps"]))
        st.write(direction["next_step"])
        for source_id in direction.get("source_ids", []):
            if source_id in sources:
                source = sources[source_id]
                st.link_button(source["title"], source["url"])
    if sources:
        with st.expander("Market sources"):
            for source in sources.values():
                st.link_button(source["title"], source["url"])
                st.caption(
                    f"Published: {source.get('published_date') or 'Not supplied'}"
                )
                st.write(source["snippet"])
    with st.expander("Why this?"):
        render_bullets(analysis["evidence_used"])
        st.write(f"Based on twin version {payload['twin_version']}.")
    st.markdown("#### Internship preparation")
    st.write(analysis["internship_strategy"])
    st.markdown("#### Before graduation")
    st.write(analysis["graduation_strategy"])
    st.markdown("#### Progress review")
    st.write(analysis["progress_summary"])

    roles = [direction["role"] for direction in analysis["career_directions"]]
    chosen = st.selectbox(
        "Career direction to pursue", roles, key=f"direction_{payload['plan_id']}"
    )
    if st.button("Focus my plan on this direction"):
        with session_scope() as session:
            repo = TwinRepository(session)
            current = repo.get_twin(ctx)
            current["profile"]["career_goals"] = [chosen]
            repo.save_twin(ctx, current, label="career_direction_selected")
        analyze_student(ctx, ai)
        st.rerun()
    _render_choices(ctx, payload, twin)
    _render_roadmap(ctx, twin, payload)


def _render_choices(
    ctx: UserContext, payload: dict[str, Any], twin: dict[str, Any]
) -> None:
    from modules.academics import learning_options

    analysis = payload["analysis"]
    earned_options = list(analysis["earned_options"])
    targets = list(analysis["target_options"])
    catalog = learning_options(twin)
    earned_names = {o["name"].casefold() for o in earned_options}
    earned_options += [o for o in catalog if o["name"].casefold() not in earned_names]
    names = {o["name"].casefold() for o in targets}
    targets += [o for o in catalog if o["name"].casefold() not in names]
    recommended = {o["name"].casefold() for o in analysis["target_options"][:3]}
    if not earned_options and not targets:
        return
    st.markdown("#### Achievements & learning goals")
    for item in analysis["target_options"][:3]:
        st.info(f"AI recommends {item['name']}: {item['rationale']}")
    wanted = st.multiselect(
        "I want to earn / learn",
        range(len(targets)),
        format_func=lambda i: f"{'Recommended | ' if targets[i]['name'].casefold() in recommended else ''}{targets[i]['kind'].title()}: {targets[i]['name']}",
        key=f"wanted_{payload['plan_id']}",
    )
    for index in wanted:
        option = next(
            (
                o
                for o in catalog
                if o["name"].casefold() == targets[index]["name"].casefold()
            ),
            {},
        )
        if option.get("foundations_first"):
            st.warning(
                f"Before {targets[index]['name']}, strengthen: {', '.join(option['foundations_first'])}. These foundations will be included in your learning goals."
            )
    with st.form(f"learning_choices_{payload['plan_id']}"):
        earned = st.multiselect(
            "I have earned / completed",
            range(len(earned_options)),
            format_func=lambda i: f"{earned_options[i]['kind'].title()}: {earned_options[i]['name']}",
        )
        with st.expander("Reasons for these options"):
            for item in earned_options + targets:
                st.write(f"{item['name']}: {item['rationale']}")
        submitted = st.form_submit_button("Save my choices")
    if submitted:
        with session_scope() as session:
            repo = TwinRepository(session)
            current = repo.get_twin(ctx)
            current = confirm_learning_choices(
                current,
                [earned_options[i] for i in earned],
                [targets[i] for i in wanted],
            )
            selected_names = {targets[i]["name"].casefold() for i in wanted}
            foundations = list(
                dict.fromkeys(
                    p
                    for o in catalog
                    if o["name"].casefold() in selected_names
                    for p in o["foundations_first"]
                )
            )
            current = confirm_learning_choices(
                current, [], [{"name": p, "kind": "skill"} for p in foundations]
            )
            repo.save_twin(ctx, current, label="learning_choices_confirmed")
        st.rerun()


def _render_roadmap(
    ctx: UserContext, twin: dict[str, Any], payload: dict[str, Any]
) -> None:
    st.markdown("#### Proposed roadmap")
    for week in payload["analysis"]["weeks"]:
        with st.expander(f"Week {week['week']}: {week['focus']}"):
            for task in week["tasks"]:
                st.write(f"**{task['title']}** | {task['minutes']} min")
                st.write(f"Completion evidence: {task['evidence_required']}")
                st.caption(task["resource"])
    if payload["schedule"]:
        st.dataframe(payload["schedule"], hide_index=True, use_container_width=True)
    else:
        st.info(
            "No free study slots are available. Update availability in Profile when you have time."
        )
    if payload["deferred_tasks"]:
        st.warning(
            "Some work does not fit your available time or graduation deadline. Your commitments have been preserved."
        )
        st.dataframe(
            payload["deferred_tasks"], hide_index=True, use_container_width=True
        )
    active_id = twin.get("active_plan", {}).get("plan_id")
    stale = payload["twin_version"] != twin.get("meta", {}).get("twin_version")
    if active_id != payload["plan_id"]:
        if stale:
            st.info(
                "Your profile or progress has changed. Refresh the career plan before starting this roadmap."
            )
        if st.button("Use this roadmap", disabled=stale or not payload["schedule"]):
            with session_scope() as session:
                repo = TwinRepository(session)
                current = repo.get_twin(ctx)
                current["active_plan"] = {
                    key: payload[key]
                    for key in (
                        "plan_id",
                        "created_at",
                        "twin_version",
                        "tasks",
                        "schedule",
                        "deferred_tasks",
                    )
                }
                repo.save_twin(ctx, current, label="roadmap_started")
            st.rerun()


def _render_progress(ctx: UserContext, twin: dict[str, Any]) -> None:
    st.markdown("#### My active roadmap")
    plan = twin["active_plan"]
    summary = progress_summary(twin)
    st.progress(summary["completion_percent"] / 100)
    st.write(
        f"{summary['completed_tasks']} of {summary['total_tasks']} tasks completed"
    )
    if plan["schedule"]:
        st.dataframe(plan["schedule"], hide_index=True, use_container_width=True)
    completed = {
        e["task_id"]
        for e in twin.get("progress_events", [])
        if e.get("plan_id") == plan["plan_id"]
    }
    pending = [task for task in plan["tasks"] if task["task_id"] not in completed]
    if pending:
        with st.form(f"progress_{plan['plan_id']}"):
            index = st.selectbox(
                "Completed task",
                range(len(pending)),
                format_func=lambda i: pending[i]["title"],
            )
            evidence = st.text_area("Completion note / evidence link", max_chars=2000)
            submitted = st.form_submit_button("Record completion")
        if submitted:
            try:
                with session_scope() as session:
                    repo = TwinRepository(session)
                    current = record_task_completion(
                        repo.get_twin(ctx), pending[index]["task_id"], evidence
                    )
                    repo.save_twin(ctx, current, label="learning_milestone_completed")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    else:
        st.success(
            "Your current roadmap is complete. Refresh your career plan for the next cycle."
        )
    if twin.get("progress_events"):
        with st.expander("Completed milestones"):
            st.dataframe(
                twin["progress_events"], hide_index=True, use_container_width=True
            )


def _render_coach(ctx: UserContext, ai: AIService) -> None:
    with st.expander("Ask my academic & career coach"):
        with session_scope() as session:
            history = TwinRepository(session).get_chat_history(ctx, limit=12)
        for message in history:
            with st.chat_message(message["role"]):
                st.write(message["content"])
        with st.form("career_coach"):
            message = st.text_input("My question", max_chars=2000)
            submitted = st.form_submit_button("Ask coach")
        if submitted and message.strip():
            try:
                with st.spinner("Reviewing your twin and recent progress..."):
                    with session_scope() as session:
                        reply = ai.coach_chat(session, ctx, message.strip())
                st.write(reply.reply)
                st.caption(f"Confidence: {reply.confidence:.0%} | {reply.notice}")
                with st.expander("Why this reply?"):
                    render_bullets(reply.evidence_used)
            except RateLimitExceeded:
                st.warning("Please wait a minute before asking another question.")
            except Exception as exc:
                _logger.warning(
                    "event=coach_unavailable user_id=%s err=%s",
                    ctx.user_id,
                    type(exc).__name__,
                )
                st.warning("Your coach is temporarily unavailable. Please try again.")
