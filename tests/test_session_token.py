"""Unit tests for persistent device session tokens."""

from __future__ import annotations

import time
from uuid import uuid4

from storage.session_token import create_session_token, validate_session_token


def test_session_token_round_trip() -> None:
    uid = str(uuid4())
    token = create_session_token(uid)
    assert isinstance(token, str) and len(token) > 20
    restored = validate_session_token(token)
    assert restored == uid


def test_invalid_session_token_returns_none() -> None:
    assert validate_session_token("") is None
    assert validate_session_token("invalid.token.here") is None
    assert validate_session_token(None) is None  # type: ignore[arg-type]


def test_tampered_session_token_rejected() -> None:
    uid = str(uuid4())
    token = create_session_token(uid)
    tampered = token[:-4] + "abcd"
    assert validate_session_token(tampered) is None


def test_expired_session_token_rejected() -> None:
    uid = str(uuid4())
    token = create_session_token(uid)
    # Validate with negative max_age to simulate immediate expiration
    assert validate_session_token(token, max_age=-1) is None


def test_app_restores_user_from_session_token(db, monkeypatch) -> None:
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    from storage.auth import create_account
    from storage.database import session_scope

    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    with session_scope(db) as session:
        acc = create_account(session, username="token-student", password="password123")
        assert acc.ok and acc.user_id
        uid = acc.user_id

    token = create_session_token(uid)
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    app.session_state["ai_force_mock"] = True
    app.query_params["session"] = token
    app.run()
    assert not app.exception
    assert app.session_state["logged_in"] is True
    assert app.session_state["user_id"] == uid
