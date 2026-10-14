"""Credential loading for local execution and Streamlit Cloud, using fake keys."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import dotenv
import pytest
import streamlit


@pytest.fixture()
def load_config(monkeypatch):
    """Load a separate config namespace without local credentials or module reloads."""
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for name in (
        "AI_PROVIDER", "AI_MODEL", "GROQ_MODEL", "GROQ_SEARCH_MODEL",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "TAVILY_API_KEY",
        "DATABASE_URL", "MAX_PROMPT_CHARS", "MAX_CHAT_HISTORY",
        "AI_RATE_LIMIT_PER_MINUTE",
    ):
        monkeypatch.delenv(name, raising=False)
    path = Path(__file__).resolve().parents[1] / "config.py"

    def load(secrets: Any = None) -> dict[str, Any]:
        monkeypatch.setattr(streamlit, "secrets", {} if secrets is None else secrets)
        return runpy.run_path(str(path))

    return load


@pytest.mark.parametrize("nested", [False, True])
def test_groq_key_in_streamlit_secrets_selects_groq(load_config, nested) -> None:
    secrets = {"GROQ_API_KEY": "  synthetic-cloud-key  "}
    config = load_config({"ai": secrets} if nested else secrets)
    assert config["GROQ_API_KEY"] == "synthetic-cloud-key"
    assert config["AI_PROVIDER"] == "groq"
    assert config["AI_MODEL"] == "openai/gpt-oss-120b"
    assert config["ANTHROPIC_API_KEY"] is None


def test_explicit_environment_settings_take_precedence(load_config, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-environment-key")
    monkeypatch.setenv("AI_PROVIDER", " GROQ ")
    monkeypatch.setenv("AI_MODEL", "explicit-model")
    config = load_config({"ai": {
        "GROQ_API_KEY": "synthetic-secret-key", "AI_PROVIDER": "mock",
        "AI_MODEL": "secret-model",
    }})
    assert config["GROQ_API_KEY"] == "synthetic-environment-key"
    assert config["AI_PROVIDER"] == "groq"
    assert config["AI_MODEL"] == "explicit-model"


def test_root_secrets_take_precedence_over_nested_settings(load_config) -> None:
    config = load_config({
        "GROQ_API_KEY": "synthetic-root-key",
        "ai": {"GROQ_API_KEY": "synthetic-nested-key"},
    })
    assert config["GROQ_API_KEY"] == "synthetic-root-key"


def test_explicit_mock_provider_is_not_overridden_by_a_key(load_config) -> None:
    config = load_config({"AI_PROVIDER": "mock", "GROQ_API_KEY": "synthetic-key"})
    assert config["AI_PROVIDER"] == "mock"


def test_missing_secrets_file_preserves_offline_defaults(load_config) -> None:
    class MissingSecrets:
        def get(self, name, default=None):
            raise FileNotFoundError("No synthetic secrets file")

    config = load_config(MissingSecrets())
    assert config["GROQ_API_KEY"] is None
    assert config["AI_PROVIDER"] == "anthropic"
    assert config["MAX_PROMPT_CHARS"] == 24000


def test_anthropic_remains_default_when_its_key_is_available(load_config) -> None:
    config = load_config({
        "ANTHROPIC_API_KEY": "synthetic-anthropic-key",
        "GROQ_API_KEY": "synthetic-groq-key",
    })
    assert config["AI_PROVIDER"] == "anthropic"


def test_openai_only_key_selects_openai(load_config) -> None:
    config = load_config({"OPENAI_API_KEY": "synthetic-openai-key"})
    assert config["AI_PROVIDER"] == "openai"
    assert config["AI_MODEL"] == "gpt-4o-mini"


@pytest.mark.parametrize("settings", [
    {"DATABASE_URL": "postgresql://synthetic@host/students"},
    {"database": {"url": "postgresql://synthetic@host/students"}},
    {"database": {"DATABASE_URL": "postgresql://synthetic@host/students"}},
])
def test_cloud_database_secrets_are_loaded_without_becoming_ai_context(
    load_config, settings,
) -> None:
    config = load_config(settings)
    assert config["DATABASE_URL"] == "postgresql://synthetic@host/students"
    assert config["GROQ_API_KEY"] is None


def test_local_database_override_is_not_replaced_by_cloud_secrets(load_config, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///private-local.db")
    config = load_config({"database": {"url": "postgresql://synthetic@host/students"}})
    assert config["DATABASE_URL"] == "sqlite:///private-local.db"
