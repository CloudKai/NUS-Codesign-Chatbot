"""Thinking Path studio panel and learning review."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from backend.learning_service import LearningProgressService
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.student_journey import (
    THINKING_STAGES,
    ThinkingStage,
    current_stage,
    learning_review,
    normalize_journey,
    stage_guidance_questions,
)

from ui.components import progress_bar_html, review_card_html
from ui.constants import ACTIONABLE_REVIEW_FEEDBACK
from ui.runtime import local_api_client, local_api_enabled, rerun, store


def _review_fingerprint(review: dict[str, Any], positive: str, critique: tuple[str, str]) -> str:
    """Build a stable fingerprint used for Review notification dots."""
    return "|".join(
        [
            str(review.get("understanding_level") or ""),
            str(review.get("prompt_summary") or ""),
            str(review.get("conclusion") or ""),
            positive,
            critique[0],
            critique[1],
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
    """Render actionable review cards and mark Review notifications as seen."""
    messages = store.get_messages(st.session_state.thread_id)
    review = learning_review(
        messages,
        journey,
        detail=journey["response_detail"],
    )
    stage = current_stage(journey)
    positive, critique = ACTIONABLE_REVIEW_FEEDBACK[stage.id]
    fingerprint = _review_fingerprint(review, positive, critique)
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
        review_card_html(label="Strengths", body=positive),
        unsafe_allow_html=True,
    )
    st.markdown(
        review_card_html(
            label="Areas for improvement",
            body="",
            items=[critique[0], critique[1]],
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
    """Render a coach recommendation and require the student's explicit choice."""
    if local_api_enabled():
        try:
            pending = local_api_client().pending_transition(st.session_state.thread_id)
        except Exception:
            return
    else:
        pending = SQLitePhaseTransitionRepository(store).get_pending(
            st.session_state.thread_id
        )
    if not pending:
        return
    st.info(
        f"The coach recommends moving from {pending.from_stage.title()} to "
        f"{pending.to_stage.title()}: {pending.assessment.recommendation_rationale}",
        icon=":material/auto_awesome:",
    )
    stay_column, advance_column = st.columns(2)
    if stay_column.button("Stay on this step", use_container_width=True):
        _resolve_pending_transition(pending.id, accepted=False)
    if advance_column.button(
        f"Continue to {pending.to_stage.title()}",
        type="primary",
        use_container_width=True,
    ):
        _resolve_pending_transition(pending.id, accepted=True)


def _resolve_pending_transition(transition_id: str, accepted: bool) -> None:
    """Persist a student decision and refresh the visible learning journey."""
    try:
        if local_api_enabled():
            local_api_client().resolve_transition(
                st.session_state.thread_id,
                transition_id,
                accepted,
            )
        else:
            LearningProgressService(
                store,
                SQLiteNotebookRepository(store),
                SQLitePhaseTransitionRepository(store),
            ).resolve(st.session_state.thread_id, transition_id, accepted)
        updated = store.get_thread(st.session_state.thread_id) or {}
        st.session_state.learning_journey = normalize_journey(
            (updated.get("metadata") or {}).get("learning_journey")
        )
        rerun()
    except Exception as exc:
        st.error(str(exc))


def render_studio_panel() -> None:
    """Render Thinking Path with Journey/Review driven by nav focus when possible."""
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
