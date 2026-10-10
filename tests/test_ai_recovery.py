"""A temporary API failure must not disable live AI across saves or students."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from ai.client import MockClient
from ai.service import AIService, RateLimitExceeded, get_ai_service
from modules.learning import enroll_course
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


class RecoveringClient(MockClient):
    """Script already-exhausted retries without network calls or sleeping."""

    provider_name = "live_test"
    is_mock = False

    def __init__(
        self, *, failures: int = 0, invalid_responses: int = 0, model: str = "model-a"
    ) -> None:
        super().__init__()
        self.failures = failures
        self.invalid_responses = invalid_responses
        self.requests: list[str] = []
        self._model = model

    def complete_with_retry(self, **kwargs: Any) -> str:
        self.requests.append(kwargs["user_id"])
        if self.failures:
            self.failures -= 1
            raise TimeoutError("Provider temporarily unavailable")
        if self.invalid_responses:
            self.invalid_responses -= 1
            return "not valid JSON"
        payload = json.loads(super().complete(**kwargs))
        payload["notice"] = "Live provider response"
        if "strengths" in payload:
            payload["strengths"].append(f"Live response from {self.model_name}")
        return json.dumps(payload)


@pytest.mark.parametrize("failure", ["timeout", "invalid_json"])
def test_next_request_recovers_without_resetting_shared_service(
    open_session, ctx_a, monkeypatch, failure: str
) -> None:
    import ai.service as service_module

    client = RecoveringClient(
        failures=1 if failure == "timeout" else 0,
        invalid_responses=2 if failure == "invalid_json" else 0,
    )
    service = AIService(client=client)
    monkeypatch.setattr(service_module, "_service_singleton", service)
    with open_session() as session:
        repo = TwinRepository(session)
        repo.save_twin(ctx_a, empty_twin("Recovery Student"))
        fallback = service.generate_twin_insights(session, ctx_a)
        fallback_keys = repo.list_ai_cache_keys(ctx_a)
        assert "offline example" in fallback.notice
        assert fallback.confidence <= 0.5
        assert service.client is client and not service.offline_mode

        # A rerun obtains the same service. Its fallback cache cannot mask recovery.
        assert get_ai_service() is service
        recovered = get_ai_service().generate_twin_insights(session, ctx_a)
        assert "Live response from model-a" in recovered.strengths
        assert recovered.notice == "Live provider response"
        assert len(repo.list_ai_cache_keys(ctx_a)) == len(fallback_keys) + 1
        request_count = len(client.requests)
        assert service.generate_twin_insights(session, ctx_a) == recovered
        assert len(client.requests) == request_count

        # Saving creates a new version without losing the configured live client.
        twin = repo.get_twin(ctx_a)
        twin["profile"]["institution"] = "Updated university"
        repo.save_twin(ctx_a, twin, label="save_after_recovery")
        saved_result = get_ai_service().generate_twin_insights(session, ctx_a)
        assert saved_result.notice == "Live provider response"
        assert len(client.requests) == request_count + 1


def test_one_students_failure_does_not_disable_another_students_ai(
    open_session, ctx_a, ctx_b
) -> None:
    client = RecoveringClient(failures=1)
    service = AIService(client=client)
    with open_session() as session:
        repo = TwinRepository(session)
        repo.save_twin(ctx_a, empty_twin("PRIVATE_ALPHA_MARKER"))
        repo.save_twin(ctx_b, empty_twin("PRIVATE_BETA_MARKER"))
        fallback = service.generate_twin_insights(session, ctx_a)
        live = service.generate_twin_insights(session, ctx_b)
        assert "offline example" in fallback.notice
        assert live.notice == "Live provider response"
        assert "PRIVATE_ALPHA_MARKER" not in live.model_dump_json()
        assert "PRIVATE_ALPHA_MARKER" not in json.dumps(
            client.prompts_for(ctx_b.user_id)
        )
        assert all(
            key.startswith(ctx_b.user_id) for key in repo.list_ai_cache_keys(ctx_b)
        )
    assert client.requests == [ctx_a.user_id, ctx_b.user_id]
    assert service.client is client


def test_cache_is_separate_for_different_live_models(open_session, ctx_a) -> None:
    first_client = RecoveringClient(model="model-a")
    second_client = RecoveringClient(model="model-b")
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, empty_twin("Model Test Student"))
        AIService(client=first_client).generate_twin_insights(session, ctx_a)
        second = AIService(client=second_client).generate_twin_insights(session, ctx_a)
    assert "Live response from model-b" in second.strengths
    assert second_client.requests == [ctx_a.user_id]


def test_cached_results_do_not_consume_the_local_rate_budget(
    open_session, ctx_a, monkeypatch
) -> None:
    import ai.service as service_module

    monkeypatch.setattr(service_module, "AI_RATE_LIMIT_PER_MINUTE", 1)
    client = RecoveringClient()
    service = AIService(client=client)
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, empty_twin("Cached Student"))
        first = service.generate_twin_insights(session, ctx_a)
        for _ in range(5):
            assert service.generate_twin_insights(session, ctx_a) == first
        with pytest.raises(RateLimitExceeded):
            service.coach_chat(session, ctx_a, "A new uncached request")
    assert len(client.requests) == 1


def test_fallback_quiz_stays_practice_only_after_api_recovery(
    open_session, ctx_a
) -> None:
    client = RecoveringClient(failures=1)
    service = AIService(client=client)
    with open_session() as session:
        repo = TwinRepository(session)
        twin = enroll_course(
            empty_twin("Quiz Student"),
            "Python",
            "Python course",
            "https://ocw.mit.edu/",
        )
        repo.save_twin(ctx_a, twin)
        course_id = twin["learning_courses"][0]["id"]
        fallback = service.generate_course_assessment(
            session, ctx_a, course_id, "Completed loops and functions."
        )
        assert fallback["offline_mode"] and fallback["provider"] == "mock"
        service.generate_twin_insights(session, ctx_a)
        assert not service.offline_mode
        practice = service.submit_course_assessment(
            session,
            ctx_a,
            fallback["id"],
            [question["answer_index"] for question in fallback["quiz"]["questions"]],
        )
        assert practice["practice_only"]
        assert not repo.get_twin(ctx_a)["progress_events"]

        live = service.generate_course_assessment(
            session, ctx_a, course_id, "Reviewed the examples and exercises."
        )
        assert not live["offline_mode"] and live["provider"] == "live_test"
        assessed = service.submit_course_assessment(
            session,
            ctx_a,
            live["id"],
            [question["answer_index"] for question in live["quiz"]["questions"]],
        )
        assert assessed["passed"] and not assessed["practice_only"]


def test_saving_and_rerunning_streamlit_retries_live_ai(
    db, open_session, ctx_a, monkeypatch
) -> None:
    import ai.service as service_module
    import modules.market_research as market_module
    import storage.database as database

    client = RecoveringClient(failures=1)
    service = AIService(client=client)
    monkeypatch.setattr(service_module, "_service_singleton", service)
    monkeypatch.setattr(database, "DATABASE_URL", db)
    monkeypatch.setattr(
        market_module,
        "research_local_market",
        lambda *args, **kwargs: {
            "mode": "reference",
            "location": "",
            "retrieved_at": "2026-10-10T00:00:00+00:00",
            "sources": [],
            "notice": "Reference evidence for this test only.",
        },
    )
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(str(app_path), default_timeout=30)
    app.session_state["logged_in"] = True
    app.session_state["user_id"] = ctx_a.user_id
    app.session_state["ai_force_mock"] = False
    app.run()
    assert not app.exception
    next(field for field in app.text_input if field.label == "Full name").input(
        "Save Recovery Student"
    )
    next(
        button for button in app.button if button.label == "Save twin & analyze"
    ).click().run()
    assert not app.exception
    with open_session() as session:
        repo = TwinRepository(session)
        assert repo.get_twin(ctx_a)["profile"]["name"] == "Save Recovery Student"
        assert repo.list_artifacts(ctx_a, kind="career_plan")[0]["payload"][
            "offline_mode"
        ]

    app.run()
    assert not app.exception
    assert len(client.requests) == 1  # Merely rendering the page makes no API call.
    next(
        button for button in app.button if button.label == "Save twin & analyze"
    ).click().run()
    assert not app.exception
    with open_session() as session:
        plan = TwinRepository(session).list_artifacts(ctx_a, kind="career_plan")[0][
            "payload"
        ]
        assert not plan["offline_mode"] and plan["provider"] == "live_test"
    assert len(client.requests) == 2
    assert get_ai_service().client is client
    assert not any("Offline / mock AI mode" in warning.value for warning in app.warning)
