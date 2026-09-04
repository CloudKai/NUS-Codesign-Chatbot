"""Professor-facing learning analytics rendered solely from the FastAPI client."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from backend.source_library import COURSE_MATERIAL_GROUPS
from backend.student_journey import THINKING_STAGES, normalize_journey
from ui.auth_gate import app_logout_url, logout_user
from ui.coach_welcome import render_hmw_scaffold
from ui.components import (
    facione_scores_table_html,
    review_card_html,
    review_stage_sections_html,
)
from ui.constants import PRODUCT_SUBTITLE, PRODUCT_TITLE
from ui.runtime import local_api_client

_PAGES = ("Overview", "Students", "Learning", "Engagement", "Research")
_PHASE_LABELS = tuple(stage.label.title() for stage in THINKING_STAGES)
_WORKSPACE_TABS = ("Chat", "Sources", "Progression", "Review")
_ROSTER_CACHE_KEY = "professor_roster_cache"
_DETAIL_CACHE_KEY = "professor_student_detail_cache"
_CHAT_CACHE_KEY = "professor_chat_cache"
_SOURCES_CACHE_KEY = "professor_sources_cache"
_JOURNEY_CACHE_KEY = "professor_journey_cache"
_REVIEW_CACHE_KEY = "professor_review_cache"


_PAGE_META: dict[str, dict[str, str]] = {
    "Overview": {
        "eyebrow": "Class snapshot",
        "title": "Overview",
        "description": "A concise view of participation, thinking stage, and follow-up signals.",
    },
    "Students": {
        "eyebrow": "Student work",
        "title": "Students",
        "description": "Open a student record to inspect notebooks and read-only learning evidence.",
    },
    "Learning": {
        "eyebrow": "Learning signals",
        "title": "Learning",
        "description": "Descriptive critical-thinking patterns across the latest assessed responses.",
    },
    "Engagement": {
        "eyebrow": "Activity",
        "title": "Engagement",
        "description": "Usage patterns that help staff understand where support may be useful.",
    },
    "Research": {
        "eyebrow": "Research workbench",
        "title": "Research Review",
        "description": "Review immutable automated observations against student utterances, then record independent human validation.",
    },
}


def _roster_cache_key(search: str, stage: str | None, attention_only: bool) -> tuple[str, str, bool]:
    """Return a stable cache key for one roster filter tuple."""
    return (search.strip().lower(), str(stage or "").strip().lower(), bool(attention_only))


def _cached_professor_students(
    client: Any,
    *,
    search: str,
    stage: str | None,
    attention_only: bool,
) -> dict[str, Any]:
    """Fetch or reuse the lightweight roster for the active filter set."""
    cache = st.session_state.setdefault(_ROSTER_CACHE_KEY, {})
    key = _roster_cache_key(search, stage, attention_only)
    if key not in cache:
        cache[key] = client.professor_students(
            search=search,
            stage=stage,
            attention_only=attention_only,
        )
    return cache[key]


def _cached_professor_student_detail(client: Any, student_id: str) -> dict[str, Any]:
    """Fetch or reuse one student's detail payload."""
    cache = st.session_state.setdefault(_DETAIL_CACHE_KEY, {})
    if student_id not in cache:
        cache[student_id] = client.professor_student_detail(student_id)
    return cache[student_id]


def _cached_professor_chat(
    client: Any, student_id: str, notebook_id: str, *, refresh: bool = False
) -> dict[str, Any]:
    """Fetch or reuse one notebook chat page (newest messages only)."""
    cache = st.session_state.setdefault(_CHAT_CACHE_KEY, {})
    key = (student_id, notebook_id)
    if refresh or key not in cache:
        cache[key] = client.professor_notebook_messages(student_id, notebook_id)
    return cache[key]


def _cached_professor_sources(
    client: Any, student_id: str, notebook_id: str, *, refresh: bool = False
) -> dict[str, Any]:
    """Fetch or reuse one notebook sources list."""
    cache = st.session_state.setdefault(_SOURCES_CACHE_KEY, {})
    key = (student_id, notebook_id)
    if refresh or key not in cache:
        cache[key] = client.professor_notebook_sources(student_id, notebook_id)
    return cache[key]


def _cached_professor_journey(
    client: Any, student_id: str, notebook_id: str, *, refresh: bool = False
) -> dict[str, Any]:
    """Fetch or reuse one notebook journey projection."""
    cache = st.session_state.setdefault(_JOURNEY_CACHE_KEY, {})
    key = (student_id, notebook_id)
    if refresh or key not in cache:
        cache[key] = client.professor_notebook_journey(student_id, notebook_id)
    return cache[key]


def _cached_professor_review(
    client: Any, student_id: str, notebook_id: str, *, refresh: bool = False
) -> dict[str, Any]:
    """Fetch or reuse one notebook review projection."""
    cache = st.session_state.setdefault(_REVIEW_CACHE_KEY, {})
    key = (student_id, notebook_id)
    if refresh or key not in cache:
        cache[key] = client.professor_notebook_review(student_id, notebook_id)
    return cache[key]


def _clear_notebook_tab_caches(student_id: str, notebook_id: str | None = None) -> None:
    """Drop cached notebook tab payloads for one student."""
    for cache_key in (
        _CHAT_CACHE_KEY,
        _SOURCES_CACHE_KEY,
        _JOURNEY_CACHE_KEY,
        _REVIEW_CACHE_KEY,
    ):
        cache = st.session_state.get(cache_key) or {}
        if notebook_id is None:
            for key in list(cache):
                if key[0] == student_id:
                    cache.pop(key, None)
        else:
            cache.pop((student_id, notebook_id), None)


def _invalidate_student_detail_cache(student_id: str) -> None:
    """Drop one student's cached detail and notebook tab payloads."""
    detail_cache = st.session_state.get(_DETAIL_CACHE_KEY) or {}
    detail_cache.pop(student_id, None)
    _clear_notebook_tab_caches(student_id)


def _invalidate_chat_cache(student_id: str, notebook_id: str) -> None:
    """Drop one notebook chat cache entry."""
    cache = st.session_state.get(_CHAT_CACHE_KEY) or {}
    cache.pop((student_id, notebook_id), None)


def _invalidate_sources_cache(student_id: str, notebook_id: str) -> None:
    """Drop one notebook sources cache entry."""
    cache = st.session_state.get(_SOURCES_CACHE_KEY) or {}
    cache.pop((student_id, notebook_id), None)


def _invalidate_journey_cache(student_id: str, notebook_id: str) -> None:
    """Drop one notebook journey cache entry."""
    cache = st.session_state.get(_JOURNEY_CACHE_KEY) or {}
    cache.pop((student_id, notebook_id), None)


def _invalidate_review_cache(student_id: str, notebook_id: str) -> None:
    """Drop one notebook review cache entry."""
    cache = st.session_state.get(_REVIEW_CACHE_KEY) or {}
    cache.pop((student_id, notebook_id), None)


def _format_file_size(size: int | float | None) -> str:
    """Render a compact human-readable byte size."""
    value = max(0, int(size or 0))
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def _file_type_label(mime: str | None, *, kind: str | None = None) -> str:
    """Return a short file-type label for attachment/source rows."""
    normalized = str(mime or "").split(";", 1)[0].strip().lower()
    if normalized == "application/pdf" or kind == "pdf":
        return "PDF"
    if normalized.startswith("image/"):
        return "Image"
    if normalized.startswith("text/"):
        return "Text"
    if normalized:
        return normalized.split("/")[-1].upper()
    return "File"


def _file_icon(mime: str | None, *, kind: str | None = None) -> str:
    """Return a compact icon for one file row."""
    label = _file_type_label(mime, kind=kind)
    if label == "PDF":
        return "📄"
    if label == "Image":
        return "🖼️"
    if label == "Text":
        return "📝"
    return "📎"


def _score(value: Any) -> str:
    """Render a nullable Facione value without fabricating a zero score."""
    return "Not assessed" if value is None else f"{float(value):.1f} / 4"


def _notebook_card_label(item: dict[str, Any]) -> str:
    """Render a compact notebook card title for the lecturer roster."""
    return str(item.get("title") or "Untitled notebook")


def _notebook_row_caption(item: dict[str, Any]) -> str:
    """Render compact notebook list metadata."""
    student_messages = int(item.get("student_messages") or 0)
    coach_messages = int(item.get("coach_messages") or item.get("assistant_messages") or 0)
    return (
        f"{item.get('stage') or item.get('current_stage') or 'Not started'} · "
        f"{student_messages} student · {coach_messages} coach · "
        f"{_when(item.get('last_active'))}"
    )


def _student_row_caption(row: dict[str, Any]) -> str:
    """Render compact roster metadata beneath the student name."""
    parts = [str(row.get("current_stage") or "Not started")]
    if row.get("last_active"):
        parts.append(_when(row.get("last_active")))
    parts.append(f"{int(row.get('student_messages') or 0)} messages")
    attention = row.get("needs_attention") or []
    if attention:
        parts.append("Needs attention")
    return " · ".join(parts)


def _render_page_header(page: str) -> None:
    """Render a compact page heading with the shared module context."""
    meta = _PAGE_META.get(page, _PAGE_META["Overview"])
    st.markdown(
        '<header class="professor-page-header">'
        '<div class="professor-page-heading">'
        f'<p class="professor-page-eyebrow">{escape(meta["eyebrow"])}</p>'
        f'<h2>{escape(meta["title"])}</h2>'
        f'<p>{escape(meta["description"])}</p>'
        '</div>'
        '<div class="professor-page-context">'
        f'<span class="professor-page-context-code">{escape(PRODUCT_TITLE)}</span>'
        f'<span>{escape(PRODUCT_SUBTITLE)}</span>'
        '</div>'
        '</header>',
        unsafe_allow_html=True,
    )


def _section_heading(title: str, description: str = "") -> None:
    """Render a consistent section heading used across analytics pages."""
    detail = (
        f'<p class="professor-section-description">{escape(description)}</p>'
        if description
        else ""
    )
    st.markdown(
        f'<div class="professor-section-heading"><h3>{escape(title)}</h3>{detail}</div>',
        unsafe_allow_html=True,
    )


def _render_sidebar() -> str:
    """Render persistent left navigation and return the selected page."""
    with st.container(key="professor_header"):
        st.markdown(
            f"""
            <div class="professor-course-heading professor-sidebar-brand">
              <p class="professor-eyebrow">{escape(PRODUCT_TITLE.split(" ", 1)[0])}</p>
              <h1>Course Analytics</h1>
              <p>{escape(PRODUCT_SUBTITLE)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="professor-sidebar-nav-label">Professor dashboard navigation</p>',
            unsafe_allow_html=True,
        )
        page = st.radio(
            "Professor dashboard navigation",
            _PAGES,
            label_visibility="collapsed",
            key="professor_page",
        )
        professor_name = escape(str(st.session_state.get("display_name") or "Teaching staff"))
        logout_url = app_logout_url()
        if logout_url:
            st.markdown(
                '<div class="professor-account professor-sidebar-account">'
                f"<span>{professor_name}</span>"
                f'<a href="{escape(logout_url, quote=True)}" target="_self" '
                'rel="noopener">Sign out</a></div>',
                unsafe_allow_html=True,
            )
        elif st.button("Sign out", key="professor_sign_out", type="tertiary"):
            logout_user()
    return page


def _when(value: str | None) -> str:
    """Render an ISO time compactly while retaining a clear missing state."""
    if not value:
        return "No activity"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b, %H:%M")
    except ValueError:
        return value


def _metric(label: str, value: str, detail: str = "") -> None:
    """Render a compact metric with supporting context instead of a hero card."""
    st.markdown(
        '<div class="professor-metric" role="group">'
        f'<p class="professor-metric-label">{escape(label)}</p>'
        f'<strong class="professor-metric-value">{escape(value)}</strong>'
        f'<span class="professor-metric-detail">{escape(detail)}</span></div>',
        unsafe_allow_html=True,
    )


def _bar_rows(
    items: list[dict[str, Any]],
    *,
    value_key: str,
    label_key: str = "stage",
    suffix: str = "",
    fixed_maximum: float | None = None,
    display_key: str | None = None,
) -> None:
    """Render accessible labelled horizontal bars without a decorative legend."""
    maximum = fixed_maximum or max(
        (float(item.get(value_key) or 0) for item in items), default=1
    ) or 1
    for item in items:
        label = escape(str(item.get(label_key) or ""))
        raw_value = item.get(value_key)
        value = float(raw_value or 0)
        display = item.get(display_key) if display_key else None
        rendered_value = (
            str(display)
            if display is not None
            else "Not assessed" if raw_value is None
            else f"{value:g}{suffix}"
        )
        st.markdown(
            f'<div class="professor-bar-row" aria-label="{label}: {escape(rendered_value)}">'
            f'<span>{label}</span><div class="professor-bar" aria-hidden="true">'
            f'<i style="width:{min(value / maximum * 100, 100):.0f}%"></i></div>'
            f"<b>{escape(rendered_value)}</b></div>",
            unsafe_allow_html=True,
        )


def _attention_table(rows: list[dict[str, Any]]) -> None:
    """Render deterministic attention reasons in a responsive roster table."""
    if not rows:
        st.caption("No current follow-up signals under the configured academic thresholds.")
        return
    table_rows: list[str] = []
    for row in rows:
        reasons = "; ".join(
            str(signal.get("reason") or "")
            for signal in row.get("needs_attention", [])
            if isinstance(signal, dict)
        )
        cells = (
            ("Student", row.get("name") or "Student"),
            ("Reason", reasons or "Follow-up signal"),
            ("Stage", row.get("current_stage") or "Not started"),
            ("Score", _score(row.get("facione_overall"))),
            ("Last active", _when(row.get("last_active"))),
        )
        table_rows.append(
            '<div class="professor-followup-row" role="row">'
            + "".join(
                f'<span data-label="{escape(label)}" role="cell">{escape(str(value))}</span>'
                for label, value in cells
            )
            + "</div>"
        )
    headers = "".join(
        f'<span role="columnheader">{escape(label)}</span>'
        for label in ("Student", "Reason", "Stage", "Score", "Last active")
    )
    st.markdown(
        '<div class="professor-followup-table" role="table">'
        f'<div class="professor-followup-header" role="row">{headers}</div>'
        + "".join(table_rows)
        + "</div>",
        unsafe_allow_html=True,
    )


def _line_chart(
    rows: list[dict[str, Any]],
    *,
    x: str,
    y: str,
    x_label: str,
    y_label: str,
    y_domain: tuple[float, float] | None = None,
) -> None:
    """Render a restrained time-series chart from row-oriented API data."""
    frame = pd.DataFrame.from_records(rows, columns=[x, y])
    frame[x] = pd.to_datetime(frame[x], errors="coerce")
    frame[y] = pd.to_numeric(frame[y], errors="coerce")
    chart = (
        alt.Chart(frame)
        .mark_line(color="#147D74", strokeWidth=2)
        .encode(
            x=alt.X(f"{x}:T", title=x_label, axis=alt.Axis(format="%d %b")),
            y=alt.Y(
                f"{y}:Q",
                title=y_label,
                scale=alt.Scale(domain=list(y_domain)) if y_domain else alt.Scale(zero=True),
            ),
            tooltip=[
                alt.Tooltip(f"{x}:T", title=x_label, format="%d %b %Y"),
                alt.Tooltip(f"{y}:Q", title=y_label),
            ],
        )
        .properties(height=220)
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, width="stretch")


def _render_overview(client) -> None:
    """Render the ten-second class overview from one authorised API response."""
    data = client.professor_overview()
    updated = _when(data.get("generated_at"))
    with st.container(key="professor_overview_metrics"):
        st.markdown(
            f'<div class="professor-updated"><span>Class snapshot</span>'
            f'<time datetime="{escape(str(data.get("generated_at") or ""), quote=True)}">'
            f"Last updated {escape(updated)}</time></div>",
            unsafe_allow_html=True,
        )
        metrics = st.columns(3, gap="small")
        with metrics[0]:
            _metric("Students", str(data["students"]), "enrolled records")
        with metrics[1]:
            _metric(
                "Active this week",
                f"{data['active_students_week']} / {data['students']}",
                "with current discussion",
            )
        with metrics[2]:
            _metric(
                "Need follow-up",
                str(data.get("attention_students_count", len(data.get("attention_students", [])))),
                "deterministic signals",
            )
    summary = escape(str(data.get("summary") or "No class summary is available yet."))
    st.markdown(
        f'<div class="professor-summary">{summary}</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="professor_overview_breakdown"):
        left, right = st.columns([1.08, 1], gap="large")
        with left:
            _section_heading(
                "Current thinking stage",
                "Students are counted at the most recently active notebook stage.",
            )
            stages = [
                {**item, "display": f"{item['count']} · {item['percentage']:g}%"}
                for item in data.get("stage_distribution", [])
            ]
            _bar_rows(stages, value_key="count", display_key="display")
        with right:
            _section_heading(
                "Follow-up queue",
                "Deterministic follow-up signals, not judgements of ability.",
            )
            _attention_table(data.get("attention_students", []))
    with st.container(key="professor_overview_activity"):
        _section_heading("Activity over time")
        activity = data.get("weekly_activity", [])
        if activity:
            _line_chart(
                activity, x="week", y="active_students",
                x_label="Week", y_label="Active students",
            )
        else:
            st.info("Weekly activity will appear after students begin using the coach.")


def _render_students(client) -> None:
    """Render the roster and the read-only student workbench.

    The first view stays a lightweight roster. Once a notebook is open, the
    same data is arranged as a compact three-pane workbench so lecturers can
    keep roster context beside the transcript and Thinking Path. Notebook tab
    endpoints remain lazy: opening a notebook still fetches chat only.
    """
    selected_id = st.session_state.get("professor_selected_student_id", "")
    opened_notebook = (
        st.session_state.get(f"professor_open_notebook_{selected_id}")
        if selected_id
        else None
    )

    if opened_notebook and selected_id:
        try:
            detail = _cached_professor_student_detail(client, selected_id)
        except Exception:  # noqa: BLE001 - keep notebook back control on fetch failure
            if st.button("← Notebooks", key=f"professor_back_notebooks_{selected_id}"):
                st.session_state.pop(f"professor_open_notebook_{selected_id}", None)
                _clear_notebook_tab_caches(selected_id, opened_notebook)
                st.rerun()
            st.error("This notebook is unavailable right now. Please try again shortly.")
            return
        student = detail.get("student") or {}
        notebook_summary = next(
            (
                item
                for item in detail.get("notebooks", [])
                if str(item.get("id")) == str(opened_notebook)
            ),
            {"id": opened_notebook, "title": "Notebook"},
        )
        with st.container(key=f"professor_selected_workbench_{selected_id}_{opened_notebook}"):
            roster_col, workspace_col, path_col = st.columns(
                [0.22, 0.49, 0.29], gap="small"
            )
            with roster_col:
                _render_workbench_roster(
                    client,
                    selected_id=selected_id,
                    notebook_id=str(opened_notebook),
                    selected_student=student,
                    selected_notebook=notebook_summary,
                )
            with workspace_col:
                if st.button(
                    "← Notebooks",
                    key=f"professor_back_notebooks_{selected_id}",
                ):
                    st.session_state.pop(f"professor_open_notebook_{selected_id}", None)
                    _clear_notebook_tab_caches(selected_id, opened_notebook)
                    st.rerun()
                _render_professor_workspace(
                    client,
                    selected_id,
                    notebook_summary,
                    student_name=str(student.get("name") or "Student"),
                    compact=True,
                )
            with path_col:
                _render_professor_thinking_rail(
                    client,
                    selected_id,
                    str(opened_notebook),
                    selected_student=student,
                    student_detail=detail,
                )
        return

    if selected_id:
        if st.button("← Students", key=f"professor_back_students_{selected_id}"):
            st.session_state.pop("professor_selected_student_id", None)
            st.session_state.pop(f"professor_open_notebook_{selected_id}", None)
            _clear_notebook_tab_caches(selected_id)
            st.rerun()
        try:
            detail = _cached_professor_student_detail(client, selected_id)
        except Exception:  # noqa: BLE001 - keep the back control when one record fails
            st.error("This student record is unavailable right now. Please try again shortly.")
            return
        _render_student_detail(client, detail)
        return

    with st.container(key="professor_students_roster"):
        filters = st.columns([2.2, 1.2, 1.2], gap="small")
        with filters[0]:
            search = st.text_input(
                "Search students", placeholder="Name or email", key="professor_student_search"
            )
        with filters[1]:
            stage = st.selectbox(
                "Stage", ["All", "Not started", *_PHASE_LABELS], key="professor_stage_filter"
            )
        with filters[2]:
            attention = st.selectbox(
                "Attention", ["All", "Needs attention"], key="professor_attention_filter"
            )
        stage_filter = None if stage == "All" else stage
        attention_only = attention == "Needs attention"
        data = _cached_professor_students(
            client,
            search=search,
            stage=stage_filter,
            attention_only=attention_only,
        )
        rows = data.get("students", [])
        if not rows:
            st.info("No students match these filters.")
            return
        st.markdown(
            f'<div class="professor-result-count">{len(rows)} student'
            f'{"s" if len(rows) != 1 else ""}</div>',
            unsafe_allow_html=True,
        )
        with st.container(key="professor_student_list_scroll"):
            for row in rows:
                student_id = str(row.get("id") or "")
                student_name = str(row.get("name") or "Student")
                initials = "".join(
                    piece[0] for piece in student_name.split() if piece
                ).upper()[:2] or "ST"
                attention_label = " · Needs attention" if row.get("needs_attention") else ""
                with st.container(key=f"professor_student_card_{student_id}"):
                    row_columns = st.columns([0.84, 0.16], gap="small")
                    with row_columns[0]:
                        st.markdown(
                            '<div class="professor-student-row">'
                            f'<span class="professor-student-avatar" aria-hidden="true">{escape(initials)}</span>'
                            '<span class="professor-student-copy">'
                            f'<strong>{escape(student_name)}</strong>'
                            f'<span>{escape(str(row.get("current_stage") or "Not started"))}'
                            f'{escape(attention_label)}</span>'
                            f'<small>{escape(_student_row_caption(row))}</small>'
                            '</span></div>',
                            unsafe_allow_html=True,
                        )
                    with row_columns[1]:
                        if st.button(
                            f"Open {student_name}",
                            key=f"professor_open_student_{student_id}",
                            use_container_width=True,
                        ):
                            st.session_state["professor_selected_student_id"] = student_id
                            st.session_state.pop(f"professor_open_notebook_{student_id}", None)
                            _clear_notebook_tab_caches(student_id)
                            st.rerun()


def _render_student_detail(
    client: Any, data: dict[str, Any]
) -> None:
    """Render one selected student's record and notebook rows."""
    student = data["student"]
    header = st.columns([0.82, 0.18], gap="small")
    with header[0]:
        st.markdown(f"### {student['name']}")
        st.caption(
            f"{student.get('email') or 'Authorised student record'} · "
            f"{student.get('current_stage') or 'Not started'} · "
            f"Last active {_when(student.get('last_active'))} · "
            f"{int(student.get('student_messages') or 0)} messages"
        )
    with header[1]:
        if st.button(
            "Refresh",
            key=f"professor_refresh_student_{student['id']}",
            use_container_width=True,
        ):
            _invalidate_student_detail_cache(student["id"])
            st.rerun()

    notebooks = data.get("notebooks", [])
    st.markdown(f"#### Notebooks ({len(notebooks)})")
    if not notebooks:
        st.info("This student has not started a notebook yet.")
    else:
        for item in notebooks:
            notebook_id = str(item.get("id") or "")
            with st.container(key=f"professor_notebook_card_{student['id']}_{notebook_id}"):
                row_columns = st.columns([0.84, 0.16], gap="small")
                with row_columns[0]:
                    st.markdown(
                        '<div class="professor-notebook-row">'
                        f'<strong>{escape(_notebook_card_label(item))}</strong>'
                        f'<span>{escape(str(item.get("stage") or item.get("current_stage") or "Not started"))}</span>'
                        f'<small>{escape(_notebook_row_caption(item))}</small>'
                        '</div>',
                        unsafe_allow_html=True,
                    )
                with row_columns[1]:
                    if st.button(
                        f"Open {_notebook_card_label(item)}",
                        key=f"professor_open_notebook_btn_{student['id']}_{notebook_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"professor_open_notebook_{student['id']}"] = notebook_id
                        _clear_notebook_tab_caches(student["id"], notebook_id)
                        st.rerun()

    st.markdown("#### Learning snapshot")
    completed_labels = set(data.get("completed_stages", []))
    current_stage = student.get("current_stage")
    steps = []
    for stage in _PHASE_LABELS:
        if stage in completed_labels and stage != current_stage:
            status = "completed"
        elif stage == current_stage:
            status = "current"
        elif stage in completed_labels:
            status = "completed"
        else:
            status = "not_completed"
        marker = "✓" if status == "completed" else "●" if status == "current" else "○"
        steps.append(
            f'<span class="professor-step professor-step-{status}">'
            f"<b>{marker}</b> {escape(stage)}</span>"
        )
    st.markdown(f'<div class="professor-progress">{"".join(steps)}</div>', unsafe_allow_html=True)
    overview_left, overview_right = st.columns(2, gap="large")
    with overview_left:
        st.markdown("#### Critical thinking")
        profile_rows = []
        class_profile = data.get("class_facione_profile", {})
        for key, value in data.get("facione_profile", {}).items():
            display = "Not assessed" if value is None else f"{value:.1f} / 4"
            class_value = class_profile.get(key, {})
            if class_value.get("value") is not None:
                display += (
                    f" · class {class_value['value']:.1f} "
                    f"(n={class_value.get('sample_size', 0)})"
                )
            profile_rows.append({"dimension": key, "score": value, "display": display})
        if profile_rows:
            _bar_rows(profile_rows, value_key="score", label_key="dimension", fixed_maximum=4, display_key="display")
        else:
            st.caption("No critical-thinking assessment is available yet.")
    with overview_right:
        st.markdown("#### Engagement")
        engagement = data.get("engagement", {})
        engagement_metrics = st.columns(2, gap="small")
        with engagement_metrics[0]:
            _metric("Active days", str(engagement.get("active_days", 0)))
            _metric("Student messages", str(engagement.get("student_messages", 0)))
        with engagement_metrics[1]:
            _metric("Sessions", str(engagement.get("sessions", 0)))
            _metric(
                "Estimated active time",
                f"{engagement.get('estimated_active_minutes', 0)} min",
            )
        st.caption(engagement.get("definition", ""))

    trend = data.get("facione_trend", [])
    if len(trend) >= 2:
        st.markdown("#### Critical-thinking trend")
        _line_chart(
            trend, x="at", y="overall",
            x_label="Assessment", y_label="Overall score (0–4)", y_domain=(0, 4),
        )
        st.caption("Assessment trend is descriptive only; it does not establish causal change.")


def _workbench_filter_rows(
    rows: list[dict[str, Any]],
    filter_name: str,
) -> list[dict[str, Any]]:
    """Apply the visual workbench roster filter without another API contract."""
    if filter_name == "Active":
        return [
            row
            for row in rows
            if row.get("last_active") or int(row.get("student_messages") or 0) > 0
        ]
    if filter_name == "Done":
        return [
            row
            for row in rows
            if int(row.get("stage_progress") or 0) >= len(_PHASE_LABELS)
        ]
    return rows


def _render_workbench_roster(
    client: Any,
    *,
    selected_id: str,
    notebook_id: str,
    selected_student: dict[str, Any],
    selected_notebook: dict[str, Any],
) -> None:
    """Render the selected-notebook roster context using the existing API."""
    with st.container(key=f"professor_workbench_roster_{selected_id}_{notebook_id}"):
        st.markdown(
            '<div class="professor-workbench-panel-heading">'
            '<p class="professor-workbench-eyebrow">Student work</p>'
            '<h3>All students</h3></div>',
            unsafe_allow_html=True,
        )
        search = st.text_input(
            "Search students",
            placeholder="Name or email",
            key=f"professor_workbench_search_{selected_id}_{notebook_id}",
            label_visibility="collapsed",
        )
        filter_name = st.radio(
            "Roster filter",
            ("All", "Active", "Done"),
            horizontal=True,
            key=f"professor_workbench_filter_{selected_id}_{notebook_id}",
            label_visibility="collapsed",
        )
        roster = _cached_professor_students(
            client,
            search=search,
            stage=None,
            attention_only=False,
        )
        rows = _workbench_filter_rows(list(roster.get("students") or []), filter_name)
        selected_row = {
            "id": selected_id,
            "name": selected_student.get("name") or "Student",
            "current_stage": selected_student.get("current_stage"),
            "stage_progress": selected_student.get("stage_progress"),
            "student_messages": selected_student.get("student_messages"),
            "last_active": selected_student.get("last_active"),
        }
        if not any(str(row.get("id")) == selected_id for row in rows):
            rows.insert(0, selected_row)
        st.markdown(
            f'<p class="professor-workbench-count">{len(rows)} student'
            f'{"s" if len(rows) != 1 else ""}</p>',
            unsafe_allow_html=True,
        )
        with st.container(key=f"professor_workbench_roster_scroll_{selected_id}_{notebook_id}"):
            for row in rows:
                row_id = str(row.get("id") or "")
                if not row_id:
                    continue
                name = str(row.get("name") or "Student")
                initials = "".join(piece[0] for piece in name.split() if piece).upper()[:2] or "ST"
                is_selected = row_id == selected_id
                card_key = (
                    f"professor_workbench_student_card_{row_id}_selected"
                    if is_selected
                    else f"professor_workbench_student_card_{row_id}"
                )
                with st.container(key=card_key):
                    st.markdown(
                        '<div class="professor-workbench-student-row">'
                        f'<span class="professor-student-avatar" aria-hidden="true">{escape(initials)}</span>'
                        '<span class="professor-student-copy">'
                        f'<strong>{escape(name)}</strong>'
                        f'<span>{escape(str(selected_notebook.get("title") if is_selected else row.get("current_stage") or "Not started"))}</span>'
                        f'<small>{escape("Active" if is_selected else _when(row.get("last_active")))}</small>'
                        '</span>'
                        f'<span class="professor-workbench-student-status" aria-label="{escape("Selected" if is_selected else "Student")}">'
                        f'{"●" if is_selected else ""}</span></div>',
                        unsafe_allow_html=True,
                    )
                    if not is_selected and st.button(
                        f"Open {name}",
                        key=f"professor_workbench_select_student_{row_id}_{notebook_id}",
                        use_container_width=True,
                    ):
                        st.session_state["professor_selected_student_id"] = row_id
                        st.session_state.pop(f"professor_open_notebook_{row_id}", None)
                        _clear_notebook_tab_caches(row_id)
                        st.rerun()


def _render_professor_thinking_rail(
    client: Any,
    student_id: str,
    notebook_id: str,
    *,
    selected_student: dict[str, Any],
    student_detail: dict[str, Any],
) -> None:
    """Render a lazy Thinking Path rail beside the read-only transcript."""
    rail_key = f"professor_thinking_rail_{student_id}_{notebook_id}"
    loaded_key = f"{rail_key}_loaded"
    # Review is the visual default in the supplied workbench. The initial
    # state uses the already-fetched student profile as a quiet placeholder;
    # the full review projection is fetched only after an explicit click.
    active = st.session_state.get(rail_key) or "Review"
    loaded = bool(st.session_state.get(loaded_key))
    with st.container(key=f"professor_path_rail_{student_id}_{notebook_id}"):
        st.markdown(
            '<div class="professor-path-heading"><h3>Thinking Path</h3></div>',
            unsafe_allow_html=True,
        )
        controls = st.columns(2, gap="small")
        with controls[0]:
            if st.button(
                "Progression",
                key=f"professor_path_progression_{student_id}_{notebook_id}",
                use_container_width=True,
                type="secondary" if active != "Progression" else "primary",
            ):
                st.session_state[rail_key] = "Progression"
                st.session_state[loaded_key] = True
                st.rerun()
        with controls[1]:
            if st.button(
                "Review",
                key=f"professor_path_review_{student_id}_{notebook_id}",
                use_container_width=True,
                type="secondary" if active != "Review" else "primary",
            ):
                st.session_state[rail_key] = "Review"
                st.session_state[loaded_key] = True
                st.rerun()
        if active == "Progression":
            if loaded:
                journey_payload = _cached_professor_journey(client, student_id, notebook_id)
                _render_professor_journey_tab(journey_payload)
            else:
                _render_professor_path_fallback(
                    selected_student=selected_student,
                    student_detail=student_detail,
                    notebook_id=notebook_id,
                    mode="Progression",
                )
        elif active == "Review":
            if loaded:
                review_payload = _cached_professor_review(client, student_id, notebook_id)
                _render_professor_review_tab(review_payload)
            else:
                _render_professor_path_fallback(
                    selected_student=selected_student,
                    student_detail=student_detail,
                    notebook_id=notebook_id,
                    mode="Review",
                )


def _render_professor_path_fallback(
    *,
    selected_student: dict[str, Any],
    student_detail: dict[str, Any],
    notebook_id: str,
    mode: str,
) -> None:
    """Show already-available profile context before a rail projection loads."""
    if mode == "Progression":
        completed = {str(item).strip().lower() for item in student_detail.get("completed_stages", [])}
        current = str(selected_student.get("current_stage") or "").strip().lower()
        stages: list[str] = []
        for stage in _PHASE_LABELS:
            key = stage.lower()
            state = "completed" if key in completed else "current" if key == current else "not_completed"
            _render_journey_stage_row(stage, state)
            stages.append(stage)
        return

    st.markdown(
        '<div class="professor-path-fallback-card">'
        '<strong>Working conclusion</strong>'
        '<span>Detailed review is available from the Review tab.</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="professor-path-fallback-card">'
        '<strong>Strengths</strong><span>Review evidence will appear here.</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="professor-path-fallback-card">'
        '<strong>Areas for improvement</strong><span>Review evidence will appear here.</span></div>',
        unsafe_allow_html=True,
    )
    source = student_detail.get("facione_profile") or {}
    scores: dict[str, int] = {}
    for key, value in source.items():
        normalized = str(key).strip().lower().replace(" ", "_").replace("-", "_")
        try:
            scores[normalized] = int(round(float(value))) if value is not None else 0
        except (TypeError, ValueError):
            scores[normalized] = 0
    st.markdown(
        facione_scores_table_html(scores),
        unsafe_allow_html=True,
    )


def _render_professor_workspace(
    client: Any,
    student_id: str,
    notebook: dict[str, Any],
    *,
    student_name: str | None = None,
    compact: bool = False,
) -> None:
    """Render the read-only Chat, Sources, Journey, and Review tabs."""
    notebook_id = str(notebook.get("id") or "")
    with st.container(key=f"professor_workspace_header_{student_id}_{notebook_id}"):
        breadcrumb = (
            '<p class="professor-workspace-breadcrumb">'
            f"Students / {escape(student_name or 'Student')} / "
            f"{escape(_notebook_card_label(notebook))}</p>"
            if student_name
            else ""
        )
        header_html = (
            '<div class="professor-workspace-heading">'
            + '<div class="professor-workspace-heading-copy">'
            + breadcrumb
            + f'<p class="professor-workspace-eyebrow">Read-only notebook</p>'
            + f'<h3>{escape(_notebook_card_label(notebook))}</h3>'
            + f'<p>{escape(str(notebook.get("stage") or notebook.get("current_stage") or "Not started"))}'
            + f' <span aria-hidden="true">·</span> Active {escape(_when(notebook.get("last_active")))}</p></div>'
            + '<span class="professor-readonly-badge">View only</span></div>'
        )
        st.markdown(
            header_html,
            unsafe_allow_html=True,
        )
    tab = st.radio(
        "Notebook workspace",
        _WORKSPACE_TABS,
        horizontal=True,
        key=f"professor_workspace_tab_{student_id}_{notebook_id}",
        label_visibility="collapsed",
    )
    refresh_key = f"professor_refresh_{tab.lower()}_{student_id}_{notebook_id}"
    refresh_columns = st.columns([0.82, 0.18], gap="small")
    with refresh_columns[1]:
        refresh_requested = st.button("Refresh", key=refresh_key, use_container_width=True)
    if refresh_requested:
        if tab == "Chat":
            _invalidate_chat_cache(student_id, notebook_id)
        elif tab == "Sources":
            _invalidate_sources_cache(student_id, notebook_id)
        elif tab == "Progression":
            _invalidate_journey_cache(student_id, notebook_id)
        else:
            _invalidate_review_cache(student_id, notebook_id)
        st.rerun()
    if tab == "Chat":
        chat_payload = _cached_professor_chat(client, student_id, notebook_id)
        _render_professor_chat_tab(
            client,
            student_id,
            notebook_id,
            chat_payload,
        )
    elif tab == "Sources":
        sources_payload = _cached_professor_sources(client, student_id, notebook_id)
        _render_professor_sources_tab(client, student_id, notebook_id, sources_payload)
    elif tab == "Progression":
        journey_payload = _cached_professor_journey(client, student_id, notebook_id)
        _render_professor_journey_tab(journey_payload)
    else:
        review_payload = _cached_professor_review(client, student_id, notebook_id)
        _render_professor_review_tab(review_payload)


def _render_professor_chat_tab(
    client: Any,
    student_id: str,
    notebook_id: str,
    chat_payload: dict[str, Any],
) -> None:
    """Render the active-branch transcript inside a scroll region."""
    messages = list(chat_payload.get("messages") or [])
    cache = st.session_state.setdefault(_CHAT_CACHE_KEY, {})
    cache_entry = cache.setdefault((student_id, notebook_id), chat_payload)
    next_cursor = cache_entry.get("next_cursor")
    if next_cursor and st.button("Load earlier messages", key=f"professor_load_earlier_{notebook_id}"):
        older = client.professor_notebook_messages(
            student_id, notebook_id, cursor=next_cursor
        )
        cache_entry["messages"] = list(older.get("messages") or []) + messages
        cache_entry["next_cursor"] = older.get("next_cursor")
        st.rerun()
        return
    if not messages:
        st.caption("No conversation has been recorded in this notebook.")
        return
    with st.container(key="professor_transcript_scroll"):
        for index, message in enumerate(messages):
            message_key = str(message.get("id") or index)
            with st.container(key=f"professor_message_{notebook_id}_{message_key}"):
                role = str(message.get("role") or "")
                speaker = "Student" if role == "user" else "Coach"
                role_class = "student" if role == "user" else "coach"
                with st.chat_message(
                    "user" if role == "user" else "assistant",
                    avatar=(
                        ":material/person:"
                        if role == "user"
                        else ":material/auto_awesome:"
                    ),
                ):
                    st.markdown(
                        f'<div class="professor-chat-meta professor-chat-{role_class}">'
                        f'<span class="professor-chat-speaker">'
                        f"<strong>{escape(speaker)}</strong></span>"
                        f"<time>{escape(_when(message.get('created_at')))}</time></div>",
                        unsafe_allow_html=True,
                    )
                    content = str(message.get("content") or "")
                    if content:
                        with st.container(
                            key=f"professor_message_body_{notebook_id}_{message_key}"
                        ):
                            st.markdown(content)
                    for attachment in message.get("attachments") or []:
                        _render_professor_attachment_row(
                            client,
                            student_id,
                            notebook_id,
                            message,
                            attachment,
                        )
                    citations = message.get("citations") or []
                    if citations:
                        st.markdown("**Sources used**")
                        for citation in citations:
                            _render_professor_citation_row(
                                client,
                                student_id,
                                notebook_id,
                                citation,
                            )


def _render_professor_attachment_row(
    client: Any,
    student_id: str,
    notebook_id: str,
    message: dict[str, Any],
    attachment: dict[str, Any],
) -> None:
    """Render one compact attachment row with lazy open."""
    attachment_id = str(attachment.get("id") or "")
    title = str(attachment.get("title") or "Attachment")
    mime = str(attachment.get("mime") or "application/octet-stream")
    size_label = _format_file_size(attachment.get("size"))
    icon = _file_icon(mime, kind=str(attachment.get("kind") or ""))
    row = st.columns([0.78, 0.22], gap="small")
    with row[0]:
        st.markdown(
            f'<div class="professor-file-row">'
            f'<div class="professor-file-row-title">{icon} {escape(title)}</div>'
            f'<div class="professor-file-row-meta">'
            f"{escape(_file_type_label(mime))} · {escape(size_label)}</div></div>",
            unsafe_allow_html=True,
        )
    with row[1]:
        if attachment_id and hasattr(client, "professor_conversation_attachment"):
            if st.button(
                f"Open attachment {title}",
                key=f"professor_attachment_{message.get('id')}_{attachment_id}",
                use_container_width=True,
            ):
                _professor_attachment_dialog(
                    client,
                    student_id,
                    notebook_id,
                    attachment_id,
                    title,
                )


def _render_professor_citation_row(
    client: Any,
    student_id: str,
    notebook_id: str,
    citation: dict[str, Any],
) -> None:
    """Render one citation row; open bytes only on explicit click."""
    citation_id = str(citation.get("id") or "").strip()
    label = str(citation.get("label") or citation_id or "source").strip()
    title = str(citation.get("title") or label or "Source").strip()
    display = f"[{label}] {title}" if label and title != label else f"[{label}]"
    row = st.columns([0.78, 0.22], gap="small")
    with row[0]:
        st.caption(display)
    with row[1]:
        if citation_id and hasattr(client, "professor_notebook_source"):
            if st.button(
                f"Open source {title}",
                key=f"professor_citation_{notebook_id}_{citation_id}_{label}",
                use_container_width=True,
            ):
                _professor_source_dialog(
                    client,
                    student_id,
                    notebook_id,
                    citation_id,
                    title,
                )


def _render_professor_sources_tab(
    client: Any,
    student_id: str,
    notebook_id: str,
    sources_payload: dict[str, Any],
) -> None:
    """Render grouped library sources as visible sections."""
    sources = list(sources_payload.get("sources") or [])
    grouped: dict[str, list[dict[str, Any]]] = {group: [] for group in COURSE_MATERIAL_GROUPS}
    grouped["My Sources"] = []
    for source in sources:
        group = str(source.get("group") or "My Sources")
        grouped.setdefault(group, []).append(source)
    st.markdown("#### My Sources")
    if grouped["My Sources"]:
        for source in grouped["My Sources"]:
            _render_professor_source_row(client, student_id, notebook_id, source)
    else:
        st.caption("No personal sources in this notebook.")
    for group in COURSE_MATERIAL_GROUPS:
        group_sources = grouped.get(group) or []
        st.markdown(f"#### {group}")
        if group_sources:
            for source in group_sources:
                _render_professor_source_row(client, student_id, notebook_id, source)
        else:
            st.caption(f"No {group.lower()} in this notebook.")


def _render_professor_source_row(
    client: Any,
    student_id: str,
    notebook_id: str,
    source: dict[str, Any],
) -> None:
    """Render one read-only source row with lazy open."""
    source_id = str(source.get("id") or "")
    title = str(source.get("title") or "Source")
    mime = str(source.get("mime") or "application/octet-stream")
    size = source.get("size")
    status = "Course material" if source.get("locked") else (
        "Selected" if source.get("selected") else "Not selected"
    )
    icon = _file_icon(mime, kind=str(source.get("kind") or ""))
    meta_parts = [_file_type_label(mime), status]
    if size:
        meta_parts.append(_format_file_size(size))
    row = st.columns([0.78, 0.22], gap="small")
    with row[0]:
        st.markdown(
            f'<div class="professor-file-row">'
            f'<div class="professor-file-row-title">{icon} {escape(title)}</div>'
            f'<div class="professor-file-row-meta">'
            f"{escape(' · '.join(meta_parts))}</div></div>",
            unsafe_allow_html=True,
        )
    with row[1]:
        if source_id and source.get("has_file") and hasattr(client, "professor_notebook_source"):
            if st.button(
                f"Open source {title}",
                key=f"professor_source_{notebook_id}_{source_id}",
                use_container_width=True,
            ):
                _professor_source_dialog(client, student_id, notebook_id, source_id, title)


def _render_journey_stage_row(label: str, state: str) -> None:
    """Render one persisted journey stage without inferring completion."""
    marker = "✓" if state == "completed" else "●" if state == "current" else "○"
    status = (
        "Completed"
        if state == "completed"
        else "Current focus"
        if state == "current"
        else "Not completed"
    )
    st.markdown(
        f'<div class="professor-timeline-step professor-step professor-step-{escape(state)}">'
        f'<b class="professor-timeline-node" aria-hidden="true">{marker}</b>'
        f'<span class="professor-timeline-copy"><strong>{escape(label)}</strong>'
        f"<small>{escape(status)}</small></span></div>",
        unsafe_allow_html=True,
    )


def _render_professor_journey_tab(journey_payload: dict[str, Any]) -> None:
    """Render the Thinking Path from persisted completion state."""
    stages = list(journey_payload.get("stages") or [])
    if not stages:
        journey = normalize_journey(journey_payload.get("journey") or {})
        completed = {
            str(item).lower() for item in (journey.get("completed_stages") or [])
        }
        current_id = str(journey.get("current_stage") or THINKING_STAGES[0].id)
        for stage in THINKING_STAGES:
            if stage.id in completed and stage.id != current_id:
                state = "completed"
            elif stage.id == current_id:
                state = "current"
            elif stage.id in completed:
                state = "completed"
            else:
                state = "not_completed"
            _render_journey_stage_row(stage.label, state)
    else:
        for stage in stages:
            state = str(stage.get("state") or "not_completed")
            _render_journey_stage_row(
                str(stage.get("label") or stage.get("id") or ""),
                state,
            )
    hmw = journey_payload.get("hmw_scaffold") or {}
    if hmw.get("available"):
        render_hmw_scaffold()


def _render_professor_review_tab(review_payload: dict[str, Any]) -> None:
    """Render the Review projection without Deep Review controls."""
    review = dict(review_payload)
    st.markdown(
        review_card_html(
            label="Summary",
            body=str(review.get("summary") or ""),
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        facione_scores_table_html(review.get("facione_scores")),
        unsafe_allow_html=True,
    )
    with st.expander("Strengths", expanded=False):
        st.markdown(
            review_stage_sections_html(sections=review.get("strength_sections")),
            unsafe_allow_html=True,
        )
    with st.expander("Areas for improvement", expanded=False):
        st.markdown(
            review_stage_sections_html(sections=review.get("improvement_sections")),
            unsafe_allow_html=True,
        )
    conclusion = str(review.get("conclusion") or "").strip()
    with st.expander("Working conclusion", expanded=False):
        if conclusion:
            st.markdown(
                f'<div class="review-conclusion-body">{escape(conclusion)}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<p class="review-empty">No working conclusion yet.</p>',
                unsafe_allow_html=True,
            )


def _citation_display(citation: Any) -> str:
    """Render one persisted citation as a safe, friendly reference label."""
    if isinstance(citation, dict):
        identifier = str(citation.get("label") or citation.get("id") or "source").strip()
        title = str(citation.get("title") or citation.get("label") or citation.get("id") or "Source").strip()
    else:
        identifier = title = str(citation or "Source").strip()
    value = f"[{identifier}] {title}" if identifier and title != identifier else f"[{identifier}]"
    escaped = escape(value)
    for character in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "#", "+", "-", ".", "!", "|", ">"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


@st.dialog("Source", width="large")
def _professor_source_dialog(
    client: Any,
    student_id: str,
    notebook_id: str,
    source_id: str,
    title: str,
) -> None:
    """Fetch and preview one authorized library source only after a click."""
    try:
        content = client.professor_notebook_source(student_id, notebook_id, source_id)
    except Exception:  # noqa: BLE001 - safe lecturer-facing error
        st.error("This source is unavailable or no longer authorized.")
        return
    st.markdown(f"### {title}")
    mime = str(content.mime or "application/octet-stream").split(";", 1)[0].lower()
    if mime == "application/pdf" or content.filename.lower().endswith(".pdf"):
        st.pdf(content.data, height=560, key=f"professor_source_pdf_{source_id}")
    elif mime.startswith("image/"):
        st.image(content.data, use_container_width=True)
    elif mime.startswith("text/"):
        st.text(content.data.decode("utf-8", errors="replace"))
    else:
        st.info("Preview is not available for this file type.")
    st.download_button(
        "Download source",
        data=content.data,
        file_name=content.filename or title,
        mime=content.mime,
        key=f"professor_source_download_{source_id}",
    )


@st.dialog("Attachment", width="large")
def _professor_attachment_dialog(
    client: Any,
    student_id: str,
    notebook_id: str,
    attachment_id: str,
    title: str,
) -> None:
    """Fetch and preview one authorized attachment only after a click."""
    try:
        content = client.professor_conversation_attachment(
            student_id, notebook_id, attachment_id
        )
    except Exception:  # noqa: BLE001 - safe lecturer-facing error
        st.error("This attachment is unavailable or no longer authorized.")
        return
    st.markdown(f"### {title}")
    mime = str(content.mime or "application/octet-stream").split(";", 1)[0].lower()
    if mime == "application/pdf" or content.filename.lower().endswith(".pdf"):
        st.pdf(content.data, height=560, key=f"professor_pdf_{attachment_id}")
    elif mime.startswith("image/"):
        st.image(content.data, use_container_width=True)
    elif mime.startswith("text/"):
        st.text(content.data.decode("utf-8", errors="replace"))
    else:
        st.info("Preview is not available for this file type.")
    st.download_button(
        "Download attachment",
        data=content.data,
        file_name=content.filename or title,
        mime=content.mime,
        key=f"professor_download_{attachment_id}",
    )


def _render_critical_thinking(client) -> None:
    """Render teaching-relevant Facione distributions and non-causal comparisons."""
    data = client.professor_critical_thinking()
    with st.container(key="professor_learning_stage"):
        _section_heading(
            "Stage distribution",
            "Students are counted at the most recently active notebook stage.",
        )
        stage_rows = data.get("stage_distribution") or []
        if stage_rows:
            _bar_rows(
                stage_rows,
                value_key="count",
                label_key="stage",
                suffix=" students",
            )
        else:
            st.info("Stage distribution will appear after students begin a notebook.")
    with st.container(key="professor_learning_profile"):
        _section_heading(
            "Critical-thinking class profile",
            "Medians use each student’s latest assessed response; not-started dimensions are excluded.",
        )
        dimensions = [
            {
                "dimension": label,
                "score": item.get("value"),
                "display": (
                    "Not assessed"
                    if item.get("value") is None
                    else f"{item['value']:.1f} / 4 · n={item['sample_size']}"
                ),
            }
            for label, item in data.get("dimensions", {}).items()
        ]
        _bar_rows(
            dimensions, value_key="score", label_key="dimension",
            fixed_maximum=4, display_key="display",
        )
        if not any(item.get("value") is not None for item in data.get("dimensions", {}).values()):
            st.caption("Not enough assessed students yet.")
    with st.container(key="professor_learning_comparison"):
        left, right = st.columns(2, gap="large")
        with left:
            _section_heading("Score distribution")
            _bar_rows(
                data.get("distribution", []),
                value_key="count",
                label_key="band",
                suffix=" students",
            )
        with right:
            _section_heading(
                "Stage and score",
                "Displayed only when at least three students are in a stage; this does not imply causality.",
            )
            comparisons = [
                {**item, "display": f"{item['median']:.1f} / 4 · n={item['sample_size']}"}
                for item in data.get("stage_comparison", [])
            ]
            _bar_rows(
                comparisons, value_key="median", fixed_maximum=4, display_key="display"
            )
    if data.get("trend"):
        with st.container(key="professor_learning_trend"):
            _section_heading("Assessment trend")
            _line_chart(
                data["trend"], x="date", y="median",
                x_label="Date", y_label="Median score (0–4)", y_domain=(0, 4),
            )


def _render_engagement(client) -> None:
    """Render meaningful usage patterns without rewarding high message volume."""
    data = client.professor_engagement()
    with st.container(key="professor_engagement_trends"):
        left, right = st.columns(2, gap="large")
        with left:
            _section_heading("Weekly active students")
            weekly = data.get("weekly_active_students", [])
            if weekly:
                _line_chart(
                    weekly, x="week", y="active_students",
                    x_label="Week", y_label="Active students",
                )
            else:
                st.info("No student activity has been recorded yet.")
        with right:
            _section_heading("Student messages by week")
            weekly_messages = data.get("weekly_messages", [])
            if weekly_messages:
                _line_chart(
                    weekly_messages, x="week", y="student_messages",
                    x_label="Week", y_label="Student messages",
                )
            else:
                st.info("No student messages have been recorded yet.")
    with st.container(key="professor_engagement_distribution"):
        _section_heading("Activity distribution")
        distribution, time = st.columns(2, gap="large")
        with distribution:
            st.markdown('<p class="professor-subsection-label">Sessions per student</p>', unsafe_allow_html=True)
            _bar_rows(
                data.get("active_day_distribution", []),
                value_key="students",
                label_key="days",
                suffix=" students",
            )
        with time:
            st.markdown('<p class="professor-subsection-label">Estimated time per session</p>', unsafe_allow_html=True)
            _bar_rows(
                data.get("estimated_active_time_distribution", []),
                value_key="students",
                label_key="band",
                suffix=" students",
            )
        st.caption(data.get("definition", ""))
    with st.container(key="professor_engagement_grounding"):
        _section_heading("Source-grounded coaching")
        grounded = data.get("source_grounded_responses", 0)
        assessed = data.get("assessed_coach_responses", 0)
        percentage = data.get("source_grounded_percentage")
        if assessed:
            st.caption(
                f"{grounded} of {assessed} assessed coach responses cited at least one persisted source"
                + (f" ({percentage:g}%)." if percentage is not None else ".")
            )
        else:
            st.caption("Source grounding will appear after assessed coach responses are recorded.")
    with st.container(key="professor_engagement_inactive"):
        _section_heading("Recently inactive students")
        _attention_table(data.get("inactive_students", []))


def _research_codes(values: Any) -> str:
    """Render a compact list of provisional or human codes."""
    if not isinstance(values, list) or not values:
        return "None recorded"
    return ", ".join(str(value).replace("_", " ").title() for value in values)


def _research_code_label(value: str | None) -> str:
    """Render a canonical research code without changing its stored value."""
    if value is None:
        return "Not assigned"
    return str(value).replace("_", " ").replace("-", " ").title()


def _render_research_observation(observation: dict[str, Any]) -> None:
    """Render automated codes with provenance and no validity overclaim."""
    status = escape(str(observation.get("coding_status") or "uncoded").title())
    phase = escape(str(observation.get("phase_id") or "Unknown").replace("_", " ").title())
    clear = escape(_research_code_label(observation.get("dominant_clear")))
    st.markdown(
        '<div class="research-coding-card">'
        f'<p class="research-coding-meta">{phase} · {status}</p>'
        f'<h4>Dominant CLEAR · {clear}</h4>'
        f'<p><b>Facione behaviours</b><br>{escape(_research_codes(observation.get("facione_behaviors")))}</p>'
        f'<p><b>Ethics concepts</b><br>{escape(_research_codes(observation.get("ethics_concepts")))}</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    evidence = observation.get("evidence") or []
    if evidence:
        st.caption("Evidence offsets refer to the immutable student utterance.")
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                continue
            st.markdown(
                f"**Evidence {index}** · characters {item.get('start_offset', 0)}–"
                f"{item.get('end_offset', 0)} · confidence "
                f"{float(item.get('confidence') or 0):.2f}\n\n"
                f"{item.get('rationale') or ''}"
            )
    st.caption(
        "Automated coding is provisional research support—not a grade, diagnosis, "
        "or validated measurement of student ability."
    )


def _render_research_validation(client: Any, observation: dict[str, Any]) -> None:
    """Render append-only human review and optional adjudication controls."""
    observation_id = str(observation.get("id") or "")
    reviews = list(observation.get("reviews") or [])
    adjudications = list(observation.get("adjudications") or [])
    st.markdown("#### Human validation")
    st.caption(
        "Reviews are append-only and attributed to your authenticated staff account."
    )
    with st.form(f"research_review_{observation_id}"):
        status = st.selectbox(
            "Validation decision",
            ["confirmed", "amended", "rejected"],
            format_func=lambda value: value.title(),
            key=f"research_review_status_{observation_id}",
        )
        coding_status = st.selectbox(
            "Validated coding status",
            ["coded", "partial", "uncoded"],
            index=["coded", "partial", "uncoded"].index(
                str(observation.get("coding_status") or "uncoded")
            ),
            key=f"research_review_coding_status_{observation_id}",
        )
        clear_options: list[str | None] = [
            None, "concise", "logical", "explicit", "adaptive", "reflective"
        ]
        automated_clear = str(observation.get("dominant_clear") or "").casefold() or None
        dominant_clear = st.selectbox(
            "Validated dominant CLEAR strategy",
            clear_options,
            index=(
                clear_options.index(automated_clear)
                if automated_clear in clear_options
                else 0
            ),
            format_func=_research_code_label,
            key=f"research_review_clear_{observation_id}",
        )
        facione_options = [
            "analysis", "interpretation", "inference", "evaluation",
            "explanation", "self_regulation",
        ]
        facione_behaviors = st.multiselect(
            "Validated Facione behaviours (up to 2)",
            facione_options,
            default=[
                value for value in (
                    str(item).casefold().replace("-", "_")
                    for item in observation.get("facione_behaviors") or []
                ) if value in facione_options
            ],
            max_selections=2,
            format_func=_research_code_label,
            key=f"research_review_facione_{observation_id}",
        )
        ethics_options = [
            "fairness", "privacy", "transparency", "non_maleficence",
            "responsibility",
        ]
        ethics_concepts = st.multiselect(
            "Validated ethics concepts",
            ethics_options,
            default=[
                value for value in (
                    str(item).casefold().replace("-", "_")
                    for item in observation.get("ethics_concepts") or []
                ) if value in ethics_options
            ],
            format_func=_research_code_label,
            key=f"research_review_ethics_{observation_id}",
        )
        notes = st.text_area(
            "Review rationale",
            max_chars=2_000,
            placeholder="Explain the evidence for this validation decision.",
            key=f"research_review_notes_{observation_id}",
        )
        submitted = st.form_submit_button("Submit validation")
        if submitted:
            if not notes.strip():
                st.error("Add a rationale before submitting the validation.")
            elif coding_status == "coded" and dominant_clear is None:
                st.error("Choose one dominant CLEAR strategy for a coded review.")
            elif coding_status != "coded" and dominant_clear is not None:
                st.error("Only a fully coded review can assign a CLEAR strategy.")
            else:
                payload: dict[str, Any] = {
                    "observation_id": observation_id,
                    "status": status,
                    "coding_status": coding_status,
                    "dominant_clear": dominant_clear,
                    "facione_behaviors": facione_behaviors,
                    "ethics_concepts": ethics_concepts,
                    "evidence": observation.get("evidence"),
                    "holistic_candidate": observation.get("holistic_candidate"),
                    "notes": notes.strip(),
                }
                client.professor_submit_research_review(payload)
                st.success("Validation recorded.")
    if reviews:
        st.markdown("##### Review history")
        st.dataframe(
            [
                {
                    "Status": item.get("status", ""),
                    "Reviewer": item.get("reviewer_user_id", ""),
                    "Notes": item.get("notes") or "—",
                    "Created": _when(item.get("created_at")),
                }
                for item in reviews
            ],
            hide_index=True,
            width="stretch",
        )
    if len(reviews) >= 2:
        with st.expander("Adjudicate reviews"):
            with st.form(f"research_adjudication_{observation_id}"):
                decision = st.selectbox(
                    "Adjudication decision",
                    ["confirmed", "amended", "rejected"],
                    format_func=lambda value: value.title(),
                    key=f"research_adjudication_decision_{observation_id}",
                )
                rationale = st.text_area(
                    "Adjudication rationale",
                    max_chars=2_000,
                    key=f"research_adjudication_notes_{observation_id}",
                )
                if st.form_submit_button("Submit adjudication"):
                    if not rationale.strip():
                        st.error("Add a rationale before submitting the adjudication.")
                    else:
                        client.professor_submit_research_adjudication(
                            {
                                "observation_id": observation_id,
                                "referenced_review_ids": [
                                    str(item.get("id") or "") for item in reviews
                                    if item.get("id")
                                ],
                                "decision": decision,
                                "notes": rationale.strip(),
                            }
                        )
                        st.success("Adjudication recorded.")
    if adjudications:
        st.caption(f"{len(adjudications)} adjudication record(s) retained.")


def _render_research(client: Any) -> None:
    """Render an audited queue-to-transcript-to-validation research workflow."""
    summary = client.professor_research_summary()
    st.caption(
        "Review immutable automated observations against student utterances, then "
        "record independent human validation."
    )
    with st.container(key="research_summary"):
        metrics = st.columns(4, gap="small")
        status_counts = summary.get("coding_status") or {}
        with metrics[0]:
            _metric("Active observations", str(summary.get("active_observations", 0)), "in queue")
        with metrics[1]:
            _metric("Coded", str(status_counts.get("coded", 0)), "provisional")
        with metrics[2]:
            _metric("Partial", str(status_counts.get("partial", 0)), "needs review")
        with metrics[3]:
            confidence = summary.get("mean_confidence")
            _metric(
                "Mean evidence confidence",
                "Not available" if confidence is None else f"{float(confidence):.2f}",
                "research signal",
            )
        st.caption(str(summary.get("co_occurrence_note") or ""))
        with st.expander("Post-hoc co-occurrence (not a grade)", expanded=False):
            pairs = summary.get("co_occurrence") or []
            if not pairs:
                st.caption("No co-occurrence counts are available yet.")
            else:
                st.dataframe(
                    [
                        {
                            "Pair": f"{item.get('left')} × {item.get('right')}",
                            "Count": item.get("count", 0),
                        }
                        for item in pairs[:12]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

    with st.container(key="research_filters"):
        filters = st.columns([1.4, 1, 1, 0.8], gap="small")
        with filters[0]:
            search = st.text_input(
                "Search research queue",
                placeholder="Student or notebook",
                key="research_queue_search",
            )
        with filters[1]:
            status = st.selectbox(
                "Coding status",
                ["All", "coded", "partial", "uncoded"],
                format_func=lambda value: value.title(),
                key="research_queue_status",
            )
        phase_options = ["All", *sorted((summary.get("phases") or {}).keys())]
        with filters[2]:
            phase = st.selectbox(
                "Phase", phase_options, key="research_queue_phase"
            )
        with filters[3]:
            if st.button("Prepare CSV", key="research_prepare_export"):
                st.session_state["research_export_csv"] = client.professor_research_export(
                    coding_status=None if status == "All" else status,
                    phase=None if phase == "All" else phase,
                )
            export_data = st.session_state.get("research_export_csv")
            if export_data:
                st.download_button(
                    "Download CSV",
                    data=export_data,
                    file_name="research-observations.csv",
                    mime="text/csv",
                    key="research_download_export",
                )

    queue = client.professor_research_queue(
        search=search,
        coding_status=None if status == "All" else status,
        phase=None if phase == "All" else phase,
        limit=100,
        offset=0,
    )
    items = list(queue.get("items") or [])
    with st.container(key="research_workspace"):
        queue_pane, detail_pane = st.columns([0.72, 2.05], gap="large")
        with queue_pane:
            st.markdown("#### Validation queue")
            st.caption(f"{queue.get('total', 0)} active observation(s)")
            if not items:
                st.info("No research observations match these filters.")
                return
            labels = {
                item["observation_id"]: (
                    f"{item['student_name']} · {str(item.get('phase') or '').replace('_', ' ').title()} "
                    f"· {str(item.get('coding_status') or '').title()}"
                )
                for item in items
            }
            selected_id = st.selectbox(
                "Observation",
                [item["observation_id"] for item in items],
                format_func=lambda value: labels[value],
                key="research_selected_observation",
            )
            selected = next(item for item in items if item["observation_id"] == selected_id)
            st.markdown(
                f"**{selected['student_name']}**\n\n"
                f"{str(selected.get('phase') or '').replace('_', ' ').title()} · "
                f"{str(selected.get('coding_status') or '').title()}"
            )

        detail = client.professor_research_notebook(selected["notebook_id"])
        observations = list(detail.get("observations") or [])
        observation = next(
            (item for item in observations if str(item.get("id")) == selected_id),
            observations[0] if observations else {},
        )
        with detail_pane:
            st.markdown("#### Student transcript")
            student = detail.get("student") or {}
            st.caption(
                f"{student.get('name') or 'Student'} · {detail.get('title') or 'Notebook'}"
            )
            with st.container(key="research_transcript_scroll"):
                for message in detail.get("transcript") or []:
                    speaker = "Student" if message.get("role") == "user" else "Coach"
                    st.markdown(
                        f"**{speaker}** · {_when(message.get('created_at'))}\n\n"
                        f"{message.get('content') or ''}"
                    )
            st.markdown("#### Automated coding")
            if observation:
                _render_research_observation(observation)
                _render_research_validation(client, observation)
            else:
                st.info("No active automated observation is available.")


def render_professor_dashboard() -> None:
    """Render the authorised professor dashboard through FastAPI only.

    The Streamlit view has no direct database, model-provider, or filesystem
    access.  A backend 403/401 remains authoritative if a role changes after
    the navigation has rendered.
    """
    with st.container(key="professor_shell"):
        # Keep the rail close to the 210px reference geometry while allowing
        # the content pane to use the remaining width. The stylesheet stacks
        # these columns at the mobile breakpoint.
        nav_col, content_col = st.columns([0.17, 0.83], gap="small")
        with nav_col:
            page = _render_sidebar()
        with content_col:
            try:
                client = local_api_client()
                selected_student_id = st.session_state.get("professor_selected_student_id")
                selected_notebook_id = (
                    st.session_state.get(f"professor_open_notebook_{selected_student_id}")
                    if selected_student_id
                    else None
                )
                # The selected-notebook workbench supplies its own breadcrumb
                # and header; retain the page header for the roster and all
                # other dashboard pages.
                if not (page == "Students" and selected_notebook_id):
                    _render_page_header(page)
                if page == "Overview":
                    _render_overview(client)
                elif page == "Students":
                    _render_students(client)
                elif page == "Learning":
                    _render_critical_thinking(client)
                elif page == "Engagement":
                    _render_engagement(client)
                else:
                    _render_research(client)
            except Exception:  # noqa: BLE001 - do not expose backend/student data in UI errors
                st.error("Professor analytics is unavailable right now. Please try again shortly.")
