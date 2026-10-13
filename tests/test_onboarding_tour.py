"""First-account tour navigation, persistence and strict account isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from modules.onboarding_tour import (
    TOUR_STEPS, TourState, load_tour_state, save_tour_state,
)
from storage.context import UserContext
from storage.repository import TwinRepository


@pytest.fixture()
def tour_database(db, monkeypatch):
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    return db


def new_app() -> AppTest:
    """Create a fresh browser session using only mock AI."""
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    app.session_state["ai_force_mock"] = True
    return app.run()


def sign_in(app: AppTest, username: str, *, create: bool = False) -> AppTest:
    """Exercise the actual authentication UI with synthetic credentials."""
    next(item for item in app.radio if item.label == "I want to").set_value(
        "Create account" if create else "Log in"
    ).run()
    next(item for item in app.text_input if item.label == "Username").set_value(username)
    next(item for item in app.text_input if item.label == "Password").set_value(
        "synthetic-tour-password"
    )
    next(item for item in app.button if item.label == "Continue").click().run()
    assert not app.exception, [item.message for item in app.exception]
    # A fresh tree avoids AppTest retaining widgets from the removed auth screen.
    authenticated = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    authenticated.session_state["logged_in"] = True
    authenticated.session_state["user_id"] = app.session_state["user_id"]
    authenticated.session_state["ai_force_mock"] = True
    return authenticated.run()


def app_context(app: AppTest) -> UserContext:
    """Read only the authenticated identity, never another session's data."""
    return UserContext(user_id=app.session_state["user_id"], session_id="tour-test")


def test_account_creation_starts_tour_and_resumes_after_login(tour_database) -> None:
    app = sign_in(new_app(), "tour-first-student", create=True)
    ctx = app_context(app)
    assert load_tour_state(ctx) == TourState()
    assert app.button(key="tour_back").disabled
    assert any("Start with your studies" in item.value for item in app.markdown)
    app.button(key="tour_next").click().run()
    assert load_tour_state(ctx) == TourState(step=1)
    app.button(key="tour_next").click().run()
    app.button(key="tour_back").click().run()
    assert load_tour_state(ctx) == TourState(step=1)
    next(item for item in app.button if item.label == "Log out").click().run()
    assert app.session_state["logged_in"] is False
    app = sign_in(new_app(), "tour-first-student")
    assert load_tour_state(app_context(app)) == TourState(step=1)
    assert any("Establish your academic baseline" in item.value for item in app.markdown)
    assert not app.exception


def test_skipping_is_remembered_but_quick_tour_can_restart(tour_database) -> None:
    app = sign_in(new_app(), "tour-skip-student", create=True)
    ctx = app_context(app)
    app.button(key="tour_skip").click().run()
    assert load_tour_state(ctx).status == "skipped"
    assert "tour_next" not in [button.key for button in app.button]
    assert app.session_state["workspace_tab"] == "Profile"
    app = sign_in(new_app(), "tour-skip-student")
    assert "tour_next" not in [button.key for button in app.button]
    app.button(key="tour_restart").click().run()
    assert load_tour_state(ctx) == TourState()
    assert not app.exception


def test_completion_is_remembered_without_changing_academic_progress(
    tour_database, open_session,
) -> None:
    app = sign_in(new_app(), "tour-complete-student", create=True)
    ctx = app_context(app)
    for index in range(len(TOUR_STEPS) - 1):
        app.button(key="tour_next").click().run()
        assert load_tour_state(ctx).step == index + 1
        assert not app.exception
    app.button(key="tour_finish").click().run()
    assert load_tour_state(ctx).status == "completed"
    assert app.session_state["workspace_tab"] == "Profile"
    with open_session() as session:
        repo = TwinRepository(session)
        assert repo.get_twin(ctx) is None
        assert repo.list_snapshots(ctx) == []
        assert repo.list_ai_cache_keys(ctx) == []
    app = sign_in(new_app(), "tour-complete-student")
    assert "tour_next" not in [button.key for button in app.button]
    assert not app.exception


def test_second_account_does_not_inherit_the_first_accounts_tour(tour_database) -> None:
    app = sign_in(new_app(), "tour-account-a", create=True)
    first = app_context(app)
    app.button(key="tour_skip").click().run()
    next(item for item in app.button if item.label == "Log out").click().run()
    app = sign_in(app, "tour-account-b", create=True)
    second = app_context(app)
    assert first.user_id != second.user_id
    assert load_tour_state(first).status == "skipped"
    assert load_tour_state(second) == TourState()
    assert app.session_state["workspace_tab"] == "Profile"
    app.button(key="tour_next").click().run()
    assert load_tour_state(first).status == "skipped"
    assert load_tour_state(second) == TourState(step=1)


def test_demo_tour_is_optional(tour_database) -> None:
    app = new_app()
    next(item for item in app.button if item.label == "Demo student A (SE)").click().run()
    ctx = app_context(app)
    assert load_tour_state(ctx) is None
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    app.session_state["logged_in"] = True
    app.session_state["user_id"] = ctx.user_id
    app.session_state["ai_force_mock"] = True
    app.run()
    app.button(key="tour_restart").click().run()
    assert load_tour_state(ctx) == TourState()
    assert not app.exception


def test_tour_records_are_scoped_to_the_explicit_user(tour_database, ctx_a, ctx_b) -> None:
    save_tour_state(ctx_a, 3)
    assert load_tour_state(ctx_a) == TourState(step=3)
    assert load_tour_state(ctx_b) is None
    save_tour_state(ctx_b, 1, "skipped")
    assert load_tour_state(ctx_a) == TourState(step=3)
    assert load_tour_state(ctx_b) == TourState(step=1, status="skipped")


@pytest.mark.parametrize("step", [-1, len(TOUR_STEPS), 1.5, True])
def test_invalid_step_cannot_be_saved(tour_database, ctx_a, step) -> None:
    with pytest.raises(ValueError, match="Invalid tour step"):
        save_tour_state(ctx_a, step)
    assert load_tour_state(ctx_a) is None


def test_invalid_status_cannot_be_saved(tour_database, ctx_a) -> None:
    with pytest.raises(ValueError, match="Invalid tour status"):
        save_tour_state(ctx_a, 0, "not-a-tour-status")
    assert load_tour_state(ctx_a) is None
