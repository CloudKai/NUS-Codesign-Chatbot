"""Center-pane chat search (Gemini-style).

Uses existing case-insensitive substring ``store.list_threads(query)`` matching
on notebook titles and message text. Does not use typo-tolerant matching.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

import streamlit as st

from ui.notebooks import thread_overview
from ui.runtime import store
from ui.session import notebook_switch_locked, select_thread


def render_search_panel() -> None:
    """Render the centered Search chats pane."""
    with st.container(key="search_panel"):
        st.markdown(
            '<div class="cd-search-shell">'
            '<div class="cd-search-heading">Search chats</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        query = st.text_input(
            "Search chats",
            placeholder="Search chats",
            label_visibility="collapsed",
            key="chat-search-query",
        )
        needle = str(query or "").strip()
        locked = notebook_switch_locked()
        threads = store.list_threads(needle, None)

        if needle:
            st.markdown(
                '<div class="cd-search-section-label">Results</div>',
                unsafe_allow_html=True,
            )
            if not threads:
                st.markdown(
                    '<div class="cd-search-empty">No results found</div>',
                    unsafe_allow_html=True,
                )
                return
        else:
            st.markdown(
                '<div class="cd-search-section-label">Recent</div>',
                unsafe_allow_html=True,
            )
            if not threads:
                st.caption("No chats yet.")
                return

        with st.container(key="search_results_scroll", height="stretch"):
            for thread in threads:
                _render_result_row(thread, needle=needle, locked=locked)


def _render_result_row(
    thread: dict[str, Any],
    *,
    needle: str,
    locked: bool,
) -> None:
    """One search / recent row with optional match highlight."""
    thread_id = str(thread.get("id") or "")
    if not thread_id:
        return
    title = str(thread.get("name") or "Untitled notebook").strip() or "Untitled notebook"
    overview = thread_overview(thread)
    when = str(overview.get("last_active") or "").strip() or "Unknown"
    snippet = ""
    if needle:
        snippet = _match_snippet(thread, needle)
    title_html = _highlight(title, needle) if needle else escape(title)
    snippet_html = _highlight(snippet, needle) if snippet else ""
    active_id = str(st.session_state.get("thread_id") or "")
    is_active = thread_id == active_id
    open_disabled = locked and not is_active

    with st.container(key=f"search_row_{thread_id.replace('-', '_')}"):
        meta = escape(when)
        body = (
            f'<div class="cd-search-row-copy">'
            f'<div class="cd-search-row-title">{title_html}</div>'
        )
        if snippet_html:
            body += f'<div class="cd-search-row-snippet">{snippet_html}</div>'
        body += f'<div class="cd-search-row-meta">{meta}</div></div>'
        st.markdown(body, unsafe_allow_html=True)
        if st.button(
            "Open",
            key=f"search-open-{thread_id}",
            use_container_width=True,
            type="secondary",
            disabled=open_disabled,
            help="Wait for the coach reply" if open_disabled else None,
        ):
            st.session_state.center_view = "chat"
            select_thread(thread_id)


def _highlight(text: str, needle: str) -> str:
    """Escape text and wrap case-insensitive substring matches in ``<mark>``."""
    cleaned = str(text or "")
    query = str(needle or "").strip()
    if not query:
        return escape(cleaned)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    parts: list[str] = []
    last = 0
    for match in pattern.finditer(cleaned):
        parts.append(escape(cleaned[last : match.start()]))
        parts.append(f"<mark>{escape(match.group(0))}</mark>")
        last = match.end()
    parts.append(escape(cleaned[last:]))
    return "".join(parts)


def _match_snippet(thread: dict[str, Any], needle: str) -> str:
    """Return a short content snippet that contains the query when possible."""
    query = str(needle or "").strip().lower()
    if not query:
        return ""
    latest = str(thread.get("latestUserMessage") or "").strip()
    if query in latest.lower():
        return _trim_around(latest, query)
    overview = thread_overview(thread)
    summary = str(overview.get("summary") or "").strip()
    if query in summary.lower():
        return _trim_around(summary, query)
    return ""


def _trim_around(text: str, query: str, *, radius: int = 48) -> str:
    """Clip ``text`` around the first case-insensitive ``query`` hit."""
    lowered = text.lower()
    index = lowered.find(query.lower())
    if index < 0:
        return " ".join(text.split())[:120]
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
