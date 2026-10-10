"""Groq request routing, JSON mode, isolation, and credential-safe fallback."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai.client import GroqClient, MockClient, create_llm_client
from ai.service import AIService
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


@pytest.fixture()
def groq_sdk(monkeypatch):
    import openai

    constructor_calls, requests = [], []

    def complete(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),
            ]
        )

    def constructor(**kwargs):
        constructor_calls.append(kwargs)
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=complete),
            )
        )

    monkeypatch.setattr(openai, "OpenAI", constructor)
    yield constructor_calls, requests
    for call in constructor_calls:
        call["http_client"].close()


def test_groq_uses_fixed_endpoint_and_stateless_json_requests(groq_sdk, caplog) -> None:
    constructors, requests = groq_sdk
    client = GroqClient(api_key="test-only-credential", model="test-model")
    assert client.provider_name == "groq" and not client.is_mock
    assert constructors[0]["base_url"] == "https://api.groq.com/openai/v1"
    assert constructors[0]["http_client"] is not None
    assert constructors[0]["max_retries"] == 0
    for user_id, marker in (("user-a", "StudentAOnly"), ("user-b", "StudentBOnly")):
        result = client.complete(
            system="Return JSON.", user=marker, user_id=user_id, max_tokens=100
        )
        assert json.loads(result) == {"ok": True}
    assert requests[-1]["model"] == "test-model"
    assert requests[-1]["response_format"] == {"type": "json_object"}
    assert requests[-1]["max_tokens"] == 100
    assert "StudentAOnly" not in json.dumps(requests[-1])
    assert "test-only-credential" not in json.dumps(requests)
    assert "test-only-credential" not in caplog.text


def test_groq_factory_reads_provider_configuration(groq_sdk, monkeypatch) -> None:
    import ai.client as client_module

    monkeypatch.setattr(client_module, "GROQ_API_KEY", "test-only-credential")
    monkeypatch.setattr(client_module, "AI_PROVIDER", "groq")
    monkeypatch.setattr(client_module, "AI_MODEL", "configured-model")
    client = create_llm_client()
    assert isinstance(client, GroqClient)
    assert client.model_name == "configured-model"


def test_missing_groq_key_falls_back_without_using_another_providers_key(
    monkeypatch,
) -> None:
    import ai.client as client_module

    monkeypatch.setattr(client_module, "GROQ_API_KEY", "")
    monkeypatch.setattr(client_module, "OPENAI_API_KEY", "other-provider-key")
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqClient()
    assert isinstance(create_llm_client(provider="groq"), MockClient)


def test_groq_failure_preserves_graceful_private_fallback(
    groq_sdk,
    open_session,
    ctx_a,
    monkeypatch,
    caplog,
) -> None:
    import ai.client as client_module

    client = GroqClient(api_key="test-only-credential")

    def unavailable(**kwargs):
        raise TimeoutError("Do not log this student payload or test-only-credential")

    monkeypatch.setattr(client._client.chat.completions, "create", unavailable)
    monkeypatch.setattr(client_module.time, "sleep", lambda _: None)
    service = AIService(client=client)
    with open_session() as session:
        TwinRepository(session).save_twin(ctx_a, empty_twin("PrivateStudentName"))
        insight = service.generate_twin_insights(session, ctx_a)
    assert insight.next_actions
    assert "offline example" in insight.notice
    assert service.offline_mode is False
    assert service.client is client
    assert service.client.provider_name == "groq"
    assert "PrivateStudentName" not in caplog.text
    assert "test-only-credential" not in caplog.text


@pytest.mark.parametrize(
    "status,retry_after,expected_calls,expected_waits",
    [
        (429, "2.5", 2, [2.5]),
        (429, "120", 1, []),
        (401, "1", 1, []),
    ],
)
def test_retries_honor_provider_limits_and_skip_permanent_errors(
    monkeypatch,
    status,
    retry_after,
    expected_calls,
    expected_waits,
) -> None:
    import ai.client as client_module

    class ProviderError(RuntimeError):
        status_code = status
        response = SimpleNamespace(headers={"retry-after": retry_after})

    class RetryClient(MockClient):
        calls = 0

        def complete(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError()
            return '{"ok": true}'

    waits = []
    monkeypatch.setattr(client_module.time, "sleep", waits.append)
    client = RetryClient()
    if expected_calls == 1:
        with pytest.raises(ProviderError):
            client.complete_with_retry(
                system="Return JSON", user="connection test", user_id="test"
            )
    else:
        assert json.loads(
            client.complete_with_retry(
                system="Return JSON", user="connection test", user_id="test"
            )
        )["ok"]
    assert client.calls == expected_calls
    assert waits == expected_waits
