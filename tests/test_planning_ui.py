"""Streamlit tests for onboarding, roadmap adoption, and progress persistence."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage.repository import TwinRepository


def test_onboarding_analysis_roadmap_and_check_in(
    db, open_session, ctx_a, monkeypatch
) -> None:
    import storage.database as database
    import modules.market_research as market

    monkeypatch.setattr(database, "DATABASE_URL", db)
    monkeypatch.setattr(market, "TAVILY_API_KEY", "")
    app_path = Path(__file__).resolve().parents[1] / "app.py"

    def render() -> AppTest:
        app = AppTest.from_file(str(app_path), default_timeout=30)
        app.session_state["logged_in"] = True
        app.session_state["user_id"] = ctx_a.user_id
        app.session_state["ai_force_mock"] = True
        app.run()
        assert not app.exception, [error.message for error in app.exception]
        return app

    app = render()
    next(
        field for field in app.selectbox if field.label == "Subject choice 1"
    ).set_value("Other").run()
    inputs = {field.label: field for field in app.text_input}
    inputs["Full name"].input("Nursing UI Student")
    inputs["Program / Degree / Track"].input("BSc Nursing")
    inputs["Your city"].input("Karachi")
    inputs["Country"].input("Pakistan")
    inputs["Career goals (comma-separated)"].input("Nursing")
    inputs["Subject 1"].input("Anatomy")
    inputs["Grade 1"].input("82")
    next(field for field in app.selectbox if field.label == "Field of study").set_value(
        "Health & Medicine"
    )
    next(
        button for button in app.button if button.label == "Save twin & analyze"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    with open_session() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx_a)
        assert twin["profile"]["city"] == "Karachi"
        assert twin["profile"]["field_of_study"] == "Health & Medicine"
        assert repo.list_artifacts(ctx_a, kind="career_plan")

    app = render()
    next(
        field for field in app.multiselect if field.label == "I have earned / completed"
    ).select(0)
    next(
        field for field in app.multiselect if field.label == "I want to earn / learn"
    ).select(0)
    next(
        button for button in app.button if button.label == "Save my choices"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    with open_session() as session:
        assert TwinRepository(session).get_twin(ctx_a)["goals"]

    app = render()
    next(
        button
        for button in app.button
        if button.label == "Analyze / refresh career plan"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    app = render()
    next(
        button for button in app.button if button.label == "Use this roadmap"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    with open_session() as session:
        assert TwinRepository(session).get_twin(ctx_a)["active_plan"]["schedule"]

    app = render()
    next(
        field
        for field in app.text_area
        if field.label == "Completion note / evidence link"
    ).input("Completed the exercises and saved my notes.")
    next(
        button for button in app.button if button.label == "Record completion"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    with open_session() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx_a)
        assert len(twin["progress_events"]) == 1
        assert len(repo.list_snapshots(ctx_a)) >= 3

    app = render()
    next(
        button
        for button in app.button
        if button.label == "Analyze / refresh career plan"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    with open_session() as session:
        plan = TwinRepository(session).list_artifacts(ctx_a, kind="career_plan")[0][
            "payload"
        ]
        assert "1 completed milestones" in plan["analysis"]["progress_summary"]

    app = render()
    next(field for field in app.text_input if field.label == "My question").input(
        "What progress have I made?"
    )
    next(button for button in app.button if button.label == "Ask coach").click().run()
    assert not app.exception, [error.message for error in app.exception]
    with open_session() as session:
        history = TwinRepository(session).get_chat_history(ctx_a)
        assert len(history) == 2
        assert "1 recorded milestones" in history[-1]["content"]

    app = render()
    next(
        button for button in app.sidebar.button if button.label == "Log out"
    ).click().run()
    assert not app.exception, [error.message for error in app.exception]
    assert app.session_state["logged_in"] is False
    assert "user_id" not in app.session_state
    assert "Nursing UI Student" not in str(app.session_state)
