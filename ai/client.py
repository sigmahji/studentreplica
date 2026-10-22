"""Provider-agnostic LLM client with Anthropic default and Mock fallback."""

from __future__ import annotations

import json
import logging
import math
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from config import (
    AI_MODEL,
    AI_PROVIDER,
    ANTHROPIC_API_KEY,
    OPENAI_API_KEY,
    GROQ_API_KEY,
    GROQ_MODEL,
)

_logger = logging.getLogger("student_twin.ai")


class LLMClient(ABC):
    """Minimal chat-completion interface used by AIService."""

    provider_name: str = "base"
    is_mock: bool = False

    @property
    def model_name(self) -> str:
        """Return the configured public model identifier, never credentials."""
        return getattr(self, "_model", "")

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        user_id: str,
        max_tokens: int = 2048,
    ) -> str:
        """Return raw model text (expected to be JSON). Never log API keys."""

    def complete_with_retry(
        self,
        *,
        system: str,
        user: str,
        user_id: str,
        max_tokens: int = 2048,
        attempts: int = 3,
    ) -> str:
        """Call complete with exponential backoff on transient errors."""
        delay = 0.5
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return self.complete(
                    system=system,
                    user=user,
                    user_id=user_id,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001 — surfaced to fallback
                last_exc = exc
                _logger.warning(
                    "event=llm_retry user_id=%s attempt=%s provider=%s",
                    user_id,
                    attempt + 1,
                    self.provider_name,
                )
                if attempt + 1 >= attempts:
                    break
                status = getattr(exc, "status_code", None)
                if status in (400, 401, 403, 404, 413, 422):
                    break
                wait_seconds = delay
                if status == 429:
                    response = getattr(exc, "response", None)
                    headers = getattr(response, "headers", {})
                    try:
                        retry_after = float(headers.get("retry-after", delay))
                    except (TypeError, ValueError):
                        retry_after = delay
                    if math.isfinite(retry_after) and retry_after > 30:
                        break
                    if math.isfinite(retry_after):
                        wait_seconds = max(delay, retry_after)
                time.sleep(wait_seconds)
                delay *= 2
        assert last_exc is not None
        raise last_exc


class AnthropicClient(LLMClient):
    """Anthropic Messages API via the official SDK."""

    provider_name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key if api_key is not None else ANTHROPIC_API_KEY
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        from anthropic import Anthropic
        from httpx import Client

        self._client = Anthropic(
            api_key=key,
            timeout=25.0,
            max_retries=0,
            http_client=Client(timeout=25.0),
        )
        self._model = model or AI_MODEL

    def complete(
        self,
        *,
        system: str,
        user: str,
        user_id: str,
        max_tokens: int = 2048,
    ) -> str:
        _logger.info(
            "event=llm_call user_id=%s provider=anthropic model=%s",
            user_id,
            self._model,
        )
        message = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in message.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()


class OpenAIClient(LLMClient):
    """Optional OpenAI Chat Completions implementation."""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        base_url: str | None = None,
    ) -> None:
        key = api_key if api_key is not None else OPENAI_API_KEY
        if not key:
            raise ValueError("OPENAI_API_KEY is not set")
        from openai import OpenAI
        from httpx import Client

        # Explicit client avoids old SDKs passing removed httpx proxy options.
        self._client = OpenAI(
            api_key=key,
            base_url=base_url,
            timeout=25.0,
            max_retries=0,
            http_client=Client(timeout=25.0),
        )
        self._model = model or (AI_MODEL if AI_PROVIDER == "openai" else "gpt-4o-mini")

    def complete(
        self,
        *,
        system: str,
        user: str,
        user_id: str,
        max_tokens: int = 2048,
    ) -> str:
        _logger.info(
            "event=llm_call user_id=%s provider=%s model=%s",
            user_id,
            self.provider_name,
            self._model,
        )
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        system
                        if "json" in (system + user).lower()
                        else f"{system}\nRespond with JSON."
                    ),
                },
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or ""
        return content.strip()


class GroqClient(OpenAIClient):
    """Groq chat API via its documented OpenAI-compatible endpoint."""

    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        key = api_key if api_key is not None else GROQ_API_KEY
        if not key:
            raise ValueError("GROQ_API_KEY is not set")
        selected_model = model or (AI_MODEL if AI_PROVIDER == "groq" else GROQ_MODEL)
        super().__init__(
            api_key=key,
            model=selected_model,
            base_url="https://api.groq.com/openai/v1",
        )


class MockClient(LLMClient):
    """Deterministic offline client for tests and graceful demo fallback."""

    provider_name = "mock"
    is_mock = True

    def __init__(self, *, record_prompts: bool = True) -> None:
        self._record_prompts = record_prompts
        self.prompt_log: list[dict[str, Any]] = []

    def prompts_for(self, user_id: str) -> list[dict[str, Any]]:
        """Return recorded prompts for one user (isolation tests)."""
        return [p for p in self.prompt_log if p["user_id"] == user_id]

    def complete(
        self,
        *,
        system: str,
        user: str,
        user_id: str,
        max_tokens: int = 2048,
    ) -> str:
        if self._record_prompts:
            self.prompt_log.append(
                {
                    "user_id": user_id,
                    "system": system,
                    "user_prompt": user,
                }
            )
        _logger.info("event=llm_call user_id=%s provider=mock", user_id)
        task = _detect_task(system)
        name = _extract_name(user)
        return json.dumps(_mock_payload(task, name, user))


def _detect_task(system: str) -> str:
    """Infer task name from the system prompt Task=... marker."""
    match = re.search(r"Task=(repair_)?([a-z_]+)", system)
    if match:
        return match.group(2)
    return "twin_insight"


def _extract_name(user_prompt: str) -> str:
    match = re.search(r'"name"\s*:\s*"([^"]+)"', user_prompt)
    if match:
        return match.group(1)
    return "student"


def _mock_payload(task: str, name: str, user_prompt: str) -> dict[str, Any]:
    """Build schema-valid deterministic JSON from the prompt alone."""
    if task == "course_assessment":
        from ai.mock_planner import _block

        course = _block(user_prompt, "COURSE_CONTEXT", {})
        skill = course.get("skill", "Selected skill")
        # Explicit demonstration questions; never grant real assessed evidence.
        return {
            "skill": skill,
            "preparation": f"Offline practice only. Revise {skill} using your course notes; reconnect AI for a subject-specific assessment.",
            "questions": [
                {
                    "question": f"Practice {i + 1}: what is a reliable way to check your understanding of {skill}?",
                    "options": [
                        "Copy an answer without checking",
                        "Apply a concept and explain the result",
                        "Skip all exercises",
                        "Claim mastery without evidence",
                    ],
                    "answer_index": 1,
                    "explanation": "Apply the concept to an example and explain your reasoning; an offline example is not subject mastery.",
                    "concept": skill,
                }
                for i in range(5)
            ],
            "evidence_used": ["learning_courses"],
            "confidence": 0.2,
            "notice": "Offline practice quiz only; no assessed achievement is awarded.",
        }
    if task == "market_analysis":
        return {
            "openings": [],
            "emerging_advice": "Offline mode cannot verify current openings or emerging trends. Review the linked sources and your university careers office; prioritize academic foundations.",
            "source_ids": [],
            "evidence_used": ["profile.degree", "skills"],
            "confidence": 0.2,
        }
    if task == "cv_selection":
        from ai.mock_planner import _block

        facts = _block(user_prompt, "FACTS_CONTEXT", [])
        return {
            "fact_ids": [f["id"] for f in facts],
            "rationale": "Offline fact-only ordering; no tailoring claims are made.",
            "evidence_used": ["FACTS_CONTEXT"],
            "confidence": 0.3,
        }
    if task == "student_career_plan":
        from ai.mock_planner import mock_student_career_plan

        return mock_student_career_plan(user_prompt)
    skills = re.findall(r'"name"\s*:\s*"([^"]+)"', user_prompt)
    # First name hit is profile name; remaining may be skills — keep unique
    skill_guess = [s for s in skills if s != name][:5] or ["Python", "Git"]

    if task == "career_match":
        score_match = re.search(r"match_score=(\d+)", user_prompt)
        score = int(score_match.group(1)) if score_match else 50
        return {
            "fit_summary": f"{name} has partial overlap with this role.",
            "matched_skills": skill_guess[:2],
            "missing_skills": ["Docker"],
            "confidence": 0.75,
            "evidence_used": ["profile.name", "skills"],
            "match_score": score,
            "score_source": "deterministic",
            "notice": "AI-generated, verify important details",
        }
    if task == "skill_gap_roadmap":
        return {
            "target_role": "Target Role",
            "weeks": [
                {
                    "week": 1,
                    "focus": f"Basics for {name}",
                    "resources": ["Official docs", "Tutorial project"],
                    "milestone": "Complete intro exercises",
                },
                {
                    "week": 2,
                    "focus": "Build a small project",
                    "resources": ["GitHub sample"],
                    "milestone": "Push working demo",
                },
            ],
            "overall_milestone": "Close top skill gaps in 4 weeks",
            "evidence_used": ["skills", "goals"],
            "confidence": 0.7,
            "notice": "AI-generated, verify important details",
        }
    if task == "cv_content":
        return {
            "cv_markdown": (
                f"# {name}\n\n## Summary\n"
                f"Candidate profile grounded in twin skills: "
                f"{', '.join(skill_guess)}.\n"
            ),
            "cover_letter_markdown": (
                f"Dear Hiring Manager,\n\nI am {name} applying based on "
                f"verified twin facts only.\n"
            ),
            "missing_information": ["Work experience dates not in twin"],
            "evidence_used": ["profile.name", "skills", "academic.courses"],
            "confidence": 0.8,
            "fabricated": False,
            "notice": "AI-generated, verify important details",
        }
    if task == "coach_reply":
        from ai.mock_planner import mock_coach_reply

        return mock_coach_reply(user_prompt)
    if task == "what_if":
        return {
            "scenario": "simulated scenario",
            "estimated_skill_changes": [
                {
                    "skill": skill_guess[0],
                    "delta": 10,
                    "reasoning": "Practice typically raises proficiency.",
                }
            ],
            "career_match_impact": "Modest improvement on related roles.",
            "is_estimate": True,
            "reasoning": f"Estimate for {name} based on current twin skills.",
            "evidence_used": ["skills"],
            "confidence": 0.55,
            "notice": "Estimate only — AI-generated, verify important details",
        }
    # default twin_insight (includes academic performance fields)
    subjects = re.findall(
        r'"name"\s*:\s*"([^"]+)".{0,80}?"grade"\s*:\s*("([^"]+)"|(\d+(?:\.\d+)?))',
        user_prompt,
        flags=re.DOTALL,
    )
    subject_insights = []
    for match in subjects[:5]:
        subj = match[0]
        grade = match[2] or match[3] or ""
        subject_insights.append(
            {
                "subject": subj,
                "grade": str(grade),
                "assessment": f"Performance recorded for {subj}.",
                "recommendation": f"Review weak topics in {subj} this week.",
            }
        )
    if not subject_insights and skill_guess:
        subject_insights = [
            {
                "subject": skill_guess[0],
                "grade": "n/a",
                "assessment": "No graded course entry found for this subject.",
                "recommendation": "Add grades so analysis can be more specific.",
            }
        ]
    return {
        "strengths": skill_guess[:3],
        "weaknesses": ["Limited project evidence"],
        "risks": ["Career goals underspecified"],
        "next_actions": [
            {
                "action": "Improve lowest-graded subject",
                "rationale": f"Academic gaps for {name} affect twin quality",
                "priority": 1,
            },
            {
                "action": "Record one project",
                "rationale": "Projects list is thin",
                "priority": 2,
            },
            {
                "action": "Set a career goal",
                "rationale": "Improves matching quality",
                "priority": 3,
            },
        ],
        "academic_summary": (
            f"{name}'s twin includes academic courses/grades; "
            "analysis prioritizes weaker subjects for remediation."
        ),
        "subject_insights": subject_insights,
        "study_level_fit": (
            "Performance reviewed relative to the student's declared study level."
        ),
        "evidence_used": [
            "profile.name",
            "profile.education_level",
            "academic.courses",
            "skills",
        ],
        "confidence": 0.72,
        "notice": "AI-generated, verify important details",
    }


def create_llm_client(
    provider: str | None = None,
    *,
    force_mock: bool = False,
) -> LLMClient:
    """Build the configured client, falling back to MockClient on failure."""
    if force_mock or (provider or AI_PROVIDER).lower() == "mock":
        return MockClient(record_prompts=False)

    chosen = (provider or AI_PROVIDER).lower()
    try:
        if chosen == "groq":
            return GroqClient()
        if chosen == "openai":
            return OpenAIClient()
        # default anthropic
        return AnthropicClient()
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "event=llm_fallback_mock reason=%s",
            type(exc).__name__,
        )
        return MockClient(record_prompts=False)
