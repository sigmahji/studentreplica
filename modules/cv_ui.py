"""Interactive fact-only CV preview and user-scoped document downloads."""

from __future__ import annotations

import base64
from html import escape

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


def render_professional_cv_preview(
    twin: dict, facts: list[dict], photo: bytes | None = None
) -> None:
    """Render an executive paper sheet preview with layout graphics, badges and evidence."""
    profile = twin.get("profile", {})
    name = escape(str(profile.get("name") or "Student"))
    degree = escape(str(profile.get("degree") or ""))
    institution = escape(str(profile.get("institution") or ""))
    city = escape(str(profile.get("city") or ""))
    country = escape(str(profile.get("country") or ""))
    grad = escape(str(profile.get("graduation_date") or ""))

    pills_html: list[str] = []
    if city or country:
        loc = ", ".join(filter(None, [city, country]))
        pills_html.append(f'<span class="cv-header-pill">📍 {loc}</span>')
    if degree:
        pills_html.append(f'<span class="cv-header-pill">🎓 {degree}</span>')
    if institution:
        pills_html.append(f'<span class="cv-header-pill">🏛️ {institution}</span>')
    if grad:
        pills_html.append(f'<span class="cv-header-pill">📅 Class of {grad}</span>')

    photo_html = ""
    if photo:
        b64_img = base64.b64encode(photo).decode("ascii")
        photo_html = (
            f'<div class="cv-photo-badge">'
            f'<img src="data:image/jpeg;base64,{b64_img}" alt="Portrait">'
            f'</div>'
        )

    sections_html: list[str] = []
    for section in dict.fromkeys(f["section"] for f in facts):
        sec_facts = [f for f in facts if f["section"] == section]
        if not sec_facts:
            continue
        icon = {
            "Education": "🎓",
            "Assessed Learning": "✅",
            "Skills": "⚡",
            "Projects": "🚀",
            "Achievements": "🏆",
            "Relevant Coursework": "📚",
        }.get(section, "📌")

        items_html: list[str] = []
        for fact in sec_facts:
            text = escape(fact["text"])
            extra_badge = ""
            if "100%" in text or "formative assessment" in text:
                extra_badge = '<span class="cv-score-pill">Verified Score</span>'
            link_html = ""
            if fact.get("url"):
                link_html = (
                    f'<a class="cv-evidence-link" href="{escape(fact["url"])}" '
                    f'target="_blank" rel="noopener">Evidence ↗</a>'
                )
            items_html.append(
                f'<div class="cv-fact-row">'
                f'<span class="cv-fact-bullet">•</span>'
                f'<div class="cv-fact-body">{text}{extra_badge}{link_html}</div>'
                f'</div>'
            )
        sections_html.append(
            f'<div class="cv-section-block">'
            f'<div class="cv-section-heading"><span>{icon}</span> {escape(section)}</div>'
            f'{"".join(items_html)}'
            f'</div>'
        )

    subtitle_html = f'<div class="cv-header-subtitle">{degree}</div>' if degree else ""
    pills_row = "".join(pills_html)
    sections_body = "".join(sections_html)

    sheet_html = (
        f'<div class="cv-preview-container">'
        f'<div class="cv-header-row">'
        f'<div class="cv-header-info">'
        f'<div class="cv-header-name">{name}</div>'
        f'{subtitle_html}'
        f'<div class="cv-header-pills">{pills_row}</div>'
        f'</div>'
        f'{photo_html}'
        f'</div>'
        f'<div class="cv-divider"></div>'
        f'{sections_body}'
        f'</div>'
    )
    st.markdown(sheet_html, unsafe_allow_html=True)


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

    # Professional graphical CV sheet preview
    photo_bytes = photo if (photo and use_photo) else None
    render_professional_cv_preview(twin, visible, photo_bytes)

    with st.expander("Raw markdown view"):
        st.markdown(cv_markdown(twin, visible))

    if visible:
        col1, col2 = st.columns(2)
        col1.download_button(
            "Download PDF",
            export_pdf(twin, visible, photo_bytes),
            "student_cv.pdf",
            "application/pdf",
            icon=":material/picture_as_pdf:",
            type="primary",
            width="stretch",
        )
        col2.download_button(
            "Download DOCX",
            export_docx(twin, visible, photo_bytes),
            "student_cv.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            icon=":material/description:",
            width="stretch",
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
