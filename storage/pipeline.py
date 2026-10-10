"""Student pipeline with strict user isolation.

Phase 2+: AI calls go through ``ai.service.AIService`` (MockClient in tests).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ai.client import MockClient
from ai.service import AIService
from modules.market_matcher import calculate_match, get_local_job_catalog
from storage.context import UserContext
from storage.logging_utils import log_event
from storage.repository import TwinRepository
from storage.twin_schema import legacy_profile_to_twin, skill_names


def update_twin_from_profile(
    session: Session,
    ctx: UserContext,
    profile: dict[str, Any],
    *,
    label: str = "profile_update",
) -> dict[str, Any]:
    """Convert a legacy/demo profile dict into a stored twin for this user."""
    repo = TwinRepository(session)
    twin = legacy_profile_to_twin(profile)
    saved = repo.save_twin(ctx, twin, label=label)
    log_event(ctx.user_id, "pipeline_twin_updated")
    return saved


def run_matching(session: Session, ctx: UserContext) -> list[dict[str, Any]]:
    """Match this user's twin skills against the local job catalog."""
    repo = TwinRepository(session)
    twin = repo.get_or_create_twin(ctx)
    skills = skill_names(twin)
    results: list[dict[str, Any]] = []
    for job in get_local_job_catalog():
        match = calculate_match(skills, job["required_skills"])
        results.append({"job": job, "match": match})
    results.sort(key=lambda r: r["match"]["match_score"], reverse=True)
    repo.save_artifact(ctx, "match_results", {"results": results})
    log_event(ctx.user_id, "pipeline_matching_done", count=len(results))
    return results


def run_full_pipeline(
    session: Session,
    ctx: UserContext,
    profile: dict[str, Any],
    ai: AIService,
) -> dict[str, Any]:
    """Run twin update → matching → CV → insight → chat for one user."""
    twin = update_twin_from_profile(session, ctx, profile)
    matches = run_matching(session, ctx)
    top = matches[0] if matches else None

    cv = None
    if top:
        cv = ai.generate_cv_content(session, ctx, top["job"])

    insight = ai.generate_twin_insights(session, ctx)
    chat = ai.coach_chat(
        session,
        ctx,
        "Help me improve for roles related to my goals.",
    )

    explanation = None
    roadmap = None
    if top:
        explanation = ai.explain_career_match(
            session,
            ctx,
            top["job"],
            match_score=top["match"]["match_score"],
            matched_skills=top["match"]["matched_skills"],
            missing_skills=top["match"]["missing_skills"],
        )
        roadmap = ai.build_learning_roadmap(
            session,
            ctx,
            top["job"]["title"],
            missing_skills=top["match"]["missing_skills"],
        )

    what_if = ai.simulate_what_if(
        session, ctx, "What if I learn Docker for 4 weeks?"
    )

    return {
        "twin": twin,
        "matches": matches,
        "cv": cv.model_dump(mode="json") if cv else None,
        "insight": insight.model_dump(mode="json"),
        "chat": chat.model_dump(mode="json"),
        "explanation": (
            explanation.model_dump(mode="json") if explanation else None
        ),
        "roadmap": roadmap.model_dump(mode="json") if roadmap else None,
        "what_if": what_if.model_dump(mode="json"),
    }


def mock_ai_service() -> AIService:
    """Convenience: AIService backed by MockClient for tests/offline."""
    client = MockClient()
    return AIService(client=client, offline_mode=True)
