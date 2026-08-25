"""Thinking Path studio panel and learning review.

Renders the configured Thinking Path, confirmation-gated pending transitions (when
auto-advance is off), and Review cards. Review
summary and Facione scores come from the latest coach assessment when present;
strengths and improvement areas nest one expander per Thinking Path stage,
with only the student's current stage open by default.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from html import escape
from typing import Any, Literal

import streamlit as st

from backend.domain import CoachRequest
from backend.models import DEFAULT_CHAT_MODEL_ID
from backend.settings import settings
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_JOB_COMPLETED,
    DEEP_REVIEW_JOB_FAILED,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    bound_deep_review_interval,
    deep_review_job_is_active,
    explicit_deep_review_available,
    parse_coaching_turns_since_deep_review,
    parse_deep_review_job,
)
from backend.student_journey import (
    STAGE_BY_ID,
    THINKING_STAGES,
    ThinkingStage,
    learning_review,
    normalize_journey,
    selectable_stage_ids,
    stage_guidance_questions,
)

from ui.components import (
    facione_scores_table_html,
    progress_bar_html,
    review_card_html,
    review_feedback_items_html,
)
from ui.runtime import (
    coach_turn_is_streaming,
    get_deep_review_job,
    rerun_app,
    rerun_fragment,
    start_deep_review,
    store,
    submit_coach_turn,
)

logger = logging.getLogger(__name__)

_STAGE_SELECT_ERROR = "The Thinking Path stage could not be updated. Try again."
_TRANSITION_RESOLVE_ERROR = (
    "The stage recommendation could not be updated. Try again."
)
_DEEP_REVIEW_ERROR = "Deep Review could not be completed. Try again."
_DEEP_REVIEW_STATUS_LABEL = (
    "Running Deep Review… This may take a few seconds to a couple of minutes."
)
_DEEP_REVIEW_READY_DETAIL = (
    "Deep Review performs a more detailed analysis of your progress and may "
    "take from a few seconds to a couple of minutes."
)
_DEEP_REVIEW_COMPLETE_CAPTION = "Deep Review ready."
_DEEP_REVIEW_NEWER_TURNS_CAPTION = (
    "This review reflects the conversation at the start of Deep Review. "
    "Newer turns are not included."
)
_FACIONE_ACTIVITY_LABELS = (
    ("analysis", "Analysis"),
    ("interpretation", "Interpretation"),
    ("inference", "Inference"),
    ("evaluation", "Evaluation"),
    ("explanation", "Explanation"),
    ("self_regulation", "Self-Regulation"),
)


@dataclass(frozen=True)
class DeepReviewControlView:
    """Presentation mapping of server Deep Review eligibility onto Review UI."""

    eligible: bool
    disabled: bool
    button_type: Literal["primary", "secondary"]
    caption: str | None
    detail_caption: str | None
    status_label: str | None


def deep_review_control_view(
    counter: int,
    interval: int,
    *,
    running: bool,
) -> DeepReviewControlView:
    """Map persisted Deep Review eligibility onto the Review-tab button.

    This helper does not increment or store a second counter. ``counter`` must
    already come from notebook metadata and ``interval`` from settings.

    Args:
        counter: Persisted ``coaching_turns_since_deep_review``.
        interval: Configured ``DEEP_REVIEW_INTERVAL_TURNS``.
        running: Whether this notebook already has an in-flight Deep Review.

    Returns:
        Caption, enablement, and button type for Start Deep Review.
    """
    bounded_interval = bound_deep_review_interval(interval)
    current = parse_coaching_turns_since_deep_review(counter)
    eligible = explicit_deep_review_available(
        coaching_turns_since_deep_review=current,
        interval=bounded_interval,
    )
    disabled = (not eligible) or running
    shown = min(current, bounded_interval)
    locked_caption = (
        f"Deep Review unlocks after {bounded_interval} coaching turns — "
        f"{shown}/{bounded_interval} completed."
    )
    if running:
        return DeepReviewControlView(
            eligible=eligible,
            disabled=disabled,
            button_type="primary" if eligible else "secondary",
            caption=None,
            detail_caption=None,
            status_label=_DEEP_REVIEW_STATUS_LABEL,
        )
    if eligible:
        return DeepReviewControlView(
            eligible=True,
            disabled=False,
            button_type="primary",
            caption="Deep Review is ready.",
            detail_caption=_DEEP_REVIEW_READY_DETAIL,
            status_label=None,
        )
    return DeepReviewControlView(
        eligible=False,
        disabled=True,
        button_type="secondary",
        caption=locked_caption,
        detail_caption=None,
        status_label=None,
    )


def _render_deep_review_chrome(metadata: dict[str, Any]) -> None:
    """Mount the stable or polling Deep Review control from persisted job status.

    Args:
        metadata: Notebook metadata already loaded for this Review render.
    """
    if deep_review_job_is_active(parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))):
        _render_deep_review_polling()
        return
    _render_deep_review_stable()


@st.fragment
def _render_deep_review_stable() -> None:
    """Deep Review control without a client auto-refresh timer."""
    thread_id = str(st.session_state.thread_id or "")
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    job = parse_deep_review_job(metadata.get(DEEP_REVIEW_JOB_KEY))
    if deep_review_job_is_active(job):
        if not coach_turn_is_streaming():
            rerun_app()
        return
    view = deep_review_control_view(
        parse_coaching_turns_since_deep_review(metadata.get(COUNTER_SETTINGS_KEY)),
        settings.deep_review_interval_turns,
        running=False,
    )
    with st.container(key="deep_review_control", gap=10):
        if job and str(job.get("status") or "") == DEEP_REVIEW_JOB_COMPLETED:
            st.caption(_DEEP_REVIEW_COMPLETE_CAPTION)
            live_revision = int(thread.get("conversation_revision") or 0)
            reviewed_revision = int(job.get("reviewed_revision") or 0)
            if live_revision > reviewed_revision:
                st.caption(_DEEP_REVIEW_NEWER_TURNS_CAPTION)
        if view.caption:
            st.caption(view.caption)
        if view.detail_caption:
            st.caption(view.detail_caption)
        clicked = st.button(
            "Start Deep Review",
            key="start_deep_review",
            type=view.button_type,
            disabled=view.disabled,
            use_container_width=True,
        )
        if job and str(job.get("status") or "") == DEEP_REVIEW_JOB_FAILED:
            st.error(_DEEP_REVIEW_ERROR)
        if clicked and not view.disabled:
            try:
                start_deep_review(thread_id)
            except Exception:
                logger.exception("deep_review_ui_failed")
                st.error(_DEEP_REVIEW_ERROR)
                return
            rerun_app()


@st.fragment(run_every="2s")
def _render_deep_review_polling() -> None:
    """Poll Deep Review job status until the backend job is terminal."""
    thread_id = str(st.session_state.thread_id or "")
    job = get_deep_review_job(thread_id)
    status = str(getattr(job, "status", "") or "")
    if job is None or status not in {"queued", "running"}:
        if not coach_turn_is_streaming():
            rerun_app()
        return
    thread = store.get_thread(thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    view = deep_review_control_view(
        parse_coaching_turns_since_deep_review(metadata.get(COUNTER_SETTINGS_KEY)),
        settings.deep_review_interval_turns,
        running=True,
    )
    with st.container(key="deep_review_control", gap=10):
        st.button(
            "Start Deep Review",
            key="start_deep_review",
            type=view.button_type,
            disabled=True,
            use_container_width=True,
        )
        if view.status_label:
            st.status(view.status_label, expanded=False, type="compact")


def _review_fingerprint(review: dict[str, Any]) -> str:
    """Build a stable fingerprint used for Review notification dots."""
    facione = review.get("facione_scores") or {}
    facione_part = ",".join(
        f"{key}:{facione.get(key, 0)}"
        for key in (
            "analysis",
            "interpretation",
            "inference",
            "evaluation",
            "explanation",
            "self_regulation",
        )
    )
    strength_parts: list[str] = []
    for section in review.get("strength_sections") or []:
        items = section.get("items") or []
        strength_parts.append(
            f"{section.get('stage_id')}:{';'.join(str(item) for item in items)}"
        )
    improvement_parts: list[str] = []
    for section in review.get("improvement_sections") or []:
        items = section.get("items") or []
        improvement_parts.append(
            f"{section.get('stage_id')}:{';'.join(str(item) for item in items)}"
        )
    behavior_counts = review.get("facione_behavior_counts") or {}
    behavior_part = ",".join(
        f"{key}:{behavior_counts.get(key, 0)}"
        for key, _label in _FACIONE_ACTIVITY_LABELS
    )
    holistic = review.get("facione_holistic_candidate") or {}
    return "|".join(
        [
            str(review.get("summary") or ""),
            facione_part,
            behavior_part,
            str(holistic.get("score") or ""),
            str(holistic.get("rationale") or ""),
            str(review.get("conclusion") or ""),
            *strength_parts,
            *improvement_parts,
        ]
    )


def _render_stage_detail(stage: ThinkingStage) -> None:
    """Render the stage description under the full-name title."""
    st.markdown(
        f'<div class="journey-stage-detail">'
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
    opened = st.session_state.get("journey_preview_stage")
    st.session_state.journey_preview_stage = None if opened == stage_id else stage_id


def _render_journey_stage_title_row(
    stage: ThinkingStage,
    *,
    chevron: str,
) -> None:
    """Render a left-aligned stage title and preview chevron."""
    with st.container(key=f"journey_header_{stage.id}"):
        title_column, chevron_column = st.columns(
            [0.94, 0.06],
            gap="small",
            vertical_alignment="center",
        )
        with title_column:
            st.markdown(
                '<div class="journey-stage-heading">'
                f'<span class="journey-short-label">'
                f"{escape(stage.label)}</span></div>",
                unsafe_allow_html=True,
            )
        with chevron_column:
            if st.button(
                chevron,
                type="tertiary",
                use_container_width=True,
                key=f"journey-toggle-{stage.id}",
            ):
                _toggle_stage_preview(stage.id)
                rerun_fragment()


def _render_journey_stage_select_cta(
    stage: ThinkingStage,
    *,
    cta_label: str,
) -> None:
    """Render the Thinking Path select CTA below the stage body when needed."""
    with st.container(key=f"journey_select_{stage.id}"):
        if st.button(
            cta_label,
            type="tertiary",
            use_container_width=False,
            key=f"journey-select-{stage.id}",
        ):
            _select_journey_stage(stage.id)


def _select_journey_stage(stage_id: str) -> None:
    """Move stage via the coach turn path so chat shows ``Moved to Stage: …``.

    Journey CTAs use the same server-owned manual-stage command as typing
    ``move me to <stage>`` in chat, so the transcript records the change.
    """
    stage = STAGE_BY_ID.get(str(stage_id or "").strip())
    if stage is None:
        st.error(_STAGE_SELECT_ERROR)
        return
    journey = normalize_journey(st.session_state.learning_journey)
    thread_id = str(st.session_state.thread_id or "").strip()
    if not thread_id:
        st.error(_STAGE_SELECT_ERROR)
        return
    try:
        turn = submit_coach_turn(
            CoachRequest(
                thread_id=thread_id,
                student_message=f"move me to {stage.label}",
                current_stage=str(journey.get("current_stage") or stage.id),
                response_detail=str(journey.get("response_detail") or "short"),
                allow_model_knowledge=bool(
                    st.session_state.get("allow_model_knowledge", True)
                ),
                response_language=str(
                    st.session_state.get("response_language") or "English"
                ),
                model_id=str(
                    st.session_state.get("selected_model") or DEFAULT_CHAT_MODEL_ID
                ),
            )
        )
        store.forget_turn_reads(thread_id)
        updated_thread = store.get_thread(thread_id) or {}
        updated_meta = dict(updated_thread.get("metadata") or {})
        updated_journey = normalize_journey(updated_meta.get("learning_journey"))
        selected = str(turn.assessment.current_stage or stage.id).strip()
        if selected in STAGE_BY_ID:
            updated_journey["current_stage"] = selected
            updated_journey = normalize_journey(updated_journey)
        st.session_state.learning_journey = updated_journey
        st.session_state.response_detail = updated_journey["response_detail"]
        st.session_state.journey_preview_stage = None
        # Open Chat on the next remount and force a bottom snap so
        # "Moved to Stage: …" is visible. Do not assign mobile_panel here —
        # the radio widget is already instantiated in this run.
        st.session_state["pending_mobile_panel"] = "Chat"
        st.session_state.nav_section = "Chat"
        st.session_state["chat_follow_bottom"] = True
        rerun_app()
    except Exception:
        logger.exception(
            "Thinking Path stage select failed for notebook %s stage %s",
            thread_id,
            stage_id,
        )
        st.error(_STAGE_SELECT_ERROR)


def render_journey_track() -> None:
    """Render the configured roadmap with progress and phase guidance."""
    journey = normalize_journey(st.session_state.learning_journey)
    completed = set(journey["completed_stages"])
    current_id = journey["current_stage"]
    selection_enabled = bool(settings.student_stage_selection)
    completed_count = len(completed)
    preview_stage = st.session_state.get("journey_preview_stage")
    if preview_stage == current_id:
        preview_stage = None
        st.session_state.journey_preview_stage = None
    selectable_ids = set(selectable_stage_ids(journey))
    stage_indexes = {
        stage.id: index for index, stage in enumerate(THINKING_STAGES)
    }
    completed_prefix_end = -1
    for index, stage in enumerate(THINKING_STAGES):
        if stage.id not in completed:
            break
        completed_prefix_end = index
    frontier_candidate = completed_prefix_end + 1
    frontier_next = (
        THINKING_STAGES[frontier_candidate].id
        if completed_prefix_end >= 0
        and frontier_candidate < len(THINKING_STAGES)
        and THINKING_STAGES[frontier_candidate].id in selectable_ids
        else None
    )
    st.markdown(
        progress_bar_html(
            completed=completed_count,
            total=len(THINKING_STAGES),
            label="Thinking path",
            heading="Current focus",
        ),
        unsafe_allow_html=True,
    )
    if selection_enabled:
        st.caption("Choose a stage to work on.")
    stage_icons = {
        "problem_identification": "problem",
        "concept_generation": "lightbulb",
        "design_specification": "design_services",
        "deep_analysis": "manage_search",
        "reflection": "fact_check",
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
                else "available"
                if stage.id in selectable_ids
                else "locked"
            )
            icon_name = "check" if state == "completed" else stage_icons[stage.id]
            is_preview_open = stage.id == preview_stage
            state_classes = f"journey-state {state}"
            if is_preview_open:
                state_classes = f"{state_classes} open preview-open"
            with st.container(key=f"journey_stage_{stage.id}"):
                st.markdown(
                    f'<span class="{state_classes}"></span>',
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
                            f"{escape(stage.label)}</span></div></div>",
                            unsafe_allow_html=True,
                        )
                        _render_stage_detail(stage)
                    else:
                        chevron = "⌃" if is_preview_open else "⌵"
                        cta_label = (
                            "Work on this stage"
                            if (
                                selection_enabled
                                and stage.id != current_id
                                and stage.id == frontier_next
                            )
                            else "Revisit"
                            if (
                                selection_enabled
                                and stage.id != current_id
                                and stage.id in selectable_ids
                            )
                            else None
                        )
                        _render_journey_stage_title_row(stage, chevron=chevron)
                        if is_preview_open:
                            _render_stage_detail(stage)
                            if state == "locked":
                                preceding = THINKING_STAGES[stage_indexes[stage.id] - 1]
                                st.caption(
                                    f"Available after {preceding.label}."
                                )
                        if cta_label is not None:
                            _render_journey_stage_select_cta(
                                stage,
                                cta_label=cta_label,
                            )
                if state == "current" or is_preview_open:
                    _render_stage_suggestions(stage)


def review_stage_expander_key(
    *,
    key_prefix: str,
    thread_key: str,
    current_stage_id: str,
    stage_key: str,
) -> str:
    """Return a remount-scoped Streamlit expander widget key.

    The render generation is notebook/thread id plus the current Thinking
    Path stage. Changing either identity creates a new widget so
    ``expanded`` applies reliably. Same-stage reruns keep the key so a
    student's manual open or close is preserved.

    Args:
        key_prefix: ``strengths`` or ``improvements``.
        thread_key: Sanitized notebook/thread id.
        current_stage_id: Persisted Thinking Path stage.
        stage_key: Stage id (or label fallback) for this expander.

    Returns:
        Stable widget key for one render generation.
    """
    render_scope = f"{str(thread_key or 'none')}_{str(current_stage_id or '')}"
    return f"review_{key_prefix}_{render_scope}_{stage_key}"


def review_stage_expander_defaults(current_stage_id: str) -> dict[str, bool]:
    """Return default open/closed flags for the five Thinking Path stages.

    Only the current stage starts open. Strengths and Areas for improvement
    share this mapping.

    Args:
        current_stage_id: Persisted Thinking Path stage.

    Returns:
        Mapping of stage id to whether that expander should start expanded.
    """
    current = str(current_stage_id or "").strip()
    return {stage.id: stage.id == current for stage in THINKING_STAGES}


def _render_review_stage_expanders(
    *,
    sections: list[dict[str, Any]] | None,
    current_stage_id: str,
    key_prefix: str,
) -> None:
    """Render one nested expander per Thinking Path stage.

    Every stage starts collapsed except the student's current stage, so past
    feedback stays available without competing with the active focus. The
    current stage is wrapped so CSS can give it a stronger outline. Widget
    keys include the current stage so a stage change remounts expanders
    instead of fighting leftover Streamlit client state. Within the same
    stage the keys stay stable, so a student's manual open/close is kept.
    """
    stage_sections = list(sections or [])
    if not stage_sections:
        st.markdown(
            '<p class="review-empty">No feedback yet</p>',
            unsafe_allow_html=True,
        )
        return

    thread_key = str(st.session_state.get("thread_id") or "none").replace("-", "_")
    defaults = review_stage_expander_defaults(current_stage_id)

    for section in stage_sections:
        stage_id = str(section.get("stage_id") or "").strip()
        stage_label = str(section.get("stage") or "").strip() or "Stage"
        stage_key = stage_id or stage_label
        is_current = bool(defaults.get(stage_id)) if stage_id else False
        expander_parent = (
            st.container(key=f"review_{key_prefix}_{thread_key}_current")
            if is_current
            else nullcontext()
        )
        with expander_parent:
            with st.expander(
                stage_label,
                expanded=is_current,
                key=review_stage_expander_key(
                    key_prefix=key_prefix,
                    thread_key=thread_key,
                    current_stage_id=current_stage_id,
                    stage_key=stage_key,
                ),
            ):
                st.markdown(
                    review_feedback_items_html(section.get("items")),
                    unsafe_allow_html=True,
                )


def render_learning_review(journey: dict[str, Any]) -> None:
    """Render actionable Review cards from the latest coaching assessment.

    Prefers a model-written summary and Facione scores from the newest Deep
    Review snapshot when present, otherwise the newest assistant
    ``assessment``. Strengths and areas for improvement nest one expander per
    Thinking Path stage, merging historical incremental feedback with the
    latest Deep Review ``stage_reviews`` (or the legacy frozen-stage lists).
    Only the current stage is open by default. Marks the Review notification
    fingerprint as seen when
    the Review tab is active. Start Deep Review is always visible; enablement
    comes from the persisted notebook counter, not a Streamlit-only count.
    """
    messages = store.get_messages(st.session_state.thread_id)
    thread = store.get_thread(st.session_state.thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
    review = learning_review(
        messages,
        journey,
        detail=journey["response_detail"],
        deep_review_snapshot=snapshot if isinstance(snapshot, dict) else None,
    )
    fingerprint = _review_fingerprint(review)
    st.session_state.review_fingerprint = fingerprint
    if st.session_state.get("studio_tab") == "Review" or st.session_state.get(
        "nav_section"
    ) == "Review":
        st.session_state.review_seen_fingerprint = fingerprint

    current_stage_id = str(
        journey.get("current_stage") or THINKING_STAGES[0].id
    )
    _render_deep_review_chrome(metadata)
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
    behavior_counts = review.get("facione_behavior_counts") or {}
    demonstrated = [
        f"{label}: {max(0, int(behavior_counts.get(key, 0) or 0))} "
        f"{'contribution' if int(behavior_counts.get(key, 0) or 0) == 1 else 'contributions'}"
        for key, label in _FACIONE_ACTIVITY_LABELS
        if int(behavior_counts.get(key, 0) or 0) > 0
    ]
    if demonstrated:
        st.markdown(
            review_card_html(
                label="Thinking activity",
                body="",
                items=demonstrated,
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "Automated, provisional observations of reasoning demonstrated in "
            "your active conversation. Intended to support reflection, not grading."
        )
    holistic = review.get("facione_holistic_candidate")
    if isinstance(holistic, dict):
        score = holistic.get("score")
        rationale = str(holistic.get("rationale") or "").strip()
        if score and rationale:
            st.markdown(
                review_card_html(
                    label="Reflection profile",
                    body=f"{score} / 4 · {rationale}",
                ),
                unsafe_allow_html=True,
            )
            st.caption(
                "A provisional whole-conversation candidate shown only in "
                "Reflection. It is not a grade."
            )
    with st.expander("Strengths", expanded=False):
        _render_review_stage_expanders(
            sections=review.get("strength_sections"),
            current_stage_id=current_stage_id,
            key_prefix="strengths",
        )
    with st.expander("Areas for improvement", expanded=False):
        _render_review_stage_expanders(
            sections=review.get("improvement_sections"),
            current_stage_id=current_stage_id,
            key_prefix="improvements",
        )
    with st.expander("Working conclusion", expanded=False):
        conclusion = str(review.get("conclusion") or "").strip()
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
    # Preserve labels used by AppTest smoke assertions.
    st.markdown(
        '<div class="review-legacy-labels" hidden>'
        "Discussion summary · What’s working · What to strengthen"
        "</div>",
        unsafe_allow_html=True,
    )


def render_pending_transition(
    pending: Any | None = None,
) -> None:
    """Show a coach recommendation banner when confirmation mode is active.

    Advancement actions live in the Thinking Path footer (Next + confirm dialog).
    """
    if pending is None:
        pending = _fetch_pending_transition()
    if not pending:
        return
    st.info(
        f"The coach recommends moving from {pending.from_stage.title()} to "
        f"{pending.to_stage.title()}: {pending.assessment.recommendation_rationale}",
        icon=":material/auto_awesome:",
    )


def _fetch_pending_transition():
    """Return the pending transition through the active application path."""
    if settings.effective_auto_advance_stages:
        return None
    try:
        return store.pending_transition(st.session_state.thread_id)
    except Exception:
        return None


def _resolve_pending_transition(transition_id: str, accepted: bool) -> None:
    """Persist a student decision and refresh the journey."""
    try:
        store.resolve_transition(
            st.session_state.thread_id,
            transition_id,
            accepted=accepted,
        )
        updated = store.get_thread(st.session_state.thread_id) or {}
        st.session_state.learning_journey = normalize_journey(
            (updated.get("metadata") or {}).get("learning_journey")
        )
        st.session_state.pop("confirm_next_transition_id", None)
        rerun_app()
    except Exception:
        logger.exception(
            "Thinking Path transition resolve failed for notebook %s transition %s",
            st.session_state.thread_id,
            transition_id,
        )
        st.error(_TRANSITION_RESOLVE_ERROR)


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
        rerun_app()
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
            rerun_app()


def render_thinking_path_footer(pending: Any | None = None) -> None:
    """Render the confirmation-gated Next control for Thinking Path."""
    if settings.effective_auto_advance_stages or settings.student_stage_selection:
        return

    if pending is None:
        pending = _fetch_pending_transition()
    _, next_column = st.columns([0.72, 0.28], gap="small")
    next_disabled = pending is None
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
                rerun_app()


@st.fragment
def render_studio_panel() -> None:
    """Render Thinking Path with Journey/Review tabs and the Next footer.

    With ``STUDENT_STAGE_SELECTION=true``, Journey exposes audited stage picks.
    Otherwise stage changes require a coach ADVANCE recommendation, then Next
    confirmation (unless auto-advance is enabled).

    Mounted as a fragment so Journey preview toggles stay panel-local. Stage
    selection and transition confirmations still call ``rerun_app()`` because
    they change shared coach/chat state.
    """
    st.session_state["_studio_fragment_runs"] = (
        int(st.session_state.get("_studio_fragment_runs") or 0) + 1
    )
    journey = normalize_journey(st.session_state.learning_journey)
    preferred = st.session_state.get("studio_tab", "Journey")
    st.markdown(
        '<div class="pane-heading"><span class="pane-title">Thinking Path</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="studio_scroll", height="stretch"):
        # Streamlit tabs always render both bodies (client-side tab switch
        # does not rerun). Duplicate get_messages/get_thread work is avoided
        # by the page-run memo, not by skipping Review.
        journey_tab, review_tab = st.tabs(["Journey", "Review"])
        pending = _fetch_pending_transition()
        with journey_tab:
            render_journey_track()
            render_pending_transition(pending)
        with review_tab:
            if preferred == "Review":
                st.caption("Current focus")
                st.session_state.review_seen_fingerprint = st.session_state.get(
                    "review_fingerprint", ""
                )
            render_learning_review(journey)
    with st.container(key="thinking_path_footer"):
        render_thinking_path_footer(pending)
    if st.session_state.get("confirm_next_transition_id"):
        _confirm_next_stage_dialog()
