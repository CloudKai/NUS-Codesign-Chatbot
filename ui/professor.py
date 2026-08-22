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
    progress_bar_html,
    review_card_html,
    review_stage_sections_html,
)
from ui.runtime import local_api_client

_PAGES = ("Overview", "Students", "Learning Progress", "Engagement", "Research Review")
_PHASE_LABELS = tuple(stage.label.title() for stage in THINKING_STAGES)
_WORKSPACE_TABS = ("Chat", "Sources", "Journey", "Review")
_ROSTER_CACHE_KEY = "professor_roster_cache"
_DETAIL_CACHE_KEY = "professor_student_detail_cache"
_WORKSPACE_CACHE_KEY = "professor_workspace_cache"


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


def _cached_professor_workspace(
    client: Any, student_id: str, notebook_id: str
) -> dict[str, Any]:
    """Fetch or reuse one notebook workspace payload."""
    cache = st.session_state.setdefault(_WORKSPACE_CACHE_KEY, {})
    key = (student_id, notebook_id)
    if key not in cache:
        cache[key] = client.professor_notebook_workspace(student_id, notebook_id)
    return cache[key]


def _clear_professor_workspace_cache(student_id: str, notebook_id: str | None = None) -> None:
    """Drop cached workspace payloads after navigation changes."""
    cache = st.session_state.get(_WORKSPACE_CACHE_KEY) or {}
    if notebook_id is None:
        for key in list(cache):
            if key[0] == student_id:
                cache.pop(key, None)
        return
    cache.pop((student_id, notebook_id), None)


def _invalidate_student_detail_cache(student_id: str) -> None:
    """Drop one student's cached detail and workspace payloads."""
    detail_cache = st.session_state.get(_DETAIL_CACHE_KEY) or {}
    detail_cache.pop(student_id, None)
    _clear_professor_workspace_cache(student_id)


def _invalidate_workspace_cache(student_id: str, notebook_id: str) -> None:
    """Drop one notebook workspace cache entry."""
    workspace_cache = st.session_state.get(_WORKSPACE_CACHE_KEY) or {}
    workspace_cache.pop((student_id, notebook_id), None)


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


def _notebook_card_caption(item: dict[str, Any]) -> str:
    """Render notebook metadata beneath the title."""
    total_messages = int(item.get("messages") or 0)
    student_messages = int(item.get("student_messages") or 0)
    coach_messages = max(total_messages - student_messages, 0)
    return (
        f"{item.get('stage') or 'Not started'} · "
        f"{student_messages} student · {coach_messages} coach · "
        f"{_when(item.get('last_active'))}"
    )


def _student_card_caption(row: dict[str, Any]) -> str:
    """Render compact roster metadata beneath the student name."""
    attention = " · Needs attention" if row.get("needs_attention") else ""
    return (
        f"{row.get('current_stage') or 'Not started'} · "
        f"{_when(row.get('last_active'))}{attention}"
    )


def _when(value: str | None) -> str:
    """Render an ISO time compactly while retaining a clear missing state."""
    if not value:
        return "No activity"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b, %H:%M")
    except ValueError:
        return value


def _render_header() -> str:
    """Render the course identity and restrained analytics navigation."""
    with st.container(key="professor_header"):
        heading, navigation = st.columns([1.55, 1], gap="large")
        heading.markdown(
            """
            <div class="professor-course-heading">
              <p class="professor-eyebrow">Course Analytics</p>
              <h1>CDE2300 · Product Design and Innovation</h1>
              <p>Class learning activity and critical-thinking progress</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with navigation:
            page = st.radio(
                "Professor dashboard navigation",
                _PAGES,
                horizontal=True,
                label_visibility="collapsed",
                key="professor_page",
            )
            logout_url = app_logout_url()
            professor_name = escape(
                str(st.session_state.get("display_name") or "Teaching staff")
            )
            if logout_url:
                navigation.markdown(
                    '<div class="professor-account">'
                    f"<span>{professor_name}</span>"
                    f'<a href="{escape(logout_url, quote=True)}" target="_self" '
                    'rel="noopener">Sign out</a></div>',
                    unsafe_allow_html=True,
                )
            elif st.button("Sign out", key="professor_sign_out", type="tertiary"):
                logout_user()
    return page


def _metric(label: str, value: str, detail: str = "") -> None:
    """Render a compact metric with supporting context instead of a hero card."""
    st.markdown(
        '<div class="professor-metric">'
        f"<p>{escape(label)}</p><strong>{escape(value)}</strong>"
        f"<span>{escape(detail)}</span></div>",
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
    """Render deterministic attention reasons in a low-emphasis roster table."""
    if not rows:
        st.caption("No current follow-up signals under the configured academic thresholds.")
        return
    display = []
    for row in rows:
        reasons = "; ".join(signal["reason"] for signal in row.get("needs_attention", []))
        display.append(
            {
                "Student": row["name"],
                "Reason": reasons,
                "Stage": row.get("current_stage") or "Not started",
                "Score": _score(row.get("facione_overall")),
                "Last active": _when(row.get("last_active")),
            }
        )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={"Reason": st.column_config.TextColumn(width="large")},
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
    st.caption(f"Last updated {updated}")
    metrics = st.columns(5, gap="small")
    with metrics[0]:
        _metric("Students", str(data["students"]))
    with metrics[1]:
        _metric(
            "Active this week",
            f"{data['active_students_week']} / {data['students']}",
        )
    with metrics[2]:
        _metric(
            "Assessed students",
            str(data["median_facione"].get("sample_size", 0)),
            "Latest critical-thinking indicator"
            if data["median_facione"].get("sample_size", 0)
            else "Not assessed yet",
        )
    with metrics[3]:
        _metric("Median stage", data.get("median_stage") or "Not started")
    with metrics[4]:
        _metric(
            "Students needing attention",
            str(data.get("attention_students_count", len(data.get("attention_students", [])))),
        )
    summary = escape(str(data.get("summary") or "No class summary is available yet."))
    st.markdown(
        f'<div class="professor-summary">{summary}</div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        st.markdown("#### Current thinking stage")
        st.caption("Students are counted at the most recently active notebook stage.")
        stages = [
            {**item, "display": f"{item['count']} · {item['percentage']:g}%"}
            for item in data.get("stage_distribution", [])
        ]
        _bar_rows(stages, value_key="count", display_key="display")
    with right:
        st.markdown("#### Follow-up queue")
        st.caption("Deterministic follow-up signals, not judgements of ability.")
        _attention_table(data.get("attention_students", []))
    st.markdown("#### Activity over time")
    activity = data.get("weekly_activity", [])
    if activity:
        _line_chart(
            activity, x="week", y="active_students",
            x_label="Week", y_label="Active students",
        )
    else:
        st.info("Weekly activity will appear after students begin using the coach.")


def _render_students(client) -> None:
    """Render a progressive roster → student → notebook workspace."""
    st.markdown("### Students")
    st.caption("Start with a lightweight roster. Select one student to load their learning record.")
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

    selected_id = st.session_state.get("professor_selected_student_id", "")
    opened_notebook = None
    if selected_id:
        opened_notebook = st.session_state.get(f"professor_open_notebook_{selected_id}")

    workspace_class = (
        "professor-students-workspace professor-mobile-detail"
        if selected_id
        else "professor-students-workspace"
    )
    st.markdown(f'<div class="{workspace_class}"></div>', unsafe_allow_html=True)

    with st.container(key="professor_students_workspace"):
        list_col, detail_col = st.columns([0.82, 1.8], gap="large")
        with list_col:
            st.markdown("#### Student list")
            st.caption(f"{len(rows)} student{'s' if len(rows) != 1 else ''}")
            for row in rows:
                student_id = str(row.get("id") or "")
                is_selected = student_id == selected_id
                card_class = "professor-student-card professor-student-card-selected" if is_selected else "professor-student-card"
                with st.container(key=f"professor_student_card_{student_id}"):
                    st.markdown(
                        f'<div class="{card_class}">'
                        f'<div class="professor-student-card-name">'
                        f"{escape(str(row.get('name') or 'Student'))}"
                        f'<span class="professor-student-card-chevron">›</span></div>'
                        f'<div class="professor-student-card-meta">'
                        f"{escape(_student_card_caption(row))}</div></div>",
                        unsafe_allow_html=True,
                    )
                    label = "Selected" if is_selected else "Open"
                    if st.button(
                        label,
                        key=f"professor_open_student_{student_id}",
                        use_container_width=True,
                    ):
                        st.session_state["professor_selected_student_id"] = student_id
                        st.session_state.pop(f"professor_open_notebook_{student_id}", None)
                        _clear_professor_workspace_cache(student_id)
                        st.rerun()
        with detail_col:
            if not selected_id:
                st.info("Select a student to view their learning progress and notebooks.")
            else:
                if opened_notebook:
                    if st.button(
                        "← Back to notebooks",
                        key=f"professor_back_notebooks_{selected_id}",
                    ):
                        st.session_state.pop(f"professor_open_notebook_{selected_id}", None)
                        _clear_professor_workspace_cache(selected_id, opened_notebook)
                        st.rerun()
                elif st.button(
                    "← Students",
                    key=f"professor_back_students_{selected_id}",
                ):
                    st.session_state.pop("professor_selected_student_id", None)
                    st.session_state.pop(f"professor_open_notebook_{selected_id}", None)
                    _clear_professor_workspace_cache(selected_id)
                    st.rerun()
                detail = _cached_professor_student_detail(client, selected_id)
                if opened_notebook:
                    workspace = _cached_professor_workspace(
                        client, selected_id, opened_notebook
                    )
                    notebook_summary = next(
                        (
                            item
                            for item in detail.get("notebooks", [])
                            if item.get("id") == opened_notebook
                        ),
                        {},
                    )
                    _render_professor_workspace(
                        client, selected_id, workspace, notebook_summary
                    )
                else:
                    _render_student_detail(client, detail, show_back=False)


def _render_student_detail(
    client: Any, data: dict[str, Any], *, show_back: bool = True
) -> None:
    """Render one selected student's record and notebook cards."""
    student = data["student"]
    header = st.columns([0.82, 0.18], gap="small")
    with header[0]:
        st.markdown(f"### {student['name']}")
        st.caption(student.get("email") or "Authorised student record")
    with header[1]:
        if st.button(
            "Refresh",
            key=f"professor_refresh_student_{student['id']}",
            use_container_width=True,
        ):
            _invalidate_student_detail_cache(student["id"])
            st.rerun()
    metrics = st.columns(4, gap="small")
    with metrics[0]:
        _metric("Current stage", student.get("current_stage") or "Not started")
    with metrics[1]:
        _metric("Progress", f"{student.get('stage_progress', 0)} / {len(_PHASE_LABELS)}")
    with metrics[2]:
        _metric("Last active", _when(student.get("last_active")))
    with metrics[3]:
        _metric("Attention", "Yes" if student.get("needs_attention") else "No")

    opened = st.session_state.get(f"professor_open_notebook_{student['id']}")
    if not opened:
        st.markdown("#### Notebooks")
        notebooks = data.get("notebooks", [])
        if not notebooks:
            st.info("This student has not started a notebook yet.")
        else:
            for item in notebooks:
                notebook_id = str(item.get("id") or "")
                with st.container(key=f"professor_notebook_card_{student['id']}_{notebook_id}"):
                    st.markdown(
                        f'<div class="professor-notebook-card">'
                        f'<div class="professor-notebook-card-title">'
                        f"{escape(_notebook_card_label(item))}</div>"
                        f'<div class="professor-notebook-card-stage">'
                        f"{escape(str(item.get('stage') or 'Not started'))}</div>"
                        f'<div class="professor-notebook-card-meta">'
                        f"{escape(_notebook_card_caption(item))}</div></div>",
                        unsafe_allow_html=True,
                    )
                    if st.button(
                        "Open →",
                        key=f"professor_open_notebook_btn_{student['id']}_{notebook_id}",
                        use_container_width=True,
                    ):
                        st.session_state[f"professor_open_notebook_{student['id']}"] = notebook_id
                        _clear_professor_workspace_cache(student["id"], notebook_id)
                        st.rerun()
        if not notebooks:
            return

    st.markdown("#### Learning journey")
    completed = set(data.get("completed_stages", []))
    steps = []
    for stage in _PHASE_LABELS:
        status = "completed" if stage in completed else "current" if stage == student.get("current_stage") else "future"
        marker = "✓" if status == "completed" else "●" if status == "current" else "○"
        steps.append(f'<span class="professor-step professor-step-{status}"><b>{marker}</b> {escape(stage)}</span>')
    st.markdown(f'<div class="professor-progress">{"".join(steps)}</div>', unsafe_allow_html=True)
    reasons = student.get("needs_attention") or []
    if reasons:
        st.caption("Needs attention: " + "; ".join(item.get("reason", "") for item in reasons))

    overview_left, overview_right = st.columns(2, gap="large")
    with overview_left:
        st.markdown("#### Critical-thinking profile")
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

    if opened:
        return


def _workspace_notebook(workspace: dict[str, Any], notebook: dict[str, Any]) -> dict[str, Any]:
    """Return notebook header metadata from the workspace or detail fallback."""
    header = workspace.get("notebook") or {}
    if header:
        return header
    return {
        "id": notebook.get("id"),
        "title": notebook.get("title"),
        "current_stage": notebook.get("stage"),
        "last_active": notebook.get("last_active"),
    }


def _render_professor_workspace(
    client: Any,
    student_id: str,
    workspace: dict[str, Any],
    notebook: dict[str, Any],
) -> None:
    """Render the read-only Chat, Sources, Journey, and Review tabs."""
    notebook_meta = _workspace_notebook(workspace, notebook)
    transcript = workspace.get("transcript") or {}
    header = st.columns([0.82, 0.18], gap="small")
    with header[0]:
        st.markdown(
            f"#### {notebook_meta.get('title') or _notebook_card_label(notebook)}"
        )
        st.caption(
            f"{notebook_meta.get('current_stage') or notebook.get('stage') or 'Not started'} · "
            f"Last active {_when(notebook_meta.get('last_active') or notebook.get('last_active'))} · "
            "Read-only workspace · active conversation branch"
        )
    with header[1]:
        notebook_id = str(notebook_meta.get("id") or "")
        if st.button(
            "Refresh",
            key=f"professor_refresh_workspace_{student_id}_{notebook_id}",
            use_container_width=True,
        ):
            _invalidate_workspace_cache(student_id, notebook_id)
            st.rerun()
    tab = st.radio(
        "Notebook workspace",
        _WORKSPACE_TABS,
        horizontal=True,
        key=f"professor_workspace_tab_{student_id}_{notebook_meta.get('id')}",
        label_visibility="collapsed",
    )
    if tab == "Chat":
        authorized_sources = {
            str(source.get("id") or ""): source
            for source in workspace.get("sources") or []
            if str(source.get("id") or "").strip()
        }
        _render_professor_chat_tab(
            client,
            student_id,
            str(notebook_meta.get("id") or ""),
            transcript,
            authorized_sources,
        )
    elif tab == "Sources":
        _render_professor_sources_tab(
            client, student_id, str(notebook_meta.get("id") or ""), workspace
        )
    elif tab == "Journey":
        _render_professor_journey_tab(workspace)
    else:
        _render_professor_review_tab(workspace)


def _render_professor_chat_tab(
    client: Any,
    student_id: str,
    notebook_id: str,
    transcript: dict[str, Any],
    authorized_sources: dict[str, dict[str, Any]],
) -> None:
    """Render the active-branch transcript inside a scroll region."""
    messages = transcript.get("messages") or []
    if not messages:
        st.caption("No conversation has been recorded in this notebook.")
        return
    with st.container(key="professor_transcript_scroll"):
        for message in messages:
            role = str(message.get("role") or "")
            speaker = "Student" if role == "user" else "Coach"
            role_class = "student" if role == "user" else "coach"
            with st.container(
                key=f"professor_message_{message.get('id') or message.get('created_at')}"
            ):
                st.markdown(
                    f'<div class="professor-chat-card professor-chat-{role_class}">'
                    f'<div class="professor-chat-meta"><strong>{escape(speaker)}</strong>'
                    f"<span>{escape(_when(message.get('created_at')))}</span></div></div>",
                    unsafe_allow_html=True,
                )
                content = str(message.get("content") or "")
                if content:
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
                            authorized_sources,
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
                "Open →",
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
    authorized_sources: dict[str, dict[str, Any]],
) -> None:
    """Render one citation row, opening sources only when authorized."""
    citation_id = str(citation.get("id") or "").strip()
    label = str(citation.get("label") or citation_id or "source").strip()
    title = str(citation.get("title") or label or "Source").strip()
    display = f"[{label}] {title}" if label and title != label else f"[{label}]"
    source = authorized_sources.get(citation_id)
    row = st.columns([0.78, 0.22], gap="small")
    with row[0]:
        st.caption(display)
    with row[1]:
        if (
            citation_id
            and source
            and source.get("has_file")
            and hasattr(client, "professor_notebook_source")
        ):
            if st.button(
                "Open →",
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
    workspace: dict[str, Any],
) -> None:
    """Render grouped library sources without upload or selection controls."""
    sources = list(workspace.get("sources") or [])
    grouped: dict[str, list[dict[str, Any]]] = {group: [] for group in COURSE_MATERIAL_GROUPS}
    grouped["My Sources"] = []
    for source in sources:
        group = str(source.get("group") or "My Sources")
        grouped.setdefault(group, []).append(source)
    with st.expander(f"My Sources · {len(grouped['My Sources'])}", expanded=True):
        if grouped["My Sources"]:
            for source in grouped["My Sources"]:
                _render_professor_source_row(client, student_id, notebook_id, source)
        else:
            st.caption("No personal sources in this notebook.")
    for group in COURSE_MATERIAL_GROUPS:
        group_sources = grouped.get(group) or []
        with st.expander(f"{group} · {len(group_sources)}", expanded=False):
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
                "Open →",
                key=f"professor_source_{notebook_id}_{source_id}",
                use_container_width=True,
            ):
                _professor_source_dialog(client, student_id, notebook_id, source_id, title)


def _render_professor_journey_tab(workspace: dict[str, Any]) -> None:
    """Render the Thinking Path and optional HMW scaffold read-only."""
    learning = workspace.get("learning") or {}
    journey = normalize_journey(learning.get("journey") or learning.get("learning_journey"))
    completed = set(journey.get("completed_stages") or [])
    current_id = str(journey.get("current_stage") or THINKING_STAGES[0].id)
    stage_index = next(
        index
        for index, item in enumerate(THINKING_STAGES, start=1)
        if item.id == current_id
    )
    completed_count = len(completed)
    if current_id not in completed:
        completed_count = max(completed_count, stage_index - 1)
    st.markdown(
        progress_bar_html(
            completed=completed_count,
            total=len(THINKING_STAGES),
            label="Thinking path",
            heading="Current focus",
        ),
        unsafe_allow_html=True,
    )
    for stage in THINKING_STAGES:
        state = (
            "current"
            if stage.id == current_id
            else "completed"
            if stage.id in completed
            else "future"
        )
        marker = "✓" if state == "completed" else "●" if state == "current" else "○"
        st.markdown(
            f'<span class="professor-step professor-step-{state}">'
            f"<b>{marker}</b> {escape(stage.label)}</span>",
            unsafe_allow_html=True,
        )
    hmw = learning.get("hmw_scaffold") or {}
    if hmw.get("available"):
        render_hmw_scaffold()


def _render_professor_review_tab(workspace: dict[str, Any]) -> None:
    """Render the Review projection without Deep Review controls."""
    learning = workspace.get("learning") or {}
    review = dict(learning.get("review") or {})
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
    st.markdown("#### Stage distribution")
    st.caption("Students are counted at the most recently active notebook stage.")
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
    st.markdown("#### Critical-thinking class profile")
    st.caption(
        "Medians use each student’s latest assessed response; not-started "
        "dimensions are excluded."
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
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Score distribution")
        _bar_rows(
            data.get("distribution", []),
            value_key="count",
            label_key="band",
            suffix=" students",
        )
    with right:
        st.markdown("#### Stage and score")
        st.caption(
            "Displayed only when at least three students are in a stage; this "
            "does not imply causality."
        )
        comparisons = [
            {**item, "display": f"{item['median']:.1f} / 4 · n={item['sample_size']}"}
            for item in data.get("stage_comparison", [])
        ]
        _bar_rows(
            comparisons, value_key="median", fixed_maximum=4, display_key="display"
        )
    if data.get("trend"):
        st.markdown("#### Assessment trend")
        _line_chart(
            data["trend"], x="date", y="median",
            x_label="Date", y_label="Median score (0–4)", y_domain=(0, 4),
        )


def _render_engagement(client) -> None:
    """Render meaningful usage patterns without rewarding high message volume."""
    data = client.professor_engagement()
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("#### Weekly active students")
        weekly = data.get("weekly_active_students", [])
        if weekly:
            _line_chart(
                weekly, x="week", y="active_students",
                x_label="Week", y_label="Active students",
            )
        else:
            st.info("No student activity has been recorded yet.")
    with right:
        st.markdown("#### Student messages by week")
        weekly_messages = data.get("weekly_messages", [])
        if weekly_messages:
            _line_chart(
                weekly_messages, x="week", y="student_messages",
                x_label="Week", y_label="Student messages",
            )
    st.markdown("#### Activity distribution")
    distribution, time = st.columns(2, gap="large")
    with distribution:
        _bar_rows(
            data.get("active_day_distribution", []),
            value_key="students",
            label_key="days",
            suffix=" students",
        )
    with time:
        _bar_rows(
            data.get("estimated_active_time_distribution", []),
            value_key="students",
            label_key="band",
            suffix=" students",
        )
    st.caption(data.get("definition", ""))
    st.markdown("#### Source-grounded coaching")
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
    st.markdown("#### Recently inactive students")
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
    st.markdown("### Research Review")
    st.caption(
        "Review immutable automated observations against student utterances, then "
        "record independent human validation."
    )
    metrics = st.columns(4, gap="small")
    status_counts = summary.get("coding_status") or {}
    with metrics[0]:
        _metric("Active observations", str(summary.get("active_observations", 0)))
    with metrics[1]:
        _metric("Coded", str(status_counts.get("coded", 0)))
    with metrics[2]:
        _metric("Partial", str(status_counts.get("partial", 0)))
    with metrics[3]:
        confidence = summary.get("mean_confidence")
        _metric(
            "Mean evidence confidence",
            "Not available" if confidence is None else f"{float(confidence):.2f}",
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
    page = _render_header()
    try:
        client = local_api_client()
        if page == "Overview":
            _render_overview(client)
        elif page == "Students":
            _render_students(client)
        elif page == "Learning Progress":
            _render_critical_thinking(client)
        elif page == "Engagement":
            _render_engagement(client)
        else:
            _render_research(client)
    except Exception:  # noqa: BLE001 - do not expose backend/student data in UI errors
        st.error("Professor analytics is unavailable right now. Please try again shortly.")
