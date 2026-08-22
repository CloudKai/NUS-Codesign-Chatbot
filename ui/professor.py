"""Professor-facing learning analytics rendered solely from the FastAPI client."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from backend.student_journey import THINKING_STAGES
from ui.auth_gate import app_logout_url, logout_user
from ui.runtime import local_api_client

_PAGES = ("Overview", "Students", "Learning Progress", "Engagement", "Research Review")
_PHASE_LABELS = tuple(stage.label.title() for stage in THINKING_STAGES)


def _score(value: Any) -> str:
    """Render a nullable Facione value without fabricating a zero score."""
    return "Not assessed" if value is None else f"{float(value):.1f} / 4"


def _notebook_label(item: dict[str, Any]) -> str:
    """Render a compact notebook choice with total and student message counts."""
    return (
        f"{item['title']} · {item.get('stage') or 'Not started'} · "
        f"{item.get('messages', 0)} total messages · "
        f"{item.get('student_messages', 0)} student messages · {_when(item.get('last_active'))}"
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
    data = client.professor_students(
        search=search,
        stage=None if stage == "All" else stage,
        attention_only=attention == "Needs attention",
    )
    rows = data.get("students", [])
    if not rows:
        st.info("No students match these filters.")
        return
    labels = {"": "Select a student"}
    labels.update({
        row["id"]: (
            f"{row['name']} · {row.get('current_stage') or 'Not started'} · "
            f"{_when(row.get('last_active'))}"
            + (" · Needs attention" if row.get("needs_attention") else "")
        )
        for row in rows
    })
    with st.container(key="professor_students_workspace"):
        list_col, detail_col = st.columns([0.82, 1.8], gap="large")
        with list_col:
            st.markdown("#### Student list")
            st.caption(f"{len(rows)} student{'s' if len(rows) != 1 else ''}")
            selected_id = st.radio(
                "Select a student", [""] + [row["id"] for row in rows],
                format_func=lambda value: labels[value],
                key="professor_selected_student", label_visibility="collapsed",
            )
        with detail_col:
            if selected_id:
                _render_student_detail(client, client.professor_student_detail(selected_id))
            else:
                st.info("Select a student to view their learning progress and notebooks.")


def _render_student_detail(client: Any, data: dict[str, Any]) -> None:
    """Render one selected student's record and one optional active transcript."""
    student = data["student"]
    st.markdown(f"### {student['name']}")
    st.caption(student.get("email") or "Authorised student record")
    metrics = st.columns(4, gap="small")
    with metrics[0]:
        _metric("Current stage", student.get("current_stage") or "Not started")
    with metrics[1]:
        _metric("Progress", f"{student.get('stage_progress', 0)} / {len(_PHASE_LABELS)}")
    with metrics[2]:
        _metric("Last active", _when(student.get("last_active")))
    with metrics[3]:
        _metric("Attention", "Yes" if student.get("needs_attention") else "No")

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

    opened = st.session_state.get(f"professor_open_notebook_{student['id']}")
    if opened:
        if st.button("← Back to notebooks", key=f"professor_back_notebooks_{student['id']}"):
            st.session_state.pop(f"professor_open_notebook_{student['id']}", None)
            st.rerun()
        notebook_summary = next((item for item in data.get("notebooks", []) if item.get("id") == opened), {})
        transcript = client.professor_conversation_transcript(student["id"], opened)
        _render_professor_transcript(client, student["id"], transcript, notebook_summary)
        return

    st.markdown("#### Notebooks")
    notebooks = data.get("notebooks", [])
    if not notebooks:
        st.info("This student has not started a notebook yet.")
        return
    notebook_labels = {item["id"]: _notebook_label(item) for item in notebooks}
    selected_notebook = st.radio(
        "Select a notebook", [item["id"] for item in notebooks],
        format_func=lambda value: notebook_labels[value],
        key=f"professor_selected_notebook_{student['id']}",
        label_visibility="collapsed",
    )
    st.button(
        "View active transcript",
        key=f"professor_view_transcript_{student['id']}",
        on_click=_open_professor_notebook,
        args=(student["id"], selected_notebook),
    )


def _open_professor_notebook(student_id: str, notebook_id: str) -> None:
    """Persist the lecturer's selected notebook after an explicit view click."""
    st.session_state[f"professor_open_notebook_{student_id}"] = notebook_id


def _render_professor_transcript(
    client: Any,
    student_id: str,
    transcript: dict[str, Any],
    notebook: dict[str, Any],
) -> None:
    """Render one active-branch transcript as readable message cards."""
    st.markdown(f"#### {transcript.get('title') or notebook.get('title') or 'Notebook'}")
    st.caption(
        f"{transcript.get('stage') or notebook.get('stage') or 'Not started'} · "
        f"Last active {_when(transcript.get('last_active') or notebook.get('last_active'))} · "
        "Active conversation branch · superseded revisions are excluded"
    )
    messages = transcript.get("messages") or []
    if not messages:
        st.caption("No conversation has been recorded in this notebook.")
        return
    for message in messages:
        speaker = "Student" if message.get("role") == "user" else "Coach"
        with st.container(key=f"professor_message_{message.get('id') or message.get('created_at')}"):
            st.markdown(f"**{speaker}** · {_when(message.get('created_at'))}")
            st.markdown(message.get("content") or "")
            for attachment in message.get("attachments") or []:
                attachment_id = str(attachment.get("id") or "")
                title = escape(str(attachment.get("title") or "Attachment"))
                st.caption(f"📎 {title}")
                if attachment_id and hasattr(client, "professor_conversation_attachment"):
                    if st.button("Open attachment", key=f"professor_attachment_{message.get('id')}_{attachment_id}"):
                        _professor_attachment_dialog(
                            client, student_id, transcript["notebook_id"], attachment_id, title
                        )
            citations = message.get("citations") or []
            if citations:
                st.caption("Cited source reference(s): " + ", ".join(_citation_display(item) for item in citations))
            st.divider()


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
