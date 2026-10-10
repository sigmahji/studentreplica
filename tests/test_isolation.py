"""Mandatory isolation tests: student A data must never appear in student B."""

from __future__ import annotations

import json
from typing import Any

from ai.client import MockClient
from ai.service import AIService
from storage.context import UserContext
from storage.pipeline import run_full_pipeline
from storage.repository import TwinRepository


STUDENT_A: dict[str, Any] = {
    "name": "AliceAbramsonUNIQUE_A_TOKEN",
    "degree": "B.S. Quantum Horticulture A_DEGREE_TOKEN",
    "verified_skills": ["AlchemyA_SKILL", "XylophoneAPI_A"],
    "core_courses": ["NebulaFarming_A_COURSE"],
    "experience_level": "Senior Astronaut A_LEVEL",
    "strengths_summary": "Alice-only summary phrase ZZYZX_A_SUMMARY.",
}

STUDENT_B: dict[str, Any] = {
    "name": "BobBakerUNIQUE_B_TOKEN",
    "degree": "M.S. Marine Robotics B_DEGREE_TOKEN",
    "verified_skills": ["SubmarineKotlin_B", "CoralSQL_B"],
    "core_courses": ["DeepSeaOS_B_COURSE"],
    "experience_level": "Intern Mariner B_LEVEL",
    "strengths_summary": "Bob-only summary phrase QQWEE_B_SUMMARY.",
}

A_MARKERS = [
    "AliceAbramsonUNIQUE_A_TOKEN",
    "Quantum Horticulture A_DEGREE_TOKEN",
    "AlchemyA_SKILL",
    "XylophoneAPI_A",
    "NebulaFarming_A_COURSE",
    "ZZYZX_A_SUMMARY",
]

B_MARKERS = [
    "BobBakerUNIQUE_B_TOKEN",
    "Marine Robotics B_DEGREE_TOKEN",
    "SubmarineKotlin_B",
    "CoralSQL_B",
    "DeepSeaOS_B_COURSE",
    "QQWEE_B_SUMMARY",
]


def _serialize(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _assert_no_markers(blob: str, markers: list[str], *, label: str) -> None:
    for marker in markers:
        assert marker not in blob, f"{label} leaked marker: {marker}"


def _fresh_mock_ai() -> tuple[AIService, MockClient]:
    client = MockClient()
    return AIService(client=client, offline_mode=True), client


def test_two_students_full_pipeline_isolated(
    open_session, ctx_a: UserContext, ctx_b: UserContext
) -> None:
    """Run the full pipeline for A and B; assert zero cross-contamination."""
    ai_a, _ = _fresh_mock_ai()
    ai_b, _ = _fresh_mock_ai()

    with open_session() as session:
        out_a = run_full_pipeline(session, ctx_a, STUDENT_A, ai_a)
        out_b = run_full_pipeline(session, ctx_b, STUDENT_B, ai_b)

        repo = TwinRepository(session)
        twin_a = repo.get_twin(ctx_a)
        twin_b = repo.get_twin(ctx_b)
        assert twin_a is not None and twin_b is not None
        assert twin_a["profile"]["name"] == STUDENT_A["name"]
        assert twin_b["profile"]["name"] == STUDENT_B["name"]

        b_blobs = repo.dump_user_strings(ctx_b)
        b_joined = "\n".join(b_blobs) + "\n" + _serialize(out_b)
        _assert_no_markers(b_joined, A_MARKERS, label="student_B_storage_or_output")

        a_blobs = repo.dump_user_strings(ctx_a)
        a_joined = "\n".join(a_blobs) + "\n" + _serialize(out_a)
        _assert_no_markers(a_joined, B_MARKERS, label="student_A_storage_or_output")

        for key in repo.list_ai_cache_keys(ctx_b):
            assert key.startswith(ctx_b.user_id)
            assert ctx_a.user_id not in key

        for key in repo.list_ai_cache_keys(ctx_a):
            assert key.startswith(ctx_a.user_id)
            assert ctx_b.user_id not in key

        hist_a = repo.get_chat_history(ctx_a, limit=100)
        hist_b = repo.get_chat_history(ctx_b, limit=100)
        assert hist_a and hist_b
        _assert_no_markers(_serialize(hist_b), A_MARKERS, label="chat_B")
        _assert_no_markers(_serialize(hist_a), B_MARKERS, label="chat_A")


def test_prompt_payload_for_b_excludes_a(
    open_session, ctx_a: UserContext, ctx_b: UserContext
) -> None:
    """Inspect exact AI prompt payloads for B; none may contain A strings."""
    # Shared MockClient records every prompt with user_id
    client = MockClient()
    ai = AIService(client=client, offline_mode=True)

    with open_session() as session:
        run_full_pipeline(session, ctx_a, STUDENT_A, ai)
        run_full_pipeline(session, ctx_b, STUDENT_B, ai)

    prompts_b = client.prompts_for(ctx_b.user_id)
    assert prompts_b, "expected prompt payloads for student B"
    for prompt in prompts_b:
        blob = _serialize(prompt)
        assert prompt["user_id"] == ctx_b.user_id
        _assert_no_markers(blob, A_MARKERS, label="prompt_B")
        assert STUDENT_B["name"] in blob


def test_repository_get_never_returns_other_user(
    open_session, ctx_a: UserContext, ctx_b: UserContext
) -> None:
    """Direct repository reads are strictly filtered by user_id."""
    with open_session() as session:
        repo = TwinRepository(session)
        repo.save_twin(
            ctx_a,
            {
                "profile": {"name": STUDENT_A["name"]},
                "skills": [],
                "academic": {"courses": []},
                "projects": [],
                "achievements": [],
                "goals": [],
                "meta": {},
            },
        )
        repo.save_twin(
            ctx_b,
            {
                "profile": {"name": STUDENT_B["name"]},
                "skills": [],
                "academic": {"courses": []},
                "projects": [],
                "achievements": [],
                "goals": [],
                "meta": {},
            },
        )
        assert repo.get_twin(ctx_a)["profile"]["name"] == STUDENT_A["name"]
        assert repo.get_twin(ctx_b)["profile"]["name"] == STUDENT_B["name"]
        assert STUDENT_A["name"] not in _serialize(repo.get_twin(ctx_b))
