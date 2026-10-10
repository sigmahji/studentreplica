"""High-level AI operations used by digital_twin, marketmatcher, cvgenerator."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ai.client import LLMClient, MockClient, create_llm_client
from ai import prompts
from ai.schemas import (
    CVContent,
    CareerMatchExplanation,
    CoachReply,
    SkillGapRoadmap,
    TwinInsight,
    WhatIfSimulation,
    StudentCareerPlan,
    CourseAssessment,
    MarketAnalysis,
    CVSelection,
)
from config import (
    AI_RATE_LIMIT_PER_MINUTE,
    MAX_CHAT_HISTORY,
    MAX_PROMPT_CHARS,
)
from storage.context import UserContext
from storage.logging_utils import log_event
from storage.repository import TwinRepository

_logger = logging.getLogger("student_twin.ai")
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class _Completion(Generic[T]):
    """Keep result provenance local to one request, not the shared service."""

    result: T
    provider: str
    offline_mode: bool
    notice: str | None = None


class RateLimitExceeded(RuntimeError):
    """Raised when a user exceeds the per-minute AI call budget."""


class AIService:
    """User-scoped AI facade: cache, rate-limit, validate, repair-once."""

    def __init__(
        self,
        client: LLMClient | None = None,
        *,
        offline_mode: bool | None = None,
    ) -> None:
        self.client = client or create_llm_client()
        self.offline_mode = (
            bool(self.client.is_mock) if offline_mode is None else offline_mode
        )
        # Per-user timestamps of recent calls (not student payloads)
        self._rate_windows: dict[str, deque[float]] = defaultdict(deque)

    # ----------------------------------------------------------------- helpers
    def _check_rate_limit(self, ctx: UserContext) -> None:
        now = time.time()
        window = self._rate_windows[ctx.user_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= AI_RATE_LIMIT_PER_MINUTE:
            log_event(ctx.user_id, "ai_rate_limited")
            raise RateLimitExceeded(
                f"Rate limit ({AI_RATE_LIMIT_PER_MINUTE}/min) exceeded"
            )
        window.append(now)

    def _cache_key(
        self,
        ctx: UserContext,
        task: str,
        twin_version: int,
        prompt: str,
        *,
        client: LLMClient | None = None,
    ) -> str:
        provider = client or self.client
        digest = hashlib.sha256(
            (
                provider.provider_name + "\n" + provider.model_name + "\n" + prompt
            ).encode("utf-8")
        ).hexdigest()[:24]
        return f"{ctx.user_id}:{task}:v{twin_version}:{digest}"

    def _trim(self, text: str) -> str:
        if len(text) <= MAX_PROMPT_CHARS:
            return text
        return text[: MAX_PROMPT_CHARS - 20] + "\n…[truncated]"

    def _parse_json(self, raw: str) -> dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        return json.loads(text)

    def _validate(self, task: str, raw: str, schema: type[T]) -> T:
        data = self._parse_json(raw)
        return schema.model_validate(data)

    def _completion(
        self,
        result: T,
        client: LLMClient,
        *,
        fallback: bool = False,
        failure_reason: str | None = None,
    ) -> _Completion[T]:
        offline = self.offline_mode or client.is_mock
        notice = None
        if offline:
            notice = (
                f"{failure_reason or 'Temporary AI failure:'} "
                "This response is an offline example. "
                "Live AI will retry automatically on the next request."
                if fallback
                else "Offline example response; not a live AI assessment."
            )
            updates: dict[str, Any] = {}
            if "notice" in type(result).model_fields:
                updates["notice"] = notice
            if "confidence" in type(result).model_fields:
                updates["confidence"] = min(result.confidence, 0.5)
            result = result.model_copy(update=updates)
        return _Completion(result, client.provider_name, offline, notice)

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        """Describe provider failures using status codes, never raw error payloads."""
        return {
            401: "The AI provider rejected the configured API key.",
            403: "The AI provider denied access to this model.",
            413: "The AI request exceeded the provider's token limit.",
            429: "The AI provider's rate limit was reached; wait for its quota to reset.",
        }.get(getattr(error, "status_code", None), "Temporary AI failure:")

    def _complete_validated(
        self,
        session: Session,
        ctx: UserContext,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        twin_version: int,
        use_cache: bool = True,
        max_tokens: int = 2048,
    ) -> _Completion[T]:
        """Run LLM → JSON parse → Pydantic validate; repair once on failure."""
        system = self._trim(system)
        user = self._trim(user)
        repo = TwinRepository(session)
        key = self._cache_key(ctx, task, twin_version, system + "\n" + user)

        if use_cache:
            cached = repo.get_ai_cache(ctx, key)
            if cached is not None:
                log_event(ctx.user_id, "ai_cache_hit", task=task)
                return self._completion(schema.model_validate(cached), self.client)

        self._check_rate_limit(ctx)
        request_client = self.client
        fallback = False
        failure_reason = None
        log_event(ctx.user_id, "ai_request", task=task)
        try:
            raw = request_client.complete_with_retry(
                system=system, user=user, user_id=ctx.user_id, max_tokens=max_tokens
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "event=ai_provider_error user_id=%s err=%s http_status=%s",
                ctx.user_id,
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            if not request_client.is_mock:
                request_client = MockClient(record_prompts=False)
                fallback = True
                failure_reason = self._failure_reason(exc)
                log_event(ctx.user_id, "ai_fallback_mock")
                raw = request_client.complete(
                    system=system, user=user, user_id=ctx.user_id, max_tokens=max_tokens
                )
            else:
                raise

        try:
            result = self._validate(task, raw, schema)
        except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as err:
            log_event(ctx.user_id, "ai_validation_retry", task=task)
            repair_system, repair_user = prompts.repair_messages(
                task, raw, str(err), schema.model_json_schema()
            )
            try:
                raw2 = request_client.complete_with_retry(
                    system=repair_system,
                    user=repair_user,
                    user_id=ctx.user_id,
                    max_tokens=max_tokens,
                )
                result = self._validate(task, raw2, schema)
            except Exception as exc:
                log_event(ctx.user_id, "ai_validation_fallback", task=task)
                request_client = MockClient(record_prompts=False)
                fallback = True
                failure_reason = (
                    self._failure_reason(exc)
                    if getattr(exc, "status_code", None)
                    else "The AI response could not be validated."
                )
                result = self._validate(
                    task,
                    request_client.complete(
                        system=system,
                        user=user,
                        user_id=ctx.user_id,
                        max_tokens=max_tokens,
                    ),
                    schema,
                )

        completion = self._completion(
            result, request_client, fallback=fallback, failure_reason=failure_reason
        )
        if use_cache:
            # An offline response must never satisfy a later live-provider request.
            key = self._cache_key(
                ctx, task, twin_version, system + "\n" + user, client=request_client
            )
            repo.set_ai_cache(ctx, key, completion.result.model_dump(mode="json"))
        return completion

    def _load_twin(self, session: Session, ctx: UserContext) -> dict[str, Any]:
        twin = TwinRepository(session).get_twin(ctx)
        if twin is None:
            raise ValueError(f"No twin found for user_id={ctx.user_id}")
        return twin

    # ----------------------------------------------------------- public API
    def generate_student_career_plan(
        self,
        session: Session,
        ctx: UserContext,
    ) -> dict[str, Any]:
        """Analyze one student, research their market, and constrain a dated plan."""
        from modules.career_planner import (
            rank_career_references,
            schedule_career_plan,
            student_planning_context,
        )
        from modules.market_research import research_local_market

        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        context = student_planning_context(twin)
        # Raw identifying profile details are never sent to the search provider.
        profile = twin.get("profile", {})
        search_profile = {
            key: profile.get(key, "")
            for key in (
                "city",
                "country",
                "university_city",
                "degree",
                "field_of_study",
                "work_preference",
                "career_goals",
                "interests",
            )
        }
        search_profile["skills"] = [
            s["name"]
            for s in twin.get("skills", [])
            if isinstance(s, dict) and s.get("name")
        ][:5]
        version = repo.get_twin_version(ctx)
        market_key = self._cache_key(
            ctx,
            "market",
            version,
            json.dumps(search_profile, sort_keys=True) + date.today().isoformat(),
        )
        market = repo.get_ai_cache(ctx, market_key)
        if market is None:
            market = research_local_market(
                ctx, search_profile, allow_groq=not self.client.is_mock
            )
            if market["mode"] == "live_web":
                repo.set_ai_cache(ctx, market_key, market)
        system, user = prompts.student_career_plan_messages(
            context, market, rank_career_references(twin)
        )
        completion = self._complete_validated(
            session,
            ctx,
            task="student_career_plan",
            system=system,
            user=user,
            schema=StudentCareerPlan,
            twin_version=version,
            max_tokens=6144,
        )
        plan = completion.result
        valid_source_ids = {s["id"] for s in market["sources"]}
        if market["mode"] != "live_web":
            plan.confidence = min(plan.confidence, 0.5)
        for direction in plan.career_directions:
            direction.source_ids = [
                s for s in direction.source_ids if s in valid_source_ids
            ]
        from modules.academics import prioritize_academic_work

        plan = prioritize_academic_work(plan, twin)
        payload = {
            "plan_id": str(uuid4()),
            "twin_version": version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "offline_mode": completion.offline_mode,
            "provider": completion.provider,
            "analysis": plan.model_dump(mode="json"),
            "market": market,
            **schedule_career_plan(
                plan,
                twin.get("learning_preferences", {}),
                graduation_date=profile.get("graduation_date", ""),
            ),
        }
        repo.save_artifact(ctx, "career_plan", payload, prompt_text=user)
        return payload

    def generate_course_assessment(
        self, session: Session, ctx: UserContext, course_id: str, completion_note: str
    ) -> dict[str, Any]:
        """Create a private quiz for this user's selected course and save its key."""
        from modules.career_planner import student_planning_context

        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        course = next(
            (c for c in twin.get("learning_courses", []) if c["id"] == course_id), None
        )
        if course is None or course.get("status") == "passed":
            raise ValueError("Choose an unfinished course from your learning list.")
        if not completion_note.strip() or len(completion_note) > 2000:
            raise ValueError(
                "Add a short note on the course units you completed (up to 2,000 characters)."
            )
        course["completion_note"] = completion_note.strip()
        context = student_planning_context(twin)
        system, user = prompts.course_assessment_messages(context, course)
        completion = self._complete_validated(
            session,
            ctx,
            task="course_assessment",
            system=system,
            user=user,
            schema=CourseAssessment,
            twin_version=repo.get_twin_version(ctx),
            use_cache=False,
            max_tokens=4096,
        )
        quiz = completion.result
        quiz.skill = course["skill"]
        payload = {
            "course_id": course_id,
            "quiz": quiz.model_dump(mode="json"),
            "offline_mode": completion.offline_mode,
            "provider": completion.provider,
        }
        identifier = repo.save_artifact(
            ctx, "course_assessment", payload, prompt_text=user
        )
        course["assessment_id"] = identifier
        course["status"] = "quiz_ready"
        repo.save_twin(ctx, twin, label="course_completion_reported")
        return {"id": identifier, **payload}

    def submit_course_assessment(
        self, session: Session, ctx: UserContext, assessment_id: int, answers: list[int]
    ) -> dict[str, Any]:
        """Load the answer key by user_id and compute the score in Python."""
        from modules.learning import grade_assessment

        repo = TwinRepository(session)
        own = next(
            (
                a
                for a in repo.list_artifacts(ctx, kind="course_assessment")
                if a["id"] == assessment_id
            ),
            None,
        )
        if own is None:
            raise ValueError("Assessment not found for your account.")
        payload = own["payload"]
        twin, feedback = grade_assessment(
            self._load_twin(session, ctx),
            payload["course_id"],
            assessment_id,
            CourseAssessment.model_validate(payload["quiz"]),
            answers,
            offline=payload["offline_mode"],
        )
        repo.save_twin(
            ctx,
            twin,
            label=(
                "assessment_passed"
                if feedback["passed"]
                else "assessment_review_needed"
            ),
        )
        repo.save_artifact(ctx, "assessment_result", feedback)
        return feedback

    def analyze_live_market(self, session: Session, ctx: UserContext) -> dict[str, Any]:
        """Retrieve fresh sources, extract supported openings, then score in Python."""
        from modules.career_planner import student_planning_context
        from modules.market_research import research_local_market, validate_openings
        from modules.market_matcher import rank_jobs

        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        profile = twin["profile"]
        search = {
            k: profile.get(k, "")
            for k in (
                "degree",
                "field_of_study",
                "city",
                "university_city",
                "country",
                "interests",
                "career_goals",
                "work_preference",
            )
        }
        search["skills"] = [
            s["name"]
            for s in twin.get("skills", [])
            if isinstance(s, dict) and s.get("name")
        ][:5]
        self._check_rate_limit(ctx)
        key = self._cache_key(
            ctx,
            "market",
            repo.get_twin_version(ctx),
            json.dumps(search, sort_keys=True) + date.today().isoformat(),
        )
        market = repo.get_ai_cache(ctx, key)
        if not market:
            market = research_local_market(
                ctx, search, allow_groq=not self.client.is_mock
            )
            if market["mode"] == "live_web":
                repo.set_ai_cache(ctx, key, market)
        context = student_planning_context(twin)
        context.pop("learning_catalog", None)
        context.pop("active_schedule", None)
        system, user = prompts.market_analysis_messages(context, market)
        completion = self._complete_validated(
            session,
            ctx,
            task="market_analysis",
            system=system,
            user=user,
            schema=MarketAnalysis,
            twin_version=repo.get_twin_version(ctx),
            max_tokens=3000,
        )
        analysis = completion.result
        openings = analysis.model_dump(mode="json")["openings"]
        source_by_id = {s["id"]: s for s in market["sources"]}
        for opening in openings:
            source = source_by_id.get(opening["source_id"])
            opening["evidence_quote"] = source["snippet"][:400] if source else ""
        jobs = validate_openings(openings, market["sources"])
        by_url = {job["url"]: job for job in jobs}
        for listing in market.get("feed_openings", []):
            if listing["url"] not in by_url:
                jobs.append(listing)
            else:
                by_url[listing["url"]].update(
                    publisher=listing["publisher"],
                    experience_level=listing["experience_level"],
                )
        analysis.source_ids = [
            s
            for s in analysis.source_ids
            if s in {src["id"] for src in market["sources"]}
        ]
        if market["mode"] != "live_web":
            analysis.confidence = min(analysis.confidence, 0.4)
        payload = {
            "market": market,
            "analysis": analysis.model_dump(mode="json"),
            "jobs": rank_jobs(twin, jobs),
            "offline_mode": completion.offline_mode,
            "provider": completion.provider,
            "twin_version": repo.get_twin_version(ctx),
        }
        repo.save_artifact(ctx, "live_market", payload, prompt_text=user)
        return payload

    def generate_twin_insights(self, session: Session, ctx: UserContext) -> TwinInsight:
        """Strengths, gaps, risks, academic analysis, and 3 next actions."""
        from modules.digital_twin import compute_academic_stats

        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        academic_stats = compute_academic_stats(twin)
        system, user = prompts.twin_insight_messages(twin, academic_stats)
        completion = self._complete_validated(
            session,
            ctx,
            task="twin_insight",
            system=system,
            user=user,
            schema=TwinInsight,
            twin_version=repo.get_twin_version(ctx),
        )
        insight = completion.result
        repo.save_artifact(
            ctx, "twin_insight", insight.model_dump(mode="json"), prompt_text=user
        )
        return insight

    def explain_career_match(
        self,
        session: Session,
        ctx: UserContext,
        job: dict[str, Any],
        *,
        match_score: int,
        matched_skills: list[str],
        missing_skills: list[str],
    ) -> CareerMatchExplanation:
        """Explain a role fit; numeric score stays deterministic."""
        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        system, user = prompts.career_match_messages(
            twin, job, match_score, matched_skills, missing_skills
        )
        completion = self._complete_validated(
            session,
            ctx,
            task="career_match",
            system=system,
            user=user,
            schema=CareerMatchExplanation,
            twin_version=repo.get_twin_version(ctx),
        )
        explanation = completion.result
        # Enforce hybrid scoring: never trust a model-invented score
        fixed = explanation.model_copy(
            update={
                "match_score": int(match_score),
                "score_source": "deterministic",
                "matched_skills": matched_skills,
                "missing_skills": missing_skills,
            }
        )
        repo.save_artifact(
            ctx, "career_match", fixed.model_dump(mode="json"), prompt_text=user
        )
        return fixed

    def build_learning_roadmap(
        self,
        session: Session,
        ctx: UserContext,
        target_role: str,
        *,
        missing_skills: list[str] | None = None,
    ) -> SkillGapRoadmap:
        """Week-by-week plan to close skill gaps for a target role."""
        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        gaps = missing_skills or []
        system, user = prompts.roadmap_messages(twin, target_role, gaps)
        completion = self._complete_validated(
            session,
            ctx,
            task="skill_gap_roadmap",
            system=system,
            user=user,
            schema=SkillGapRoadmap,
            twin_version=repo.get_twin_version(ctx),
        )
        roadmap = completion.result
        if not roadmap.target_role:
            roadmap = roadmap.model_copy(update={"target_role": target_role})
        repo.save_artifact(
            ctx, "roadmap", roadmap.model_dump(mode="json"), prompt_text=user
        )
        return roadmap

    def generate_cv_content(
        self,
        session: Session,
        ctx: UserContext,
        job_description: str | dict[str, Any],
    ) -> CVContent:
        """Tailored CV/cover letter; facts only from this student's twin."""
        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        from modules.cv_exports import cv_facts, select_facts, cv_markdown

        facts = cv_facts(twin)
        system, user = prompts.cv_selection_messages(facts, job_description)
        user = (
            prompts.wrap_untrusted(
                "STUDENT_CONTEXT",
                {"profile": {"name": twin["profile"].get("name", "")}},
            )
            + "\n"
            + user
        )
        completion = self._complete_validated(
            session,
            ctx,
            task="cv_selection",
            system=system,
            user=user,
            schema=CVSelection,
            twin_version=repo.get_twin_version(ctx),
        )
        selection = completion.result
        selected = select_facts(facts, selection.fact_ids)
        profile = twin["profile"]
        name = profile.get("name") or "Student"
        missing = [
            label
            for key, label in (
                ("institution", "Institution"),
                ("graduation_date", "Expected graduation date"),
            )
            if not profile.get(key)
        ]
        content = CVContent(
            cv_markdown=cv_markdown(twin, selected),
            cover_letter_markdown=f"Dear Hiring Manager,\n\nI am {name}. My reported education is {profile.get('degree') or 'not yet specified'}.\n\nMy relevant learning evidence includes:\n"
            + "\n".join(
                f"- {f['text']}"
                for f in selected
                if f["section"] in ("Skills", "Projects", "Assessed Learning")
            )
            + f"\n\nSincerely,\n{name}",
            missing_information=missing,
            evidence_used=selection.evidence_used + [selection.rationale],
            confidence=selection.confidence,
            notice=completion.notice or "AI-generated, verify important details",
        )
        repo.save_artifact(
            ctx,
            "cv_selection",
            {
                "facts": selected,
                "twin_version": repo.get_twin_version(ctx),
                "target": job_description,
                "rationale": selection.rationale,
                "confidence": selection.confidence,
                "offline_mode": completion.offline_mode,
                "provider": completion.provider,
            },
        )
        repo.save_artifact(
            ctx, "cv_content", content.model_dump(mode="json"), prompt_text=user
        )
        return content

    def coach_chat(
        self, session: Session, ctx: UserContext, message: str
    ) -> CoachReply:
        """Coach reply with per-user conversation memory."""
        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        history = repo.get_chat_history(ctx, limit=MAX_CHAT_HISTORY)
        system, user = prompts.coach_messages(twin, message, history)
        completion = self._complete_validated(
            session,
            ctx,
            task="coach_reply",
            system=system,
            user=user,
            schema=CoachReply,
            twin_version=repo.get_twin_version(ctx),
            use_cache=False,  # chat should feel conversational
        )
        reply = completion.result
        repo.add_chat_message(ctx, "user", message)
        repo.add_chat_message(ctx, "assistant", reply.reply)
        repo.save_artifact(
            ctx, "coach_reply", reply.model_dump(mode="json"), prompt_text=user
        )
        return reply

    def simulate_what_if(
        self, session: Session, ctx: UserContext, scenario: str
    ) -> WhatIfSimulation:
        """Estimate twin/career impact of a hypothetical action."""
        repo = TwinRepository(session)
        twin = self._load_twin(session, ctx)
        system, user = prompts.what_if_messages(twin, scenario)
        completion = self._complete_validated(
            session,
            ctx,
            task="what_if",
            system=system,
            user=user,
            schema=WhatIfSimulation,
            twin_version=repo.get_twin_version(ctx),
        )
        result = completion.result
        result = result.model_copy(
            update={"is_estimate": True, "scenario": scenario or result.scenario}
        )
        repo.save_artifact(
            ctx, "what_if", result.model_dump(mode="json"), prompt_text=user
        )
        return result


_service_singleton: AIService | None = None


def get_ai_service(*, force_mock: bool = False) -> AIService:
    """Return a process AIService. Force mock for tests / offline demos.

    Note: the service itself holds no student payloads — only the LLM client
    and per-user rate-limit timestamps.
    """
    global _service_singleton
    if force_mock:
        return AIService(client=MockClient(record_prompts=False), offline_mode=True)
    if _service_singleton is None:
        _service_singleton = AIService()
    return _service_singleton


def reset_ai_service() -> None:
    """Clear the process service (tests)."""
    global _service_singleton
    _service_singleton = None
