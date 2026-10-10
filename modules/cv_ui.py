"""Interactive fact-only CV preview and user-scoped document downloads."""

from __future__ import annotations

import base64

import streamlit as st

from ai.service import AIService, RateLimitExceeded
from modules.cv_exports import (
    cv_facts,
    cv_markdown,
    export_docx,
    export_pdf,
    sanitize_photo,
)
from storage.context import UserContext
from storage.database import session_scope
from storage.repository import TwinRepository


def render_cv_studio(ctx: UserContext, ai: AIService, job: dict | None) -> None:
    """Render a configurable preview; photos never enter AI prompts or shared files."""
    st.markdown("### CV Studio")
    with session_scope() as session:
        repo = TwinRepository(session)
        twin = repo.get_twin(ctx)
        selections = repo.list_artifacts(ctx, kind="cv_selection")
        photos = repo.list_artifacts(ctx, kind="cv_photo")
        letters = repo.list_artifacts(ctx, kind="cv_content")
    if not twin:
        st.info("Save your profile first.")
        return
    target = st.text_input(
        "CV target role",
        value=job["title"] if job else twin["profile"].get("degree", ""),
        max_chars=200,
    )
    if st.button("Tailor CV with AI", type="primary"):
        try:
            with st.spinner(
                "Selecting your relevant education, skills and achievements..."
            ):
                with session_scope() as session:
                    ai.generate_cv_content(
                        session,
                        ctx,
                        {
                            "title": target,
                            "required_skills": (job or {}).get("required_skills", []),
                        },
                    )
            st.rerun()
        except RateLimitExceeded:
            st.warning("Please wait a minute before tailoring again.")
    selection = selections[0]["payload"] if selections else None
    if selection and selection["twin_version"] == twin.get("meta", {}).get(
        "twin_version"
    ):
        facts = selection["facts"]
        with st.expander("Why this CV selection?"):
            st.write(selection["rationale"])
            st.caption(f"Confidence: {selection.get('confidence', 0.5):.0%}")
            st.caption(
                "Offline fact ordering"
                if selection["offline_mode"]
                else "AI-selected facts; verify important details"
            )
    else:
        facts = cv_facts(twin)
        if selection:
            st.info(
                "Your twin has changed. The preview uses current facts; tailor again for the updated target."
            )
    photo = (
        base64.b64decode(photos[0]["payload"]["jpeg_base64"])
        if photos and photos[0]["payload"].get("jpeg_base64")
        else None
    )
    with st.expander("CV photo (optional)"):
        upload = st.file_uploader(
            "Portrait", type=["jpg", "jpeg", "png"], key=f"cv_upload_{ctx.user_id}"
        )
        if upload and st.button("Save CV photo"):
            try:
                safe = sanitize_photo(upload.getvalue())
                with session_scope() as session:
                    TwinRepository(session).save_artifact(
                        ctx,
                        "cv_photo",
                        {"jpeg_base64": base64.b64encode(safe).decode("ascii")},
                    )
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        use_photo = st.checkbox(
            "Include my photo", value=bool(photo), disabled=photo is None
        )
        if photo and st.button("Remove CV photo"):
            with session_scope() as session:
                TwinRepository(session).delete_artifacts(ctx, kind="cv_photo")
            st.rerun()
    sections = list(dict.fromkeys(f["section"] for f in facts))
    included = st.multiselect(
        "CV sections",
        sections,
        default=sections,
        key=f"cv_sections_{ctx.user_id}_{twin['meta']['twin_version']}_{len(facts)}",
    )
    visible = [f for section in included for f in facts if f["section"] == section]
    selected_indices = st.multiselect(
        "Included facts",
        range(len(visible)),
        default=list(range(len(visible))),
        format_func=lambda i: visible[i]["text"],
        key=f"cv_facts_{ctx.user_id}_{twin['meta']['twin_version']}_{'|'.join(included)}_{len(facts)}",
    )
    visible = [visible[i] for i in selected_indices]
    with st.container(border=True):
        if photo and use_photo:
            st.image(photo, width=100)
        st.markdown(cv_markdown(twin, visible))
    if visible:
        photo_bytes = photo if use_photo else None
        col1, col2 = st.columns(2)
        col1.download_button(
            "Download PDF",
            export_pdf(twin, visible, photo_bytes),
            "student_cv.pdf",
            "application/pdf",
        )
        col2.download_button(
            "Download DOCX",
            export_docx(twin, visible, photo_bytes),
            "student_cv.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    if letters:
        with st.expander("Cover letter"):
            content = letters[0]["payload"]
            st.caption(
                f"Confidence: {content.get('confidence', 0):.0%} | {content.get('notice', '')}"
            )
            st.markdown(content["cover_letter_markdown"])
            st.download_button(
                "Download cover letter",
                content["cover_letter_markdown"],
                "cover_letter.md",
                "text/markdown",
            )
            if content.get("missing_information"):
                st.warning(
                    "Missing information: " + ", ".join(content["missing_information"])
                )
