"""Fact-only CV rendering with optional sanitized photos and real document exports."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def cv_facts(twin: dict[str, Any]) -> list[dict[str, str]]:
    """Create an allowlist that AI can order but never embellish."""
    profile = twin.get("profile", {})
    facts = []

    def add(section: str, text: str, url: str = "") -> None:
        if text.strip():
            facts.append(
                {
                    "id": f"fact_{len(facts) + 1}",
                    "section": section,
                    "text": text.strip(),
                    "url": url if url.startswith("https://") else "",
                }
            )

    add(
        "Education",
        " | ".join(
            str(profile.get(k) or "")
            for k in ("degree", "institution", "education_level")
            if profile.get(k)
        ),
    )
    if profile.get("graduation_date"):
        add("Education", f"Expected completion: {profile['graduation_date']}")
    for skill in twin.get("skills", []):
        evidence = str(skill.get("evidence", ""))
        label = (
            "Formative assessment evidence"
            if "formative assessment" in evidence
            else "Reported learning"
        )
        add("Skills", f"{skill['name']} - {label}")
    for project in twin.get("projects", []):
        add(
            "Projects",
            (
                " - ".join(
                    str(project.get(k) or "")
                    for k in ("name", "description", "evidence")
                    if project.get(k)
                )
                if isinstance(project, dict)
                else str(project)
            ),
        )
    for course in twin.get("learning_courses", []):
        if course.get("status") == "passed" and not course.get("assessment_offline"):
            attempts = [
                a
                for a in course.get("attempts", [])
                if a.get("passed") and not a.get("practice_only")
            ]
            if attempts:
                add(
                    "Assessed Learning",
                    f"{course['title']} - {course['skill']} | StudentReplica formative assessment {attempts[-1]['score']:g}% | {course.get('passed_at', '')[:10]} | Not an accredited certificate",
                    course.get("url", ""),
                )
    for achievement in twin.get("achievements", []):
        add("Achievements", f"{achievement} (student-reported)")
    for course in twin.get("academic", {}).get("courses", []):
        if course.get("grade") not in (None, ""):
            prefix = (
                f"Semester {course['semester']}: " if course.get("semester") else ""
            )
            add(
                "Relevant Coursework",
                f"{prefix}{course['name']} | Reported grade: {course['grade']}",
            )
    return facts[:80]


def select_facts(facts: list[dict[str, str]], ids: list[str]) -> list[dict[str, str]]:
    """Reject unknown IDs; keep education and passed learning visible by default."""
    by_id = {f["id"]: f for f in facts}
    ordered = list(dict.fromkeys(ids))
    selected = [by_id[i] for i in ordered if i in by_id]
    essential = [
        f
        for f in facts
        if f["section"] in ("Education", "Assessed Learning") and f["id"] not in ordered
    ]
    return essential + selected if selected else facts


def cv_markdown(twin: dict, facts: list[dict]) -> str:
    """Render only literal student facts, with clickable course evidence links."""
    profile = twin.get("profile", {})
    lines = [f"# {profile.get('name') or 'Student'}"]
    location = ", ".join(
        str(profile.get(k) or "") for k in ("city", "country") if profile.get(k)
    )
    if location:
        lines += [location]
    for section in dict.fromkeys(f["section"] for f in facts):
        lines += ["", f"## {section}"]
        for fact in facts:
            if fact["section"] == section:
                lines.append(
                    f"- {fact['text']}"
                    + (f" [Course evidence]({fact['url']})" if fact.get("url") else "")
                )
    return "\n".join(lines)


def sanitize_photo(raw: bytes) -> bytes:
    """Bound image size, remove metadata and normalize the upload before storage."""
    from PIL import Image, ImageOps

    if len(raw) > 3_000_000:
        raise ValueError("Choose a photo under 3 MB.")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Photo dimensions are too large.")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((600, 600))
            output = BytesIO()
            image.save(output, format="JPEG", quality=85)
            return output.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Choose a valid JPG or PNG photo.") from exc


def export_docx(twin: dict, facts: list[dict], photo: bytes | None = None) -> bytes:
    """Build an editable, ATS-readable Word document without invented claims."""
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE

    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.65)
    section.left_margin = section.right_margin = Inches(0.75)
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10)
    normal.paragraph_format.space_after = Pt(6)
    if photo:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT

        header = document.add_table(rows=1, cols=2)
        header.autofit = False
        header.columns[0].width, header.columns[1].width = Inches(5.5), Inches(1)
        title = header.cell(0, 0).paragraphs[0]
        title.style = "Title"
        title.add_run(twin["profile"].get("name") or "Student")
        portrait = header.cell(0, 1).paragraphs[0]
        portrait.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        portrait.add_run().add_picture(BytesIO(photo), width=Inches(0.85))
        for cell in header.rows[0].cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
    else:
        title = document.add_paragraph(
            twin["profile"].get("name") or "Student", "Title"
        )
    title.runs[0].font.color.rgb = RGBColor(0, 0, 0)
    title.runs[0].font.size = Pt(26)
    profile = twin["profile"]
    document.add_paragraph(
        ", ".join(
            str(profile.get(k) or "") for k in ("city", "country") if profile.get(k)
        )
    )
    for heading in dict.fromkeys(f["section"] for f in facts):
        paragraph = document.add_paragraph(heading, "Heading 1")
        paragraph.runs[0].font.size = Pt(12)
        paragraph.runs[0].font.color.rgb = RGBColor.from_string("117367")
        for fact in (f for f in facts if f["section"] == heading):
            paragraph = document.add_paragraph(fact["text"], "List Bullet")
            if fact.get("url"):
                paragraph.add_run(" ")
                link = OxmlElement("w:hyperlink")
                link.set(
                    qn("r:id"),
                    paragraph.part.relate_to(
                        fact["url"], RELATIONSHIP_TYPE.HYPERLINK, is_external=True
                    ),
                )
                run, text = OxmlElement("w:r"), OxmlElement("w:t")
                text.text = "Course evidence"
                run.append(text)
                link.append(run)
                paragraph._p.append(link)
    # Word templates may inherit a title rule; keep this CV free of theme borders.
    for root in (document.element, document.styles.element):
        for border in list(root.iter(qn("w:pBdr"))):
            border.getparent().remove(border)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def export_pdf(twin: dict, facts: list[dict], photo: bytes | None = None) -> bytes:
    """Render a paginated CV with wrapping, section hierarchy and clickable links."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font = "Helvetica"
    for path in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if path.exists():
            font = "TwinCV"
            if font not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font, str(path)))
            break
    body = ParagraphStyle(
        "Body",
        fontName=font,
        fontSize=10,
        leading=14,
        spaceAfter=6,
        splitLongWords=True,
    )
    heading = ParagraphStyle(
        "Section",
        parent=body,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#117367"),
        spaceBefore=14,
        spaceAfter=7,
        keepWithNext=True,
    )
    title = ParagraphStyle("Name", parent=body, fontSize=25, leading=30, spaceAfter=8)
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=42,
        bottomMargin=42,
        title="Curriculum Vitae",
        author="",
    )
    name = Paragraph(escape(twin["profile"].get("name") or "Student"), title)
    story = []
    if photo:
        image = Image(BytesIO(photo))
        ratio = min(62 / image.imageWidth, 72 / image.imageHeight)
        image.drawWidth, image.drawHeight = (
            image.imageWidth * ratio,
            image.imageHeight * ratio,
        )
        table = Table([[name, image]], colWidths=[document.width - 80, 80])
        table.setStyle(
            [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]
        )
        story.append(table)
    else:
        story.append(name)
    profile = twin["profile"]
    story.append(
        Paragraph(
            escape(
                ", ".join(
                    str(profile.get(k) or "")
                    for k in ("city", "country")
                    if profile.get(k)
                )
            ),
            body,
        )
    )
    story.append(Spacer(1, 4))
    for section in dict.fromkeys(f["section"] for f in facts):
        story.append(Paragraph(escape(section), heading))
        for fact in (f for f in facts if f["section"] == section):
            text = escape(fact["text"])
            if fact.get("url"):
                text += f' <link href="{escape(fact["url"], {chr(34): "&quot;"})}" color="#117367">Course evidence</link>'
            story.append(Paragraph(text, body, bulletText="-"))
    document.build(story)
    return output.getvalue()
