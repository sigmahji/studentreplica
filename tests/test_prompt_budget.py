"""Compact prompt JSON and private, actionable provider error reporting."""

from __future__ import annotations

import json

import pytest

from ai.client import MockClient
from ai.prompts import student_career_plan_messages, wrap_untrusted
from ai.service import AIService
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def test_compact_json_keeps_all_values_and_delimiters_with_fewer_tokens() -> None:
    payload = {
        "profile": {
            "name": "Synthetic Student",
            "notes": "Spaces inside values stay intact.",
        },
        "courses": [
            {"name": f"Course {i}", "grade": "C+", "core": True} for i in range(35)
        ],
    }
    wrapped = wrap_untrusted("STUDENT_CONTEXT", payload, max_chars=20000)
    start, body, end = wrapped.split("\n")
    assert start == "STUDENT_CONTEXT_BEGIN"
    assert end == "STUDENT_CONTEXT_END"
    assert json.loads(body) == payload
    assert len(body) < len(json.dumps(payload, indent=2)) * 0.7


def test_career_plan_has_compact_parseable_blocks_and_a_versioned_schema() -> None:
    context = {"profile": {"name": "Only This Student"}, "skills": [{"name": "Python"}]}
    market = {
        "mode": "live_web",
        "sources": [{"id": "source-1", "snippet": "Source evidence"}],
        "feed_openings": [{"unused": "Repeated listing"}],
    }
    references = [{"title": "Software Engineer", "required_skills": ["Python"]}]
    system, user = student_career_plan_messages(context, market, references)
    for label, expected in (
        ("STUDENT_CONTEXT", context),
        ("MARKET_CONTEXT", {k: v for k, v in market.items() if k != "feed_openings"}),
        ("ROLE_REFERENCES", references),
    ):
        body = user.split(f"{label}_BEGIN\n", 1)[1].split(f"\n{label}_END", 1)[0]
        assert json.loads(body) == expected
        assert "\n" not in body
    assert "prompt=v4" in system
    schema = json.loads(system.split("Return JSON matching this schema: ", 1)[1])
    assert schema["title"] == "StudentCareerPlan"
    assert "Repeated listing" not in user


@pytest.mark.parametrize(
    "status,reason", [(413, "token limit"), (429, "rate limit"), (401, "API key")]
)
def test_provider_failure_reports_a_safe_reason_and_next_request_recovers(
    open_session, ctx_a, caplog, status: int, reason: str
) -> None:
    class ProviderError(RuntimeError):
        status_code = status

    class OnceFailingClient(MockClient):
        is_mock = False
        provider_name = "live_test"
        failed = False

        def complete_with_retry(self, **kwargs):
            if not self.failed:
                self.failed = True
                raise ProviderError("PRIVATE_STUDENT_PAYLOAD_AND_API_KEY")
            return self.complete(**kwargs)

    client = OnceFailingClient()
    service = AIService(client=client)
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, empty_twin("Synthetic Student"))
        fallback = service.generate_twin_insights(session, ctx_a)
        assert reason in fallback.notice
        assert "offline example" in fallback.notice
        assert "PRIVATE_STUDENT_PAYLOAD_AND_API_KEY" not in fallback.notice
        assert "PRIVATE_STUDENT_PAYLOAD_AND_API_KEY" not in caplog.text
        assert f"http_status={status}" in caplog.text
        recovered = service.generate_twin_insights(session, ctx_a)
        assert "offline example" not in recovered.notice
        assert service.client is client
