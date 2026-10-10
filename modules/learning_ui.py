"""Course discovery, assessment attempts, and achievement feedback."""

from __future__ import annotations

import logging

import streamlit as st

from ai.service import AIService, RateLimitExceeded
from modules.academics import learning_options
from modules.learning import course_resources, enroll_course
from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository
from modules.ui import render_bullets


def render_learning(ctx: UserContext, ai: AIService) -> None:
    """Render private course records and hide answer keys until an attempt ends."""
    st.markdown("### Learning & Assessments")
    with session_scope() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx)
        assessments = repo.list_artifacts(ctx, kind="course_assessment")
        plans = repo.list_artifacts(ctx, kind="career_plan")
    if not twin:
        st.info("Save your profile first.")
        return
    budgets = ["Free only", "Free and paid"]
    budget = st.radio(
        "Course budget",
        budgets,
        index=budgets.index(
            twin.get("learning_preferences", {}).get("course_budget", "Free only")
        ),
        horizontal=True,
    )
    options = learning_options(twin)
    ai_targets = plans[0]["payload"]["analysis"]["target_options"] if plans else []
    recommended = {o["name"].casefold(): o["rationale"] for o in ai_targets}
    labels = list(
        dict.fromkeys(
            [o["name"] for o in options]
            + [o["name"] for o in ai_targets]
            + [g["name"] for g in twin.get("goals", [])]
        )
    )
    skill = st.selectbox(
        "Skill / academic concept to learn",
        labels + ["Other"],
        format_func=lambda s: f"Recommended: {s}" if s.casefold() in recommended else s,
    )
    if skill == "Other":
        skill = st.text_input("Custom learning skill", max_chars=150)
    option = next((o for o in options if o["name"] == skill), {})
    if skill.casefold() in recommended:
        st.info(recommended[skill.casefold()])
    if option.get("foundations_first"):
        st.warning("Foundations first: " + ", ".join(option["foundations_first"]))
    elif option:
        st.caption(option["rationale"])
    if skill:
        for resource in course_resources(skill, budget):
            st.link_button(
                f"{resource['title']} | {resource['cost']} | {resource['type']}",
                resource["url"],
            )
        if st.button("Ask AI to teach this concept"):
            try:
                with st.spinner(
                    "Preparing a short lesson around your current knowledge..."
                ):
                    with session_scope() as session:
                        reply = ai.coach_chat(
                            session,
                            ctx,
                            f"Teach me {skill}. Use my degree and academic weaknesses to identify prerequisites first. Give a concise explanation, one worked classroom example and one practice exercise. Respect my current coursework and available time. Do not claim I have mastered it.",
                        )
                        TwinRepository(session).save_artifact(
                            ctx,
                            "learning_lesson",
                            {"skill": skill, "reply": reply.model_dump(mode="json")},
                        )
                st.write(reply.reply)
                st.caption(f"Confidence: {reply.confidence:.0%} | {reply.notice}")
                with st.expander("Why this lesson?"):
                    render_bullets(reply.evidence_used)
            except RateLimitExceeded:
                st.warning("Please wait a minute and try again.")
        with st.form("enroll_learning_course"):
            title = st.text_input("Chosen course / unit title", max_chars=200)
            url = st.text_input("Course link", max_chars=2000)
            enrolled = st.form_submit_button("Add to my learning")
        if enrolled:
            try:
                with session_scope() as session:
                    repo = TwinRepository(session)
                    updated = enroll_course(repo.get_twin(ctx), skill, title, url)
                    updated.setdefault("learning_preferences", {})[
                        "course_budget"
                    ] = budget
                    repo.save_twin(ctx, updated, label="course_started")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.markdown("#### My learning")
    if not twin.get("learning_courses"):
        st.info("No courses added yet.")
    for course in twin.get("learning_courses", []):
        with st.expander(
            f"{course['title']} | {course['status'].replace('_', ' ').title()}"
        ):
            st.write(course["skill"])
            st.link_button("Course provider", course["url"])
            if course.get("prerequisites_to_review"):
                st.caption(
                    "Review first: " + ", ".join(course["prerequisites_to_review"])
                )
            if course.get("attempts"):
                result = course["attempts"][-1]
                if result["practice_only"]:
                    st.info(
                        f"Offline practice score: {result['score']:g}%. Reconnect AI for an assessed attempt."
                    )
                elif result["passed"]:
                    st.success(
                        f"Congratulations! You passed with {result['score']:g}%. Your learning evidence is now in your twin and CV."
                    )
                else:
                    st.warning(
                        f"Score: {result['score']:g}%. Passing: 80%. Review these concepts: {', '.join(result['weak_concepts'])}"
                    )
                st.markdown("**Assessment feedback**")
                for explanation in result["explanations"]:
                    st.write(explanation)
            if course.get("weak_concepts") and st.button(
                "Ask AI for revision guidance", key=f"revise_{course['id']}"
            ):
                try:
                    with session_scope() as session:
                        reply = ai.coach_chat(
                            session,
                            ctx,
                            f"Help me revise {course['skill']} after my formative quiz. My weak concepts are: {', '.join(course['weak_concepts'])}. Explain each, give a worked example and a practice task; do not reveal a future quiz answer key or claim accreditation.",
                        )
                    st.write(reply.reply)
                    st.caption(f"Confidence: {reply.confidence:.0%} | {reply.notice}")
                    st.caption("Based on: " + ", ".join(reply.evidence_used))
                except RateLimitExceeded:
                    st.warning("Please wait a minute and try again.")
            if course["status"] == "passed":
                continue
            artifact = next(
                (a for a in assessments if a["id"] == course.get("assessment_id")), None
            )
            if course["status"] == "quiz_ready" and artifact:
                quiz = artifact["payload"]["quiz"]
                st.write(quiz["preparation"])
                st.caption(f"Confidence: {quiz['confidence']:.0%} | {quiz['notice']}")
                st.caption("Based on: " + ", ".join(quiz["evidence_used"]))
                answers = []
                with st.form(f"quiz_{artifact['id']}"):
                    for i, question in enumerate(quiz["questions"]):
                        answer = st.radio(
                            f"{i + 1}. {question['question']}",
                            range(4),
                            index=None,
                            format_func=lambda n, q=question: q["options"][n],
                            key=f"answer_{ctx.user_id}_{artifact['id']}_{i}",
                        )
                        answers.append(answer)
                    submitted = st.form_submit_button("Submit assessment (80% to pass)")
                if submitted:
                    try:
                        with session_scope() as session:
                            ai.submit_course_assessment(
                                session, ctx, artifact["id"], answers
                            )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                with st.form(f"complete_{course['id']}"):
                    note = st.text_area(
                        "Completed units / what I learned",
                        value=course.get("completion_note", ""),
                        max_chars=2000,
                    )
                    ready = st.form_submit_button(
                        "I completed the course - start assessment"
                    )
                if ready:
                    try:
                        with st.spinner(
                            "Preparing a quiz for your course and learning needs..."
                        ):
                            with session_scope() as session:
                                ai.generate_course_assessment(
                                    session, ctx, course["id"], note
                                )
                        st.rerun()
                    except (ValueError, RateLimitExceeded) as exc:
                        st.warning(str(exc))
                    except Exception as exc:
                        logging.getLogger("student_twin.ui").warning(
                            "event=quiz_unavailable user_id=%s err=%s",
                            ctx.user_id,
                            type(exc).__name__,
                        )
                        st.warning(
                            "Assessment temporarily unavailable. Your course is saved."
                        )
