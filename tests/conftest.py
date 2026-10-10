"""Pytest fixtures: isolated in-memory SQLite per test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure project root is importable when running pytest from any cwd
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.context import UserContext, new_user_context  # noqa: E402
from storage.database import init_db, reset_engine, session_scope  # noqa: E402


@pytest.fixture()
def db_url(tmp_path: Path) -> str:
    """Unique SQLite file per test to avoid cross-test leakage."""
    path = tmp_path / "test_twin.db"
    return f"sqlite:///{path.as_posix()}"


@pytest.fixture()
def db(db_url: str):
    """Initialize a fresh database and reset the process engine afterward."""
    reset_engine()
    init_db(db_url)
    yield db_url
    reset_engine()


@pytest.fixture()
def ctx_a() -> UserContext:
    return new_user_context(session_id="test-a")


@pytest.fixture()
def ctx_b() -> UserContext:
    return new_user_context(session_id="test-b")


@pytest.fixture()
def open_session(db: str):
    """Factory that opens a session bound to the test DB."""

    def _open():
        return session_scope(db)

    return _open
