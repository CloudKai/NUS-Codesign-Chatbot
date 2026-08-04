"""Reusable presentation helpers for the Streamlit UI."""

from __future__ import annotations

from html import escape

# Re-export so existing imports of toast helpers keep working.
from ui.toasts import DEFAULT_TOAST_DURATION_MS, show_corner_toasts

__all__ = [
    "DEFAULT_TOAST_DURATION_MS",
    "empty_state_html",
    "notification_dot_html",
    "profile_initial",
    "progress_bar_html",
    "review_card_html",
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
