"""Browserless Streamlit regression for enrollment, quiz, and CV evidence."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from storage.repository import TwinRepository
from storage.twin_schema import empty_twin


def test_course_quiz_form_and_offline_result(
    db, open_session, ctx_a, monkeypatch
) -> None:
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    monkeypatch.setattr("modules.market_research.TAVILY_API_KEY", "")
    with open_session() as session:
        twin = empty_twin("Quiz UI Student")
        twin["profile"].update(
            degree="Software Engineering", education_level="Undergraduate (Year 2)"
        )
        TwinRepository(session).save_twin(ctx_a, twin)

    def render() -> AppTest:
        app = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
        )
        app.session_state["logged_in"] = True
        app.session_state["user_id"] = ctx_a.user_id
        app.session_state["ai_force_mock"] = True
        app.run()
        assert not app.exception, [e.message for e in app.exception]
        return app

    app = render()
    next(f for f in app.text_input if f.label == "Chosen course / unit title").input(
        "Python Basics"
    )
    next(f for f in app.text_input if f.label == "Course link").input(
        "https://cs50.harvard.edu/python/"
    )
    next(b for b in app.button if b.label == "Add to my learning").click().run()
    assert not app.exception, [e.message for e in app.exception]
    app = render()
    next(
        f for f in app.text_area if f.label == "Completed units / what I learned"
    ).input("Completed variables, conditionals and loops.")
    next(
        b for b in app.button if b.label == "I completed the course - start assessment"
    ).click().run()
    assert not app.exception, [e.message for e in app.exception]
    app = render()
    questions = [r for r in app.radio if ". Practice " in r.label]
    assert len(questions) == 5
    for question in questions:
        question.set_value(1)
    next(
        b for b in app.button if b.label == "Submit assessment (80% to pass)"
    ).click().run()
    assert not app.exception, [e.message for e in app.exception]
    with open_session() as session:
        course = TwinRepository(session).get_twin(ctx_a)["learning_courses"][0]
        assert course["status"] == "practice_completed"
        assert course["attempts"][-1]["score"] == 100
    app = render()
    assert any("Offline practice score" in info.value for info in app.info)
    assert not app.exception


def test_semester_editor_uses_updated_profile_year(
    db, open_session, ctx_a, monkeypatch
) -> None:
    monkeypatch.setattr("storage.database.DATABASE_URL", db)
    with open_session() as session:
        twin = empty_twin("Year Transition Student")
        twin["profile"].update(degree="Law", education_level="Undergraduate (Year 2)")
        twin["academic"]["study_year"] = 1
        TwinRepository(session).save_twin(ctx_a, twin)
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    )
    app.session_state["logged_in"] = True
    app.session_state["user_id"] = ctx_a.user_id
    app.session_state["ai_force_mock"] = True
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    assert next(n for n in app.number_input if n.label == "Academic year").value == 2
