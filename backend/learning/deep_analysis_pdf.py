"""Build a student-facing Deep Analysis PDF from a Sonnet Deep Review snapshot.

Uses PyMuPDF (already in production requirements). No model call — Sonnet
content must already be persisted on the notebook snapshot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import fitz

from backend.learning.stages import STAGE_BY_ID, THINKING_STAGES
from backend.persistence.object_keys import sanitize_filename

_FACIONE_LABELS: tuple[tuple[str, str], ...] = (
    ("analysis", "Analysis"),
    ("interpretation", "Interpretation"),
    ("inference", "Inference"),
    ("evaluation", "Evaluation"),
    ("explanation", "Explanation"),
    ("self_regulation", "Self-Regulation"),
)
_PAGE_WIDTH = 595.0
_PAGE_HEIGHT = 842.0
_MARGIN = 54.0


@dataclass(frozen=True)
class DeepAnalysisPdfExport:
    """Binary Deep Analysis PDF ready for download."""

    data: bytes
    filename: str
    mime: str = "application/pdf"


class _PdfWriter:
    """Minimal multi-page text writer for the Deep Analysis export."""

    def __init__(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        self.y = _MARGIN
        self.width = _PAGE_WIDTH - 2 * _MARGIN

    def ensure_space(self, needed: float = 48.0) -> None:
        """Start a new page when the remaining vertical space is too small."""
        if self.y <= _PAGE_HEIGHT - _MARGIN - needed:
            return
        self.page = self.doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
        self.y = _MARGIN

    def write(
        self,
        text: str,
        *,
        fontsize: float = 10,
        bold: bool = False,
        gap_after: float = 0,
    ) -> None:
        """Insert wrapped text at the current cursor."""
        cleaned = _clean(text)
        if not cleaned:
            return
        self.ensure_space(fontsize * 3)
        face = "hebo" if bold else "helv"
        bottom = _PAGE_HEIGHT - _MARGIN
        rect = fitz.Rect(_MARGIN, self.y, _MARGIN + self.width, bottom)
        overflow = self.page.insert_textbox(
            rect,
            cleaned,
            fontsize=fontsize,
            fontname=face,
            color=(0.1, 0.12, 0.16),
            align=fitz.TEXT_ALIGN_LEFT,
        )
        used = max(fontsize + 4, rect.height - max(0.0, overflow))
        self.y += used + gap_after

    def section(self, title: str) -> None:
        """Write a section heading with spacing."""
        self.ensure_space(64)
        self.write(title, fontsize=12, bold=True, gap_after=2)

    def bullet(self, text: str) -> None:
        """Write one bullet line."""
        self.write(f"• {text}", fontsize=10)

    def bytes(self) -> bytes:
        """Return PDF bytes and close the document."""
        payload = self.doc.tobytes()
        self.doc.close()
        return payload


def deep_analysis_pdf_filename(title: str) -> str:
    """Return a safe ``.pdf`` filename for one notebook title."""
    stem = sanitize_filename(str(title or "").strip() or "Untitled notebook")
    stem = re.sub(r"\.pdf$", "", stem, flags=re.IGNORECASE)
    return f"{stem}-deep-analysis.pdf"


def build_deep_analysis_pdf(
    *,
    title: str,
    snapshot: Mapping[str, Any],
    journey: Mapping[str, Any] | None = None,
) -> DeepAnalysisPdfExport:
    """Render one Deep Analysis PDF from a durable Deep Review snapshot.

    Args:
        title: Notebook title used in the heading and filename.
        snapshot: Persisted ``deep_review_snapshot`` mapping from Sonnet.
        journey: Optional learning-journey metadata for completed-stage labels.

    Returns:
        PDF bytes and download filename.

    Raises:
        ValueError: When ``snapshot`` is empty or missing useful review text.
    """
    if not isinstance(snapshot, Mapping) or not snapshot:
        raise ValueError("Deep Analysis snapshot is missing")
    summary = _clean(snapshot.get("summary") or snapshot.get("synthesis"))
    conclusion = _clean(snapshot.get("working_conclusion"))
    strengths = _clean_list(snapshot.get("strengths"))
    areas = _clean_list(
        snapshot.get("areas_to_develop") or snapshot.get("areas_to_revisit")
    )
    if not (summary or conclusion or strengths or areas):
        raise ValueError("Deep Analysis snapshot has no content to export")

    notebook_title = str(title or "").strip() or "Untitled notebook"
    created = _clean(snapshot.get("created_at")) or datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")
    model_id = _clean(snapshot.get("model_id")) or "Sonnet"
    completed: list[str] = []
    if isinstance(journey, Mapping):
        for stage_id in journey.get("completed_stages") or []:
            stage = STAGE_BY_ID.get(str(stage_id or "").strip())
            if stage is not None:
                completed.append(stage.label)

    writer = _PdfWriter()
    writer.write("Deep Analysis", fontsize=18, bold=True, gap_after=4)
    writer.write(notebook_title, fontsize=12, bold=True, gap_after=2)
    writer.write(
        f"Generated {created} · Model: {model_id}",
        fontsize=9,
        gap_after=10,
    )

    if completed:
        writer.section("Thinking Path completed")
        writer.write(", ".join(completed), fontsize=10, gap_after=8)

    if summary:
        writer.section("Summary")
        writer.write(summary, fontsize=10, gap_after=8)

    if conclusion:
        writer.section("Working conclusion")
        writer.write(conclusion, fontsize=10, gap_after=8)

    if strengths:
        writer.section("Strengths")
        for item in strengths:
            writer.bullet(item)
        writer.y += 6

    if areas:
        writer.section("Areas to improve")
        for item in areas:
            writer.bullet(item)
        writer.y += 6

    facione = snapshot.get("facione_scores")
    if isinstance(facione, Mapping) and facione:
        writer.section("Critical thinking profile")
        lines: list[str] = []
        for key, label in _FACIONE_LABELS:
            if key not in facione:
                continue
            try:
                score = int(facione.get(key) or 0)
            except (TypeError, ValueError):
                score = 0
            lines.append(f"{label}: {score}/4")
        if lines:
            writer.write("  ·  ".join(lines), fontsize=10, gap_after=8)

    stage_reviews = snapshot.get("stage_reviews")
    if isinstance(stage_reviews, list) and stage_reviews:
        writer.section("Stage reviews")
        by_id = {
            str(item.get("stage") or item.get("stage_id") or "").strip(): item
            for item in stage_reviews
            if isinstance(item, Mapping)
        }
        for stage in THINKING_STAGES:
            row = by_id.get(stage.id)
            if not isinstance(row, Mapping):
                continue
            stage_strengths = _clean_list(row.get("strengths"))
            stage_areas = _clean_list(
                row.get("areas_to_revisit") or row.get("areas_to_develop")
            )
            stage_summary = _clean(row.get("summary"))
            if not (stage_strengths or stage_areas or stage_summary):
                continue
            writer.write(stage.label, fontsize=11, bold=True, gap_after=2)
            if stage_summary:
                writer.write(stage_summary, fontsize=10)
            for item in stage_strengths:
                writer.bullet(f"Strength: {item}")
            for item in stage_areas:
                writer.bullet(f"Improve: {item}")
            writer.y += 4

    return DeepAnalysisPdfExport(
        data=writer.bytes(),
        filename=deep_analysis_pdf_filename(notebook_title),
    )


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        cleaned = _clean(raw)
        if cleaned:
            items.append(cleaned)
    return items
