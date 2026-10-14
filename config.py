"""Application configuration from environment, dotenv and Streamlit Secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv

# Project paths
PROJECT_ROOT: Path = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _setting(name: str, default: str = "") -> str:
    """Read configuration without exposing credentials or requiring a secrets file."""
    value = os.getenv(name)
    if value is None:
        try:
            import streamlit as st

            value = st.secrets.get(name)
            if value is None:
                sections = ("database", "ai") if name == "DATABASE_URL" else ("ai",)
                for section_name in sections:
                    section = st.secrets.get(section_name, {})
                    if isinstance(section, Mapping):
                        value = section.get(name)
                        if value is None and name == "DATABASE_URL":
                            value = section.get("url")
                    if value is not None:
                        break
        except (FileNotFoundError, KeyError):
            value = None
    return str(value).strip() if value is not None else default


# Local SQLite by default; DATABASE_URL selects a hosted PostgreSQL backend.
DATABASE_DIR: Path = PROJECT_ROOT / "database"
DEFAULT_DATABASE_PATH: Path = DATABASE_DIR / "studentreplica.db"
LEGACY_DATABASE_PATH: Path = DATA_DIR / "student_twin.db"
DATABASE_URL: str = _setting(
    "DATABASE_URL",
    f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}",
)

# Explicit provider selection wins; otherwise use the available provider key.
ANTHROPIC_API_KEY: str | None = _setting("ANTHROPIC_API_KEY") or None
OPENAI_API_KEY: str | None = _setting("OPENAI_API_KEY") or None
GROQ_API_KEY: str | None = _setting("GROQ_API_KEY") or None
TAVILY_API_KEY: str | None = _setting("TAVILY_API_KEY") or None
AI_PROVIDER: str = (
    _setting("AI_PROVIDER")
    or (
        "anthropic" if ANTHROPIC_API_KEY
        else "groq" if GROQ_API_KEY
        else "openai" if OPENAI_API_KEY
        else "anthropic"
    )
).lower()
GROQ_MODEL: str = _setting("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_SEARCH_MODEL: str = _setting("GROQ_SEARCH_MODEL", "openai/gpt-oss-20b")
AI_MODEL: str = _setting(
    "AI_MODEL",
    {
        "anthropic": "claude-sonnet-5-5",
        "openai": "gpt-4o-mini",
        "groq": GROQ_MODEL,
    }.get(AI_PROVIDER, "claude-sonnet-5-5"),
)
# Safety caps
MAX_PROMPT_CHARS: int = int(_setting("MAX_PROMPT_CHARS", "24000"))
MAX_CHAT_HISTORY: int = int(_setting("MAX_CHAT_HISTORY", "12"))
AI_RATE_LIMIT_PER_MINUTE: int = int(_setting("AI_RATE_LIMIT_PER_MINUTE", "20"))
