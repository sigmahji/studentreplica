"""Interactive student progress and readable, evidence-grounded twin insights."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

import plotly.graph_objects as go
import streamlit as st

from ai.service import AIService, RateLimitExceeded
from modules.career_planner import progress_summary
from modules.digital_twin import (
    compute_academic_stats,
    progress_timeline,
    skill_radar_points,
)
from modules.ui import current_colors, insight_group, render_bullets
from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository


def progress_points(
    snapshots: list[dict[str, Any]], days: int | None = None
) -> list[dict[str, Any]]:
    """Use real snapshot totals only; missing academic scores remain missing."""
    points = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    for point in progress_timeline(snapshots):
        if not point.get("created_at"):
            continue
        created = datetime.fromisoformat(point["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if cutoff is None or created >= cutoff:
            points.append({**point, "date": created})
    return sorted(points, key=lambda point: (point["date"], point["version"]))


def progress_figure(
    points: list[dict[str, Any]], metric: str, colors: dict[str, str]
) -> go.Figure:
    """Build a hoverable chart whose values retain their original units."""
    key, label, color = {
        "Milestones": (
            "completed_milestones",
            "Completed milestones",
            colors["accent"],
        ),
        "Skills": ("skill_count", "Skills tracked", colors["blue"]),
        "Academic average": (
            "average_score",
            "Academic average / 100",
            colors["coral"],
        ),
    }[metric]
    available = [point for point in points if point[key] is not None]
    fig = go.Figure(
        go.Scatter(
            x=[p["date"] for p in available],
            y=[p[key] for p in available],
            mode="lines+markers",
            line={"color": color, "width": 3, "shape": "hv"},
            marker={"size": 8, "color": color},
            customdata=[
                [p["version"], p["label"].replace("_", " ")] for p in available
            ],
            hovertemplate="%{x|%d %b, %H:%M}<br>"
            + label
            + ": %{y}<br>Snapshot v%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            name=label,
        )
    )
    fig.update_layout(
        height=300,
        margin={"l": 12, "r": 16, "t": 18, "b": 20},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": colors["text"], "family": "Arial, sans-serif", "size": 12},
        transition={"duration": 250},
        showlegend=False,
        hoverlabel={"bgcolor": colors["surface"], "font_color": colors["text"]},
        xaxis={"showgrid": False, "title": None},
        yaxis={
            "title": label,
            "gridcolor": colors["border"],
            "rangemode": "tozero",
            "dtick": 1 if metric != "Academic average" else None,
        },
    )
    if len(available) == 1:
        center = available[0]["date"]
        fig.update_xaxes(range=[center - timedelta(days=1), center + timedelta(days=1)])
    if metric == "Academic average":
        fig.update_yaxes(range=[0, 100])
    return fig


def render_progress_chart(snapshots: list[dict[str, Any]], *, key: str) -> None:
    """Filter the timeline without an AI call or changing student records."""
    controls, period = st.columns([3, 1])
    metric = controls.radio(
        "Progress measure",
        ["Milestones", "Skills", "Academic average"],
        horizontal=True,
        key=f"{key}_metric",
    )
    window = period.selectbox(
        "Period", ["All time", "Last 30 days", "Last 90 days"], key=f"{key}_period"
    )
    points = progress_points(
        snapshots, {"All time": None, "Last 30 days": 30, "Last 90 days": 90}[window]
    )
    if (
        not points
        or metric == "Academic average"
        and all(p["average_score"] is None for p in points)
    ):
        st.info("No recorded data for this selection yet.")
        return
    st.plotly_chart(
        progress_figure(points, metric, current_colors()),
        use_container_width=True,
        config={"displayModeBar": False},
        key=f"{key}_chart",
    )


def _render_radar(twin: dict[str, Any]) -> None:
    points = skill_radar_points(twin)
    if not points:
        st.info("Your skills and graded subjects will appear here.")
        return
    colors = current_colors()
    labels = [p["label"] for p in points]
    # Keep long subject names within the radar's stable plotting area.
    display = [label if len(label) <= 19 else label[:17] + "..." for label in labels]
    values = [p["value"] for p in points]
    fig = go.Figure(
        go.Scatterpolar(
            r=values + values[:1],
            theta=display + display[:1],
            customdata=labels + labels[:1],
            fill="toself",
            line={"color": colors["accent"], "width": 2},
            fillcolor="rgba(38,160,137,0.16)",
            hovertemplate="%{customdata}: %{r}/100<extra></extra>",
        )
    )
    fig.update_layout(
        height=350,
        margin={"l": 85, "r": 85, "t": 40, "b": 40},
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        font={"color": colors["text"], "size": 11},
        polar={
            "bgcolor": "rgba(0,0,0,0)",
            "radialaxis": {
                "range": [0, 100],
                "gridcolor": colors["border"],
                "tickfont": {"size": 9},
            },
            "angularaxis": {"gridcolor": colors["border"]},
        },
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
        key="dashboard_radar",
    )


def _render_insights(insight: dict[str, Any]) -> None:
    st.caption(
        f"Confidence: {insight.get('confidence', 0):.0%} | {insight.get('notice', '')}"
    )
    if insight.get("academic_summary"):
        st.write(insight["academic_summary"])
    columns = st.columns(3)
    for column, title, field, tone in zip(
        columns,
        ["Strengths", "Focus areas", "Risks to watch"],
        ["strengths", "weaknesses", "risks"],
        ["positive", "attention", "risk"],
    ):
        with column:
            insight_group(title, insight.get(field, []), tone)
    st.markdown("#### Next best actions")
    for action in insight.get("next_actions", []):
        st.markdown(f"**{action['priority']}. {action['action']}**")
        st.write(action["rationale"])
    if insight.get("subject_insights"):
        with st.expander("Subject-by-subject review"):
            for subject in insight["subject_insights"]:
                st.markdown(
                    f"**{subject['subject']}** | {subject.get('grade') or 'In progress'}"
                )
                st.write(subject.get("assessment", ""))
                st.caption(subject.get("recommendation", ""))
    with st.expander("Why this?"):
        render_bullets(insight.get("evidence_used", []))
        if insight.get("study_level_fit"):
            st.write(insight["study_level_fit"])


def render_dashboard(ctx: UserContext, ai: AIService) -> None:
    """Load only the current student's progress, grades, and saved AI report."""
    with session_scope() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx)
        snapshots = repo.list_snapshots(ctx)
        artifacts = repo.list_artifacts(ctx, kind="twin_insight")
    st.markdown("### Your learning, in perspective")
    if not twin:
        st.info("Your workspace is ready. Add your study details in Profile to begin.")
        return
    profile = twin["profile"]
    st.caption(
        f"{profile.get('name') or 'Student'} | {profile.get('degree') or 'Program not added'} | {profile.get('institution') or 'Institution not added'}"
    )
    stats = compute_academic_stats(twin)
    summary = progress_summary(twin)
    metrics = st.columns(4)
    metrics[0].metric("Completed milestones", summary["total_recorded_milestones"])
    metrics[1].metric("Skills tracked", len(twin.get("skills", [])))
    metrics[2].metric(
        "Academic average",
        (
            f"{stats['average_score']:g}/100"
            if stats["average_score"] is not None
            else "Not graded"
        ),
    )
    metrics[3].metric(
        "Courses passed",
        sum(c.get("status") == "passed" for c in twin.get("learning_courses", [])),
    )
    st.markdown("#### Progress over time")
    render_progress_chart(snapshots, key="dashboard_progress")
    skills, activity = st.columns([3, 2])
    with skills:
        st.markdown("#### Skill & subject balance")
        _render_radar(twin)
    with activity:
        st.markdown("#### Recent activity")
        events = twin.get("progress_events", [])
        if not events:
            st.caption("No completed milestones yet.")
        for event in reversed(events[-5:]):
            st.markdown(
                f'<div class="activity-item"><strong>{escape(str(event.get("title", "Learning milestone")))}</strong>'
                f'<small>{escape(str(event.get("completed_on", "")))} | {escape(str(event.get("verification", "student reported")).replace("_", " "))}</small></div>',
                unsafe_allow_html=True,
            )
        if summary["total_tasks"]:
            st.markdown("**Active roadmap**")
            st.progress(
                summary["completion_percent"] / 100,
                text=f"{summary['completed_tasks']} of {summary['total_tasks']} tasks completed",
            )
        if stats["at_risk"]:
            st.markdown("**Academic priorities**")
            render_bullets(
                [
                    f"{item['subject']} - {item['score']:g}/100"
                    for item in stats["at_risk"]
                ]
            )
    st.divider()
    st.markdown("### Twin insight report")
    insight = artifacts[0]["payload"] if artifacts else None
    if st.button(
        "Generate Twin Insights", type="primary", icon=":material/auto_awesome:"
    ):
        try:
            with st.spinner("Reviewing your skills, grades and recent work..."):
                with session_scope() as session:
                    insight = ai.generate_twin_insights(session, ctx).model_dump(
                        mode="json"
                    )
        except RateLimitExceeded:
            st.warning("Please wait a minute before another AI analysis.")
    if insight:
        _render_insights(insight)
    else:
        st.info("No insight report yet.")
