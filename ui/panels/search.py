"""Center-pane chat search (Gemini-style).

Ranks chats with typo-tolerant fuzzy matching on titles and recent text.
Clicking a result opens that chat; there is no separate Open control.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import streamlit as st

from ui.notebooks import thread_overview
from ui.runtime import store
from ui.session import notebook_switch_locked, select_thread

_FUZZY_THRESHOLD = 0.42


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
        catalog = store.list_threads("", None)
        threads = _rank_threads(catalog, needle) if needle else catalog

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


def _rank_threads(threads: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    """Return threads ordered by fuzzy score against ``needle``."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for thread in threads:
        score = _thread_fuzzy_score(thread, needle)
        if score >= _FUZZY_THRESHOLD:
            scored.append((score, thread))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [thread for _, thread in scored]


def _thread_fuzzy_score(thread: dict[str, Any], needle: str) -> float:
    """Score one chat against the search query (title weighted highest)."""
    title = str(thread.get("name") or "").strip()
    latest = str(thread.get("latestUserMessage") or "").strip()
    overview = thread_overview(thread)
    summary = str(overview.get("summary") or "").strip()
    title_score = _fuzzy_score(needle, title)
    body_score = max(_fuzzy_score(needle, latest), _fuzzy_score(needle, summary))
    return max(title_score, body_score * 0.92, (title_score * 0.65 + body_score * 0.35))


def _fuzzy_score(needle: str, text: str) -> float:
    """Return a 0..1 fuzzy similarity, boosting contiguous / substring hits."""
    query = " ".join(str(needle or "").lower().split())
    haystack = " ".join(str(text or "").lower().split())
    if not query:
        return 1.0
    if not haystack:
        return 0.0
    if query == haystack:
        return 1.0
    if query in haystack:
        return min(0.99, 0.88 + (len(query) / max(len(haystack), 1)) * 0.1)

    full = SequenceMatcher(None, query, haystack).ratio()
    partial = 0.0
    # Sliding windows catch transposed / near-miss titles longer than the query.
    window = max(len(query) + 4, len(query) * 2)
    if len(haystack) > len(query):
        step = max(1, len(query) // 2)
        for start in range(0, len(haystack) - len(query) + 1, step):
            chunk = haystack[start : start + window]
            partial = max(partial, SequenceMatcher(None, query, chunk).ratio())
    else:
        partial = SequenceMatcher(None, query, haystack).ratio()

    token_scores: list[float] = []
    for token in query.split():
        if len(token) < 2:
            continue
        if token in haystack:
            token_scores.append(1.0)
            continue
        best = 0.0
        for word in haystack.split():
            best = max(best, SequenceMatcher(None, token, word).ratio())
        token_scores.append(best)
    token_avg = sum(token_scores) / len(token_scores) if token_scores else 0.0
    return max(full, partial, token_avg)


def _render_result_row(
    thread: dict[str, Any],
    *,
    needle: str,
    locked: bool,
) -> None:
    """One search / recent row; the whole row opens the chat."""
    thread_id = str(thread.get("id") or "")
    if not thread_id:
        return
    title = str(thread.get("name") or "Untitled notebook").strip() or "Untitled notebook"
    overview = thread_overview(thread)
    when = str(overview.get("last_active") or "").strip() or "Unknown"
    snippet = _match_snippet(thread, needle) if needle else ""
    active_id = str(st.session_state.get("thread_id") or "")
    is_active = thread_id == active_id
    open_disabled = locked and not is_active

    label_lines = [title]
    if snippet:
        label_lines.append(snippet)
    label_lines.append(when)
    label = "\n".join(label_lines)

    with st.container(key=f"search_row_{thread_id.replace('-', '_')}"):
        if st.button(
            label,
            key=f"search-open-{thread_id}",
            use_container_width=True,
            type="primary" if is_active else "tertiary",
            disabled=open_disabled,
            help="Wait for the coach reply" if open_disabled else "Open chat",
        ):
            st.session_state.center_view = "chat"
            select_thread(thread_id)


def _match_snippet(thread: dict[str, Any], needle: str) -> str:
    """Return a short content snippet near the best fuzzy match when possible."""
    query = str(needle or "").strip()
    if not query:
        return ""
    latest = str(thread.get("latestUserMessage") or "").strip()
    overview = thread_overview(thread)
    summary = str(overview.get("summary") or "").strip()
    candidates = [field for field in (latest, summary) if field]
    if not candidates:
        return ""
    best_text = max(candidates, key=lambda text: _fuzzy_score(query, text))
    if _fuzzy_score(query, best_text) < _FUZZY_THRESHOLD:
        return ""
    return _trim_around_fuzzy(best_text, query)


def _trim_around_fuzzy(text: str, query: str, *, radius: int = 48) -> str:
    """Clip ``text`` around the best fuzzy alignment with ``query``."""
    lowered = text.lower()
    q = query.lower()
    index = lowered.find(q)
    if index < 0:
        matcher = SequenceMatcher(None, q, lowered)
        block = max(
            matcher.get_matching_blocks(),
            key=lambda item: item.size,
            default=None,
        )
        if block is None or block.size <= 0:
            return " ".join(text.split())[:120]
        index = block.b
        span = max(block.size, len(q))
    else:
        span = len(q)
    start = max(0, index - radius)
    end = min(len(text), index + span + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet
