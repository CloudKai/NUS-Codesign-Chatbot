"""Reusable presentation helpers for the Streamlit UI."""

from __future__ import annotations

from html import escape

from typing import Any

# Re-export so existing imports of toast helpers keep working.
from ui.toasts import DEFAULT_TOAST_DURATION_MS, show_corner_toasts

__all__ = [
    "DEFAULT_TOAST_DURATION_MS",
    "empty_state_html",
    "facione_scores_table_html",
    "notification_dot_html",
    "profile_initial",
    "progress_bar_html",
    "review_card_html",
    "review_feedback_items_html",
    "review_stage_sections_html",
    "show_corner_toasts",
]


def progress_bar_html(
    *,
    completed: int,
    total: int = 6,
    label: str = "Progress",
    heading: str | None = None,
) -> str:
    """Return a calm progress indicator for the thinking path."""
    safe_total = max(total, 1)
    ratio = max(0, min(completed, safe_total)) / safe_total
    percent = int(round(ratio * 100))
    heading_html = (
        f'<div class="cd-progress-heading">{escape(heading)}</div>'
        if heading
        else ""
    )
    return (
        '<div class="cd-progress" role="group" '
        f'aria-label="{escape(label)}">'
        f"{heading_html}"
        '<div class="cd-progress-meta">'
        f"<span>{completed} of {safe_total}</span>"
        "</div>"
        '<div class="cd-progress-track" role="progressbar" '
        f'aria-valuemin="0" aria-valuemax="{safe_total}" '
        f'aria-valuenow="{completed}" aria-label="{escape(label)}">'
        f'<div class="cd-progress-fill" style="width:{percent}%"></div>'
        "</div></div>"
    )


def empty_state_html(*, title: str, body: str) -> str:
    """Return a quiet empty-state block for panels and dialogs."""
    body_html = "<br>".join(
        escape(line.strip()) for line in body.splitlines() if line.strip()
    )
    return (
        '<div class="cd-empty-state">'
        f"<strong>{escape(title)}</strong>"
        f"<span>{body_html}</span>"
        "</div>"
    )


def review_card_html(*, label: str, body: str, items: list[str] | None = None) -> str:
    """Return a compact review insight card."""
    if items:
        list_html = "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"
        content = list_html
    else:
        content = escape(body)
    return (
        '<section class="cd-card">'
        f'<div class="cd-card-label">{escape(label)}</div>'
        f'<div class="cd-card-body">{content}</div>'
        "</section>"
    )


def review_feedback_items_html(
    items: list[Any] | None,
    *,
    empty_label: str = "No feedback yet",
) -> str:
    """Return bullet list HTML for one stage's Strengths or Areas feedback.

    Empty stages stay quiet with a short placeholder so history remains
    scannable without filler coaching tips.
    """
    cleaned = [
        " ".join(str(item).split()).strip()
        for item in (items or [])
        if str(item).strip()
    ]
    if not cleaned:
        return f'<p class="review-empty">{escape(empty_label)}</p>'
    return (
        '<div class="review-stage-body"><ul>'
        + "".join(f"<li>{escape(item)}</li>" for item in cleaned)
        + "</ul></div>"
    )


def review_stage_sections_html(
    *,
    sections: list[dict[str, Any]] | None,
    empty_label: str = "No feedback yet",
) -> str:
    """Return compact stage-grouped feedback HTML (legacy flat layout).

    Prefer nested Streamlit stage expanders in the Review tab. This helper
    remains for callers that need a single HTML block.
    """
    rows: list[str] = []
    for section in sections or []:
        stage = str(section.get("stage") or "").strip() or "Stage"
        body = review_feedback_items_html(
            section.get("items"),
            empty_label=empty_label,
        )
        rows.append(
            '<div class="review-stage-block">'
            f'<div class="review-stage-label">{escape(stage)}</div>'
            f"{body}"
            "</div>"
        )
    if not rows:
        return f'<p class="review-empty">{escape(empty_label)}</p>'
    return '<div class="review-stage-list">' + "".join(rows) + "</div>"


_FACIONE_ICONS: dict[int, tuple[str, str]] = {
    0: ("radio_button_unchecked", "Not started"),
    1: ("sentiment_very_dissatisfied", "Weak"),
    2: ("sentiment_dissatisfied", "Unacceptable"),
    3: ("sentiment_satisfied", "Acceptable"),
    4: ("sentiment_very_satisfied", "Strong"),
}

_FACIONE_ROWS: tuple[tuple[str, str], ...] = (
    ("analysis", "Analysis"),
    ("interpretation", "Interpretation"),
    ("inference", "Inference"),
    ("evaluation", "Evaluation"),
    ("explanation", "Explanation"),
    ("self_regulation", "Self-Regulation"),
)


def facione_scores_table_html(scores: dict[str, int] | None) -> str:
    """Return a Facione dimension table with one rubric icon per row.

    Scores use ``0`` not started through ``4`` Strong. Missing keys render as
    not started so legacy assessments stay readable.
    """
    source = scores or {}
    rows: list[str] = []
    for key, label in _FACIONE_ROWS:
        try:
            value = int(source.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        value = max(0, min(4, value))
        icon, rubric = _FACIONE_ICONS[value]
        aria = f"{label}: {rubric}"
        rows.append(
            "<tr>"
            f'<th scope="row">{escape(label)}</th>'
            f'<td class="facione-score facione-score-{value}">'
            '<span class="facione-score-content">'
            f'<span class="material-symbols-rounded" role="img" '
            f'title="{escape(aria)}" aria-label="{escape(aria)}">'
            f"{escape(icon)}</span>"
            f'<span class="facione-rubric">{escape(rubric)}</span>'
            "</span>"
            "</td>"
            "</tr>"
        )
    return (
        '<section class="cd-card facione-card">'
        '<div class="cd-card-label">Critical thinking (Facione)</div>'
        '<div class="cd-card-body">'
        '<table class="facione-table">'
        "<thead><tr><th scope=\"col\">Dimension</th>"
        "<th scope=\"col\">Score</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div></section>"
    )


def notification_dot_html(*, visible: bool) -> str:
    """Return a small change indicator for navigation labels."""
    if not visible:
        return ""
    return '<span class="cd-nav-dot" aria-label="New review updates"></span>'


def profile_initial(name: str) -> str:
    """Return avatar initials: one letter per name, up to two characters."""
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        return "S"
    parts = cleaned.split()
    initials = "".join(part[:1] for part in parts[:2] if part)
    return initials.upper() or "S"
