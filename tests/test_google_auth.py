"""Verified Google identities, private storage, native login and logout UI."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import streamlit as st
from sqlalchemy import func, inspect, select
from streamlit.errors import StreamlitAPIException
from streamlit.testing.v1 import AppTest

from ai.client import MockClient
from ai.service import AIService
from modules.google_auth import GOOGLE_METADATA_URL, google_login_settings
from modules.onboarding_tour import load_tour_state
from storage.auth import create_account, login_account, login_google_account
from storage.context import UserContext
from storage.database import get_engine, init_db, reset_engine, session_scope
from storage.models import Account, Base, ExternalIdentity
from storage.pipeline import run_full_pipeline
from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def claims(subject: str = "synthetic-google-a", **changes) -> dict:
    """Create synthetic provider-verified claims without calling Google."""
    return {
        "iss": "https://accounts.google.com", "sub": subject,
        "email_verified": True, "email": "synthetic-student@example.test",
        "name": "Synthetic Google Student", "exp": int(time.time()) + 3600,
        **changes,
    }


def auth_secrets() -> dict:
    """Configuration-shaped test values, never real OAuth credentials."""
    return {"auth": {
        "redirect_uri": "http://localhost:8501/oauth2callback",
        "cookie_secret": "synthetic-test-cookie-not-for-deployment-0001",
        "google": {
            "client_id": "synthetic-client.apps.googleusercontent.com",
            "client_secret": "synthetic-client-secret",
            "server_metadata_url": GOOGLE_METADATA_URL,
        },
    }}


def test_google_identity_restores_the_same_private_account_after_restart(db) -> None:
    first_claims = claims()
    with session_scope(db) as session:
        first = login_google_account(session, first_claims)
        assert first.ok
        ctx = UserContext(user_id=first.user_id)
        TwinRepository(session).save_twin(ctx, empty_twin("GOOGLE_A_PRIVATE_TWIN"))
    reset_engine()
    init_db(db)
    with session_scope(db) as session:
        second = login_google_account(
            session, claims(email="changed@example.test", name="Changed display name")
        )
        assert second.user_id == first.user_id
        assert "GOOGLE_A_PRIVATE_TWIN" in str(TwinRepository(session).get_twin(ctx))
        assert session.scalar(select(func.count()).select_from(Account)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        identity = session.scalars(select(ExternalIdentity)).one()
        assert identity.subject_hash != first_claims["sub"]
        assert len(identity.subject_hash) == 64
        assert not login_account(session, username=first.username, password="!google-only").ok


def test_google_students_and_matching_password_names_never_merge(db, caplog) -> None:
    client = MockClient()
    service = AIService(client=client, offline_mode=True)
    with session_scope(db) as session:
        password_user = create_account(
            session, username="synthetic-student@example.test", password="synthetic-password"
        )
        google_a = login_google_account(session, claims("synthetic-google-a"))
        google_b = login_google_account(session, claims("synthetic-google-b"))
        assert len({password_user.user_id, google_a.user_id, google_b.user_id}) == 3
        for result, marker in ((google_a, "GOOGLE_A_PRIVATE"), (google_b, "GOOGLE_B_PRIVATE")):
            ctx = UserContext(user_id=result.user_id)
            pipeline = run_full_pipeline(session, ctx, {
                "name": marker, "degree": marker, "verified_skills": [marker],
                "core_courses": [marker],
            }, service)
            assert marker in json.dumps(pipeline)
        records = "\n".join(TwinRepository(session).dump_user_strings(
            UserContext(user_id=google_b.user_id)
        ))
        assert "GOOGLE_A_PRIVATE" not in records
        assert "GOOGLE_B_PRIVATE" in records
        assert login_account(
            session, username="synthetic-student@example.test", password="synthetic-password"
        ).user_id == password_user.user_id
    for prompt in client.prompts_for(google_b.user_id):
        assert "GOOGLE_A_PRIVATE" not in json.dumps(prompt)
    assert "synthetic-student@example.test" not in caplog.text
    assert "synthetic-google-a" not in caplog.text
    assert "GOOGLE_A_PRIVATE" not in caplog.text


@pytest.mark.parametrize("changes", [
    {"iss": "https://untrusted.example.test"}, {"sub": ""}, {"sub": None},
    {"sub": "x" * 256}, {"sub": " leading-space"}, {"sub": "non-ascii-\u2603"},
    {"email_verified": False}, {"email_verified": "true"}, {"exp": None},
    {"exp": "9999999999"}, {"exp": True}, {"exp": 0}, {"exp": float("nan")},
    {"exp": float("inf")},
])
def test_invalid_or_expired_claims_never_create_accounts(db, changes) -> None:
    with session_scope(db) as session:
        with pytest.raises(ValueError, match="could not be verified"):
            login_google_account(session, claims(**changes))
        assert session.scalar(select(func.count()).select_from(Account)) == 0
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 0


def test_google_registration_and_mapping_roll_back_together(db) -> None:
    with pytest.raises(RuntimeError):
        with session_scope(db) as session:
            login_google_account(session, claims())
            raise RuntimeError("synthetic rollback")
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Account)) == 0
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 0


def test_simultaneous_first_google_sign_ins_share_one_account(db) -> None:
    def sign_in(_index):
        with session_scope(db) as session:
            return login_google_account(session, claims())

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(sign_in, range(2)))
    assert all(result.ok for result in results)
    assert results[0].user_id == results[1].user_id
    with session_scope(db) as session:
        assert session.scalar(select(func.count()).select_from(Account)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1


def test_google_table_is_added_without_altering_existing_accounts(tmp_path) -> None:
    url = f"sqlite:///{(tmp_path / 'pre_google.db').as_posix()}"
    engine = get_engine(url)
    tables = [table for table in Base.metadata.sorted_tables if table.name != "external_identities"]
    Base.metadata.create_all(bind=engine, tables=tables)
    with session_scope(url) as session:
        previous = create_account(session, username="existing-student", password="saved-password")
        ctx = UserContext(user_id=previous.user_id)
        TwinRepository(session).save_twin(ctx, empty_twin("EXISTING_STUDENT_PRIVATE"))
    assert "external_identities" not in inspect(engine).get_table_names()
    init_db(url)
    with session_scope(url) as session:
        assert login_account(
            session, username="existing-student", password="saved-password"
        ).user_id == previous.user_id
        assert "EXISTING_STUDENT_PRIVATE" in str(TwinRepository(session).get_twin(ctx))
        assert login_google_account(session, claims()).user_id != previous.user_id
    reset_engine()


@pytest.fixture()
def google_ui(db, monkeypatch):
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    monkeypatch.setattr(st, "user", {"is_logged_in": False})
    monkeypatch.setattr("modules.google_auth.find_spec", lambda _name: object())
    return db


def new_app(*, configured: bool = True) -> AppTest:
    """Create an isolated app with mock AI, optionally enabling fake OAuth config."""
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    if configured:
        app.secrets.update(auth_secrets())
    app.session_state["ai_force_mock"] = True
    return app.run()


def test_unconfigured_google_button_does_not_break_password_login(google_ui) -> None:
    app = new_app(configured=False)
    assert not app.exception
    assert app.button(key="google_sign_in").disabled
    assert any(button.label == "Continue" for button in app.button)


def test_google_button_starts_native_named_provider(google_ui, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(st, "login", lambda provider: calls.append(provider))
    app = new_app()
    assert not app.button(key="google_sign_in").disabled
    app.button(key="google_sign_in").click().run()
    assert not app.exception
    assert calls == ["google"]


def test_google_start_errors_do_not_show_private_configuration(google_ui, monkeypatch) -> None:
    def failed(_provider):
        raise StreamlitAPIException("PRIVATE_OAUTH_CLIENT_SECRET")

    monkeypatch.setattr(st, "login", failed)
    app = new_app()
    app.button(key="google_sign_in").click().run()
    assert not app.exception
    assert any("could not start" in item.value for item in app.error)
    assert "PRIVATE_OAUTH_CLIENT_SECRET" not in str(app.error)


def test_google_cookie_restores_account_tour_and_replaces_previous_session(
    google_ui, monkeypatch,
) -> None:
    monkeypatch.setattr(st, "user", {"is_logged_in": True, **claims()})
    app = new_app()
    assert not app.exception
    first = UserContext(user_id=app.session_state["user_id"])
    assert load_tour_state(first) is not None
    with session_scope(google_ui) as session:
        TwinRepository(session).save_twin(first, empty_twin("PREVIOUS_GOOGLE_STUDENT_PRIVATE"))
    app.session_state["private_draft"] = "PREVIOUS_GOOGLE_STUDENT_PRIVATE"
    monkeypatch.setattr(st, "user", {"is_logged_in": True, **claims("synthetic-google-b")})
    app.run()
    assert not app.exception
    second = UserContext(user_id=app.session_state["user_id"])
    assert first != second
    assert "PREVIOUS_GOOGLE_STUDENT_PRIVATE" not in str(app.session_state)
    with session_scope(google_ui) as session:
        repo = TwinRepository(session)
        assert repo.get_twin(second) is None
        assert "PREVIOUS_GOOGLE_STUDENT_PRIVATE" in str(repo.get_twin(first))
    app = new_app()
    assert not app.exception
    assert app.session_state["user_id"] == second.user_id


def test_google_logout_clears_native_cookie_and_form_state(google_ui, monkeypatch) -> None:
    monkeypatch.setattr(st, "user", {"is_logged_in": True, **claims()})
    calls = []

    def logout():
        calls.append(True)
        monkeypatch.setattr(st, "user", {"is_logged_in": False})

    monkeypatch.setattr(st, "logout", logout)
    app = new_app()
    app.session_state["private_draft"] = "PRIVATE_GOOGLE_DRAFT"
    next(button for button in app.button if button.label == "Log out").click().run()
    assert not app.exception
    assert calls == [True]
    assert app.session_state["logged_in"] is False
    assert "user_id" not in app.session_state
    assert "PRIVATE_GOOGLE_DRAFT" not in str(app.session_state)
    app = new_app()
    assert app.button(key="google_sign_in")


def test_expired_cookie_cannot_access_the_previous_students_twin(google_ui, monkeypatch) -> None:
    monkeypatch.setattr(st, "user", {"is_logged_in": True, **claims()})
    app = new_app()
    previous_user_id = app.session_state["user_id"]
    app.session_state["private_draft"] = "PRIVATE_EXPIRED_GOOGLE_DRAFT"
    monkeypatch.setattr(st, "user", {"is_logged_in": True, **claims(exp=0)})
    app.run()
    assert not app.exception
    assert "user_id" not in app.session_state
    assert previous_user_id not in str(app.session_state)
    assert "PRIVATE_EXPIRED_GOOGLE_DRAFT" not in str(app.session_state)
    assert not app.tabs
    assert any("expired" in item.value for item in app.error)


def test_lost_google_cookie_clears_the_app_identity(google_ui) -> None:
    app = new_app()
    app.session_state["logged_in"] = True
    app.session_state["auth_provider"] = "google"
    app.session_state["user_id"] = "synthetic-previous-user"
    app.session_state["private_draft"] = "PRIVATE_GOOGLE_DRAFT"
    app.run()
    assert not app.exception
    assert "user_id" not in app.session_state
    assert "PRIVATE_GOOGLE_DRAFT" not in str(app.session_state)
    assert app.button(key="google_sign_in")


@pytest.mark.parametrize("field,value", [
    ("cookie_secret", "short"), ("client_secret", "replace-with-secret"),
    ("client_id", "not-a-google-client"),
    ("server_metadata_url", "https://untrusted.example.test/discovery"),
    ("redirect_uri", "http://public.example.test/oauth2callback"),
    ("redirect_uri", "https://example.test/incorrect-callback"),
])
def test_incomplete_or_unsafe_configuration_is_disabled(monkeypatch, field, value) -> None:
    settings = auth_secrets()
    section = (
        settings["auth"] if field in ("redirect_uri", "cookie_secret")
        else settings["auth"]["google"]
    )
    section[field] = value
    monkeypatch.setattr(st, "secrets", settings)
    assert not google_login_settings().available


def test_default_google_provider_and_missing_authlib_are_supported(monkeypatch) -> None:
    settings = auth_secrets()
    settings["auth"].update(settings["auth"].pop("google"))
    monkeypatch.setattr(st, "secrets", settings)
    monkeypatch.setattr("modules.google_auth.find_spec", lambda _name: object())
    assert google_login_settings().available
    assert google_login_settings().provider is None
    monkeypatch.setattr("modules.google_auth.find_spec", lambda _name: None)
    assert not google_login_settings().available
