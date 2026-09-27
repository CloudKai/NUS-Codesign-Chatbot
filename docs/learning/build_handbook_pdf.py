"""Render the learning handbook chapters into one readable PDF.

This is a deliberately small Markdown renderer for this repository's teaching
documents. It handles the prose, headings, lists, tables, fenced code, and
Mermaid source blocks used in chapters 01-08 plus CODEBASE_STRUCTURE.md. It
does not execute Markdown, diagram, or application code.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEARNING_DIR = Path(__file__).resolve().parent
OUTPUT = PROJECT_ROOT / "output/pdf/co-design-chatbot-learning-handbook.pdf"
SOURCES = [
    *(LEARNING_DIR / f"{number:02d}-{name}.md" for number, name in (
        (1, "system-and-services"),
        (2, "frontend-api-and-turns"),
        (3, "rag-and-context"),
        (4, "database-and-idempotency"),
        (5, "agentcore-and-workflow"),
        (6, "without-aws-and-langgraph"),
        (7, "scaling-and-tradeoffs"),
        (8, "interview-and-study"),
    )),
    PROJECT_ROOT / "docs/CODEBASE_STRUCTURE.md",
]


def styles() -> dict[str, ParagraphStyle]:
    """Return the document's compact visual language."""
    sample = getSampleStyleSheet()
    body = ParagraphStyle(
        "Body",
        parent=sample["BodyText"],
        fontName="Helvetica",
        fontSize=9.3,
        leading=13.2,
        spaceAfter=7,
        textColor=colors.HexColor("#1E293B"),
    )
    return {
        "title": ParagraphStyle(
            "Title",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=27,
            leading=33,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#0F766E"),
            spaceAfter=16,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=body,
            fontSize=12,
            leading=17,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#475569"),
            spaceAfter=18,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=sample["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=24,
            textColor=colors.HexColor("#0F766E"),
            spaceBefore=14,
            spaceAfter=10,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13.5,
            leading=17,
            textColor=colors.HexColor("#155E75"),
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=11.2,
            leading=14,
            textColor=colors.HexColor("#334155"),
            spaceBefore=9,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "body": body,
        "bullet": ParagraphStyle(
            "Bullet",
            parent=body,
            leftIndent=14,
            firstLineIndent=-9,
            bulletIndent=0,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=body,
            fontName="Courier",
            fontSize=7.1,
            leading=9.2,
            backColor=colors.HexColor("#F1F5F9"),
            borderColor=colors.HexColor("#CBD5E1"),
            borderWidth=0.5,
            borderPadding=6,
            spaceBefore=3,
            spaceAfter=9,
        ),
        "caption": ParagraphStyle(
            "Caption",
            parent=body,
            fontName="Helvetica-Oblique",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=4,
        ),
        "table": ParagraphStyle(
            "Table",
            parent=body,
            fontSize=7.4,
            leading=9.3,
            spaceAfter=0,
        ),
        "table_head": ParagraphStyle(
            "TableHead",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=7.4,
            leading=9.3,
            textColor=colors.white,
            spaceAfter=0,
        ),
    }


def clean_text(value: str) -> str:
    """Turn Markdown inline styling into reportlab-safe paragraph markup."""
    value = value.strip()
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", value)
    value = escape(value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", value)
    return value.replace("---", "-").replace("--", "-")


def table_from_lines(lines: list[str], st: dict[str, ParagraphStyle]) -> Table:
    """Create a styled PDF table from a simple pipe-delimited Markdown table."""
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    columns = max(len(row) for row in rows)
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    rendered = []
    for row_index, row in enumerate(normalized):
        rendered.append([
            Paragraph(clean_text(cell), st["table_head"] if row_index == 0 else st["table"])
            for cell in row
        ])
    width = A4[0] - 3.2 * cm
    column_widths = [width / columns] * columns
    table = Table(rendered, colWidths=column_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#155E75")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def render_markdown(path: Path, st: dict[str, ParagraphStyle]) -> list[object]:
    """Render supported Markdown blocks from one source file."""
    story: list[object] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            story.append(Paragraph(clean_text(" ".join(paragraph)), st["body"]))
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            flush_paragraph()
            language = line[3:].strip().lower()
            index += 1
            block: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index].replace("\t", "    "))
                index += 1
            if language == "mermaid":
                story.append(Paragraph("Diagram source (Mermaid)", st["caption"]))
            elif language:
                story.append(Paragraph(f"Code example ({language})", st["caption"]))
            story.append(Preformatted("\n".join(block), st["code"]))
        elif line.startswith("|") and index + 1 < len(lines) and lines[index + 1].startswith("|"):
            flush_paragraph()
            table_lines = [line]
            index += 1
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            story.append(table_from_lines(table_lines, st))
            story.append(Spacer(1, 8))
            continue
        elif line.startswith("# "):
            flush_paragraph()
            story.append(Paragraph(clean_text(line[2:]), st["h1"]))
            story.append(HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#99F6E4"), spaceAfter=8))
        elif line.startswith("## "):
            flush_paragraph()
            story.append(Paragraph(clean_text(line[3:]), st["h2"]))
        elif line.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(clean_text(line[4:]), st["h3"]))
        elif re.match(r"^[-*] ", line):
            flush_paragraph()
            story.append(Paragraph(clean_text(line[2:]), st["bullet"], bulletText="•"))
        elif re.match(r"^\d+\. ", line):
            flush_paragraph()
            marker, content = line.split(". ", 1)
            story.append(Paragraph(clean_text(content), st["bullet"], bulletText=f"{marker}."))
        elif line.strip() == "---":
            flush_paragraph()
            story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#CBD5E1"), spaceBefore=6, spaceAfter=8))
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line.strip())
        index += 1
    flush_paragraph()
    return story


def page_number(canvas, document) -> None:
    """Draw a minimal running header and footer on every content page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(1.6 * cm, A4[1] - 1.0 * cm, "Co-design Chatbot - Learning Handbook")
    canvas.drawRightString(A4[0] - 1.6 * cm, 0.9 * cm, f"Page {document.page}")
    canvas.restoreState()


def build() -> None:
    """Create the handbook PDF from the selected Markdown sources."""
    missing = [str(path) for path in SOURCES if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing handbook sources: {missing}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    st = styles()
    document = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.5 * cm, bottomMargin=1.45 * cm,
        title="Co-design Chatbot Learning Handbook",
        author="Co-design Chatbot project",
    )
    story: list[object] = [
        Spacer(1, 4.5 * cm),
        Paragraph("Co-design Chatbot", st["title"]),
        Paragraph("Learning Handbook", st["title"]),
        Paragraph(
            "A guided explanation of the frontend, backend, RAG, database, AgentCore, LangGraph, scaling, and interview-ready design decisions.",
            st["subtitle"],
        ),
        Spacer(1, 0.8 * cm),
        Paragraph("Source set: learning chapters 01-08 and CODEBASE_STRUCTURE.md", st["subtitle"]),
        Spacer(1, 2.8 * cm),
        Paragraph("Generated from the local repository Markdown sources.", st["caption"]),
        PageBreak(),
        Paragraph("Reader's guide", st["h1"]),
        Paragraph(
            "Read chapters 1-2 for the end-to-end system. Chapters 3-5 explain retrieval, persistence, and generation. Chapters 6-8 explore non-AWS alternatives, scaling, and interview preparation. The final appendix maps the repository codebase.",
            st["body"],
        ),
        Paragraph("Included sections", st["h2"]),
    ]
    for source in SOURCES:
        label = source.stem.replace("-", " ") if source.name != "CODEBASE_STRUCTURE.md" else "Codebase structure appendix"
        story.append(Paragraph(clean_text(label), st["bullet"], bulletText="•"))
    story.append(PageBreak())
    for source_index, source in enumerate(SOURCES):
        if source.name == "CODEBASE_STRUCTURE.md":
            story.append(Paragraph("Appendix: Codebase Structure", st["h1"]))
        story.extend(render_markdown(source, st))
        if source_index < len(SOURCES) - 1:
            story.append(PageBreak())
    document.build(story, onFirstPage=page_number, onLaterPages=page_number)


if __name__ == "__main__":
    build()
    print(OUTPUT)
