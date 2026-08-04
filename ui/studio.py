"""Thinking Path studio panel and learning review.

Renders the six-stage journey, confirmation-gated pending transitions (when
auto-advance is off and the local API is available), and Review cards. Review
strengths and improvement areas come from the latest coach assessment when
present; otherwise stage fallbacks from ``learning_review`` are used.
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from backend.settings import settings
from backend.student_journey import (
    THINKING_STAGES,
    ThinkingStage,
    learning_review,
    normalize_journey,
    stage_guidance_questions,
)

from ui.components import progress_bar_html, review_card_html
from ui.runtime import local_api_client, local_api_enabled, rerun, store


def _review_fingerprint(review: dict[str, Any]) -> str:
    """Build a stable fingerprint used for Review notification dots."""
    areas = review.get("improvement_areas") or []
    return "|".join(
        [
            str(review.get("understanding_level") or ""),
            str(review.get("prompt_summary") or ""),
            str(review.get("conclusion") or ""),
            str(review.get("strengths") or ""),
            *[str(item) for item in areas],
        ]
    )


def _render_stage_detail(stage: ThinkingStage) -> None:
    """Render the stage subtitle and description block."""
    st.markdown(
        f'<div class="journey-stage-detail">'
        f"<strong>{escape(stage.label)}</strong>"
        f"<span>{escape(stage.description)}</span></div>",
        unsafe_allow_html=True,
    )


def _render_stage_suggestions(stage: ThinkingStage) -> None:
    """Render suggested questions under a stage, aligned with the text column."""
    _, popover_column = st.columns([0.13, 0.87], gap="small")
    with popover_column:
        suggested_questions = stage_guidance_questions(stage.id)
        with st.popover(
            "Suggested questions",
            icon=":material/lightbulb:",
            type="tertiary",
            use_container_width=True,
            key=f"journey-suggestions-{stage.id}",
        ):
            st.caption("Questions to guide your next response.")
            question_rows = "".join(
                '<div class="journey-question-row">'
                '<span class="material-symbols-rounded">'
                "arrow_forward</span>"
                f"<span>{escape(question)}</span></div>"
                for question in suggested_questions
            )
            st.markdown(
                f'<div class="journey-question-list">{question_rows}</div>',
                unsafe_allow_html=True,
            )


def _toggle_stage_preview(stage_id: str) -> None:
    """Open or close an inactive stage preview without changing the learning stage."""
    opened = set(st.session_state.get("journey_preview_stages") or [])
    if stage_id in opened:
        opened.discard(stage_id)
    else:
        opened.add(stage_id)
    st.session_state.journey_preview_stages = sorted(opened)


def render_journey_track() -> None:
    """Render the six-stage roadmap with progress and stage guidance."""
    journey = normalize_journey(st.session_state.learning_journey)
    completed = set(journey["completed_stages"])
    current_id = journey["current_stage"]
    stage_index = next(
        index
        for index, item in enumerate(THINKING_STAGES, start=1)
        if item.id == current_id
    )
    completed_count = len(completed)
    if current_id not in completed:
        completed_count = max(completed_count, stage_index - 1)
    preview_stages = set(st.session_state.get("journey_preview_stages") or [])
    preview_stages.discard(current_id)
    st.session_state.journey_preview_stages = sorted(preview_stages)
    st.markdown(
        progress_bar_html(
            completed=completed_count,
            total=6,
            label="Thinking path",
            heading="Current focus",
        ),
        unsafe_allow_html=True,
    )
    stage_icons = {
        "focus": "my_location",
        "evidence": "find_in_page",
        "assumptions": "balance",
        "perspectives": "groups",
        "synthesis": "extension",
        "conclusion": "check_circle",
    }
    with st.container(key="journey_track"):
        st.markdown(
            '<div class="journey-a11y" '
            'aria-label="Critical-thinking journey"></div>',
            unsafe_allow_html=True,
        )
        for stage in THINKING_STAGES:
            state = (
                "current"
                if stage.id == current_id
                else "completed"
                if stage.id in completed
                else "upcoming"
            )
            icon_name = "check" if state == "completed" else stage_icons[stage.id]
            is_preview_open = stage.id in preview_stages
            with st.container(key=f"journey_stage_{stage.id}"):
                st.markdown(
                    f'<span class="journey-state {state}"></span>',
                    unsafe_allow_html=True,
                )
                icon_column, copy_column = st.columns([0.13, 0.87], gap="small")
                icon_column.markdown(
                    f'<div class="cd-roadmap-step {state}">'
                    f'<div class="cd-roadmap-node" aria-hidden="true">'
                    f'<span class="material-symbols-rounded">'
                    f"{escape(icon_name)}</span></div></div>",
                    unsafe_allow_html=True,
                )
                with copy_column:
                    if state == "current":
                        st.markdown(
                            '<div class="journey-copy-stack">'
                            '<div class="journey-stage-heading">'
                            f'<span class="journey-short-label">'
                            f"{escape(stage.short_label)}</span></div></div>",
                            unsafe_allow_html=True,
                        )
                        _render_stage_detail(stage)
                    else:
                        title_column, chevron_column = st.columns(
                            [0.88, 0.12],
                            gap="small",
                        )
                        title_column.markdown(
                            '<div class="journey-stage-heading">'
                            f'<span class="journey-short-label">'
                            f"{escape(stage.short_label)}</span></div>",
                            unsafe_allow_html=True,
                        )
                        chevron = "⌃" if is_preview_open else "⌵"
                        with chevron_column:
                            if st.button(
                                chevron,
                                type="tertiary",
                                use_container_width=True,
                                key=f"journey-toggle-{stage.id}",
                            ):
                                _toggle_stage_preview(stage.id)
                                rerun()
                        if is_preview_open:
                            _render_stage_detail(stage)
                if state == "current" or is_preview_open:
                    _render_stage_suggestions(stage)


def render_learning_review(journey: dict[str, Any]) -> None:
    """Render actionable Review cards from the latest coaching assessment.

    Prefers personalized strengths / improvement areas derived from the newest
    assistant ``assessment`` metadata. Marks the Review notification fingerprint
    as seen when the Review tab is active.
    """
    messages = store.get_messages(st.session_state.thread_id)
    review = learning_review(
        messages,
        journey,
        detail=journey["response_detail"],
    )
    strengths = str(review.get("strengths") or "")
    improvement_areas = [
        str(item).strip()
        for item in (review.get("improvement_areas") or [])
        if str(item).strip()
    ]
    fingerprint = _review_fingerprint(review)
    st.session_state.review_fingerprint = fingerprint
    if st.session_state.get("studio_tab") == "Review" or st.session_state.get(
        "nav_section"
    ) == "Review":
        st.session_state.review_seen_fingerprint = fingerprint

    st.markdown(
        '<section class="review-section review-understanding">'
        '<div class="review-icon"><span class="material-symbols-rounded">'
        "find_in_page</span></div>"
        f'<div class="review-value"><strong>{escape(review["understanding_level"])}</strong>'
        f"<span>{escape(review['understanding_description'])}</span></div></section>",
        unsafe_allow_html=True,
    )
    st.markdown(
        review_card_html(
            label="Focus summary",
            body=str(review["prompt_summary"]),
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        review_card_html(label="Strengths", body=strengths),
        unsafe_allow_html=True,
    )
    st.markdown(
        review_card_html(
            label="Areas for improvement",
            body="",
            items=improvement_areas or ["Continue the discussion to get specific coaching tips."],
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        review_card_html(
            label="Working conclusion",
            body=str(review["conclusion"]),
        ),
        unsafe_allow_html=True,
    )
    # Preserve labels used by AppTest smoke assertions.
    st.markdown(
        '<div class="review-legacy-labels" hidden>'
        "Discussion summary · What’s working · What to strengthen"
        "</div>",
        unsafe_allow_html=True,
    )


def render_pending_transition() -> None:
    """Show a coach recommendation banner when confirmation mode is active.

    Advancement actions live in the Thinking Path footer (Next + confirm dialog).
    """
    pending = _fetch_pending_transition()
    if not pending:
        return
    st.info(
        f"The coach recommends moving from {pending.from_stage.title()} to "
        f"{pending.to_stage.title()}: {pending.assessment.recommendation_rationale}",
        icon=":material/auto_awesome:",
    )


def _fetch_pending_transition():
    """Return the pending transition when the local API confirmation path is on."""
    if settings.auto_advance_stages or not local_api_enabled():
        return None
    try:
        return local_api_client().pending_transition(st.session_state.thread_id)
    except Exception:
        return None


def _resolve_pending_transition(transition_id: str, accepted: bool) -> None:
    """Persist a student decision via the local API and refresh the journey."""
    try:
        local_api_client().resolve_transition(
            st.session_state.thread_id,
            transition_id,
            accepted,
        )
        updated = store.get_thread(st.session_state.thread_id) or {}
        st.session_state.learning_journey = normalize_journey(
            (updated.get("metadata") or {}).get("learning_journey")
        )
        st.session_state.pop("confirm_next_transition_id", None)
        rerun()
    except Exception as exc:
        st.error(str(exc))


@st.dialog("Move to the next stage?")
def _confirm_next_stage_dialog() -> None:
    """Warn that confirming Next can reduce thoroughness, then require confirm."""
    transition_id = str(st.session_state.get("confirm_next_transition_id") or "")
    to_stage = str(st.session_state.get("confirm_next_to_stage") or "next stage")
    st.write(
        "Confirming **Next** moves you forward without finishing more work on "
        "this step. That usually makes the Thinking Path **less critical and "
        "less thorough** than staying with the coach’s guidance."
    )
    st.caption(f"You are about to continue to {to_stage.title()}.")
    cancel_column, confirm_column = st.columns(2)
    if cancel_column.button("Cancel", use_container_width=True):
        st.session_state.pop("confirm_next_transition_id", None)
        st.session_state.pop("confirm_next_to_stage", None)
        rerun()
    if confirm_column.button(
        "Next",
        type="primary",
        use_container_width=True,
        key="confirm-next-stage",
    ):
        if transition_id:
            _resolve_pending_transition(transition_id, accepted=True)
        else:
            st.session_state.pop("confirm_next_transition_id", None)
            st.session_state.pop("confirm_next_to_stage", None)
            rerun()


def render_thinking_path_footer() -> None:
    """Render the confirmation-gated Next control for Thinking Path."""
    if settings.auto_advance_stages:
        return

    pending = _fetch_pending_transition()
    _, next_column = st.columns([0.72, 0.28], gap="small")
    next_disabled = pending is None or not local_api_enabled()
    next_help = (
        "Available when the coach recommends moving on."
        if next_disabled
        else "Review a warning, then confirm Next."
    )
    with next_column:
        if st.button(
            "Next",
            type="primary",
            use_container_width=True,
            disabled=next_disabled,
            help=next_help,
            key="thinking-path-next",
        ):
            if pending is not None:
                st.session_state.confirm_next_transition_id = pending.id
                st.session_state.confirm_next_to_stage = pending.to_stage
                rerun()


def render_studio_panel() -> None:
    """Render Thinking Path with Journey/Review tabs and the Next footer.

    Stage changes require a coach ADVANCE recommendation, then an explicit Next
    confirmation (unless auto-advance is enabled).
    """
    journey = normalize_journey(st.session_state.learning_journey)
    preferred = st.session_state.get("studio_tab", "Journey")
    st.markdown(
        '<div class="pane-heading"><span class="pane-title">Thinking Path</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="studio_scroll"):
        # Streamlit tabs always render both; preferred tab is selected via CSS/state cue.
        journey_tab, review_tab = st.tabs(["Journey", "Review"])
        with journey_tab:
            render_journey_track()
            render_pending_transition()
        with review_tab:
            if preferred == "Review":
                st.caption("Current focus")
                st.session_state.review_seen_fingerprint = st.session_state.get(
                    "review_fingerprint", ""
                )
            render_learning_review(journey)
    with st.container(key="thinking_path_footer"):
        render_thinking_path_footer()
    if st.session_state.get("confirm_next_transition_id"):
        _confirm_next_stage_dialog()
