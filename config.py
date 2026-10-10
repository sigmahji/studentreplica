"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project paths
PROJECT_ROOT: Path = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite database (all student rows keyed by user_id)
DATABASE_DIR: Path = PROJECT_ROOT / "database"
DEFAULT_DATABASE_PATH: Path = DATABASE_DIR / "studentreplica.db"
LEGACY_DATABASE_PATH: Path = DATA_DIR / "student_twin.db"
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}",
)

# AI settings (used from Phase 2 onward; safe defaults here)
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "anthropic").strip().lower()
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_SEARCH_MODEL: str = os.getenv("GROQ_SEARCH_MODEL", "openai/gpt-oss-20b")
AI_MODEL: str = os.getenv(
    "AI_MODEL",
    {
        "anthropic": "claude-sonnet-5-5",
        "openai": "gpt-4o-mini",
        "groq": GROQ_MODEL,
    }.get(AI_PROVIDER, "claude-sonnet-5-5"),
)
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY: str | None = os.getenv("TAVILY_API_KEY")

# Safety caps
MAX_PROMPT_CHARS: int = int(os.getenv("MAX_PROMPT_CHARS", "24000"))
MAX_CHAT_HISTORY: int = int(os.getenv("MAX_CHAT_HISTORY", "12"))
AI_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("AI_RATE_LIMIT_PER_MINUTE", "20"))
