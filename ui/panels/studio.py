"""Thinking Path studio panel and learning review.

Renders the configured Thinking Path, confirmation-gated pending transitions
(when auto-advance is off), and Review cards. Review order is Working
conclusion, Strengths, Areas for improvement, then the Critical Thinking
Facione card inline (not in an expander). Facione scores prefer a Deep Review
snapshot, else max message assessments with Haiku stage checkpoints; strengths
and improvement areas nest one expander per Thinking Path stage, with only the
student's current stage open by default.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from dataclasses import dataclass
from html import escape
from typing import Any, Literal

import streamlit as st

from backend.settings import settings
from backend.specialists.review_orchestration import (
    COUNTER_SETTINGS_KEY,
    DEEP_REVIEW_JOB_COMPLETED,
    DEEP_REVIEW_JOB_FAILED,
    DEEP_REVIEW_JOB_KEY,
    DEEP_REVIEW_SNAPSHOT_KEY,
    JOURNEY_STAGE_REVIEWS_KEY,
    STAGE_REVIEW_COMPLETE,
    STAGE_REVIEW_FAILED,
    STAGE_REVIEW_QUEUED,
    STAGE_REVIEW_RUNNING,
    deep_review_job_is_active,
    explicit_deep_review_available,
    parse_deep_review_job,
    parse_journey_stage_reviews,
    stage_reviews_need_attention,
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
    get_journey_stage_reviews,
    mark_journey_stage_reviews_read,
    rerun_app,
    rerun_fragment,
    start_deep_review,
    store,
)
from ui.session import apply_manual_stage_move

logger = logging.getLogger(__name__)

_REVIEW_UNREAD_BADGE = "🛑"

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
    completed_stages: list[str] | tuple[str, ...] | None,
    *,
    running: bool,
) -> DeepReviewControlView:
    """Map Thinking Path completion onto the Deep Review button.

    Unlock requires every required stage, including Reflection, to be in
    ``completed_stages``. This helper does not invoke Sonnet.

    Args:
        completed_stages: Persisted completed Thinking Path stage ids.
        running: Whether this notebook already has an in-flight Deep Review.

    Returns:
        Caption, enablement, and button type for Start Deep Review.
    """
    eligible = explicit_deep_review_available(
        completed_stages=list(completed_stages or []),
    )
    disabled = (not eligible) or running
    locked_caption = (
        "Deep Review unlocks when the Thinking Path including Reflection "
        "is complete."
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
        normalize_journey(metadata.get("learning_journey")).get("completed_stages")
        or [],
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
        normalize_journey(metadata.get("learning_journey")).get("completed_stages")
        or [],
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
    """Move stage via ``select_stage`` and show an ephemeral composer notice.

    Does not write ``move me to …`` / ``Moved to Stage: …`` chat bubbles.
    Focus is persisted on the notebook journey only.
    """
    stage = STAGE_BY_ID.get(str(stage_id or "").strip())
    if stage is None:
        st.error(_STAGE_SELECT_ERROR)
        return
    thread_id = str(st.session_state.thread_id or "").strip()
    if not thread_id:
        st.error(_STAGE_SELECT_ERROR)
        return
    try:
        apply_manual_stage_move(thread_id, stage.id)
        store.forget_turn_reads(thread_id)
        st.session_state.journey_preview_stage = None
        # Open Chat so the composer notice is visible. Do not assign
        # mobile_panel here — the radio widget is already instantiated.
        st.session_state["pending_mobile_panel"] = "Chat"
        st.session_state.nav_section = "Chat"
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
    frontier_progress_id = (
        THINKING_STAGES[frontier_candidate].id
        if frontier_candidate < len(THINKING_STAGES)
        else None
    )
    frontier_next = (
        THINKING_STAGES[frontier_candidate].id
        if completed_prefix_end >= 0
        and frontier_candidate < len(THINKING_STAGES)
        and THINKING_STAGES[frontier_candidate].id in selectable_ids
        else None
    )
    thread_meta = dict(
        (store.get_thread(str(st.session_state.thread_id or "")) or {}).get(
            "metadata"
        )
        or {}
    )
    st.markdown(
        progress_bar_html(
            completed=completed_count,
            total=len(THINKING_STAGES),
            label="Thinking path",
            heading="Stage Progression",
        ),
        unsafe_allow_html=True,
    )
    if selection_enabled:
        st.caption("Choose a stage to work on.")
    if explicit_deep_review_available(
        completed_stages=list(completed),
    ) and not isinstance(thread_meta.get(DEEP_REVIEW_SNAPSHOT_KEY), dict):
        with st.container(key="journey_deep_review"):
            st.markdown("**Deep Review**")
            st.caption("Your full learning journey is ready.")
            if st.button(
                "Generate Deep Review",
                key="journey_generate_deep_review",
                type="primary",
                use_container_width=True,
            ):
                try:
                    start_deep_review(str(st.session_state.thread_id or ""))
                    rerun_app()
                except Exception:
                    logger.exception("journey_deep_review_ui_failed")
                    st.error(_DEEP_REVIEW_ERROR)
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
            # Progress node state is cumulative; focus/expansion uses current_id.
            if stage.id in completed:
                state = "completed"
            elif frontier_progress_id and stage.id == frontier_progress_id:
                state = "current"
            elif stage.id in selectable_ids:
                state = "available"
            else:
                state = "locked"
            is_focus = stage.id == current_id
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
                    if is_focus:
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
                if is_focus or is_preview_open:
                    _render_stage_suggestions(stage)


def _dedupe_feedback_items(*groups: list[Any]) -> list[str]:
    """Return cleaned feedback strings with case-insensitive dedupe, first wins."""
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        for raw in group:
            cleaned = " ".join(str(raw).split()).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(cleaned)
    return result


def _complete_checkpoint_review(
    stage_id: str, blob: dict[str, Any]
) -> dict[str, Any] | None:
    """Return a completed stage-checkpoint review mapping, if present."""
    job = (blob.get("jobs") or {}).get(stage_id) or {}
    if str(job.get("status") or "") != STAGE_REVIEW_COMPLETE:
        return None
    review = (blob.get("reviews") or {}).get(stage_id)
    return review if isinstance(review, dict) else None


def _merge_checkpoint_items_into_sections(
    sections: list[dict[str, Any]] | None,
    blob: dict[str, Any],
    *,
    field: str,
) -> list[dict[str, Any]]:
    """Prepend Journey stage-checkpoint items onto matching Review sections."""
    merged: list[dict[str, Any]] = []
    for section in list(sections or []):
        stage_id = str(section.get("stage_id") or "").strip()
        checkpoint = _complete_checkpoint_review(stage_id, blob)
        extra = list((checkpoint or {}).get(field) or []) if checkpoint else []
        existing = list(section.get("items") or [])
        merged.append(
            {
                **section,
                "items": _dedupe_feedback_items(extra, existing),
            }
        )
    return merged


def _conclusion_sections_from_checkpoints(
    *,
    blob: dict[str, Any],
    current_stage_id: str,
    whole_conclusion: str,
) -> list[dict[str, Any]]:
    """Build Working-conclusion stage sections from checkpoint summaries.

    Each stage expander is labeled with the Thinking Path stage name. The
    whole-conversation conclusion is shown on the current stage when present.
    """
    current = str(current_stage_id or "").strip()
    whole = " ".join(str(whole_conclusion or "").split()).strip()
    sections: list[dict[str, Any]] = []
    for stage in THINKING_STAGES:
        checkpoint = _complete_checkpoint_review(stage.id, blob)
        summary = ""
        if checkpoint is not None:
            summary = " ".join(str(checkpoint.get("summary") or "").split()).strip()
        parts: list[str] = []
        if summary:
            parts.append(summary)
        if stage.id == current and whole:
            if not summary or whole.lower() != summary.lower():
                parts.append(whole)
        sections.append(
            {
                "stage_id": stage.id,
                "stage": stage.label,
                "body": "\n\n".join(parts),
            }
        )
    return sections


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
        key_prefix: ``strengths``, ``improvements``, or ``conclusions``.
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

    Only the current stage starts open. Strengths, Areas for improvement, and
    Working conclusion share this mapping.

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
    content: Literal["items", "body"] = "items",
    empty_label: str = "No feedback yet",
) -> None:
    """Render one nested expander per Thinking Path stage.

    Every stage starts collapsed except the student's current stage, so past
    feedback stays available without competing with the active focus. The
    current stage is wrapped so CSS can give it a stronger outline. Widget
    keys include the current stage so a stage change remounts expanders
    instead of fighting leftover Streamlit client state. Within the same
    stage the keys stay stable, so a student's manual open/close is kept.

    Args:
        sections: Stage-grouped feedback with ``items`` bullets or ``body``
            prose depending on ``content``.
        current_stage_id: Persisted Thinking Path stage.
        key_prefix: Widget-key namespace (``strengths``, ``improvements``,
            ``conclusions``).
        content: ``items`` for bullet lists, ``body`` for prose paragraphs.
        empty_label: Placeholder when a stage has no content.
    """
    stage_sections = list(sections or [])
    if not stage_sections:
        st.markdown(
            f'<p class="review-empty">{escape(empty_label)}</p>',
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
                if content == "body":
                    body = str(section.get("body") or "").strip()
                    if body:
                        paragraphs = [
                            f"<p>{escape(part)}</p>"
                            for part in body.split("\n\n")
                            if part.strip()
                        ]
                        st.markdown(
                            f'<div class="review-conclusion-body">'
                            f'{"".join(paragraphs)}</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<p class="review-empty">{escape(empty_label)}</p>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.markdown(
                        review_feedback_items_html(
                            section.get("items"),
                            empty_label=empty_label,
                        ),
                        unsafe_allow_html=True,
                    )


def render_learning_review(journey: dict[str, Any]) -> None:
    """Render actionable Review cards from coaching and Journey checkpoints.

    Prefers Facione scores from the newest Deep Review snapshot when present,
    otherwise maxes historical assessments with Haiku stage-checkpoint Facione.
    Strengths and areas for improvement nest one expander per Thinking Path
    stage, merging historical incremental feedback with the latest Deep Review
    ``stage_reviews`` (or the legacy frozen-stage lists) and Journey stage-
    checkpoint items. Working conclusion uses the same nested-stage pattern.
    Only the current stage is open by default. Marks the Review notification
    fingerprint as seen when the Review section is active. Start Deep Review
    is always visible; enablement comes from the persisted notebook counter.
    """
    messages = store.get_messages(st.session_state.thread_id)
    thread = store.get_thread(st.session_state.thread_id) or {}
    metadata = dict(thread.get("metadata") or {})
    snapshot = metadata.get(DEEP_REVIEW_SNAPSHOT_KEY)
    checkpoint_blob = parse_journey_stage_reviews(
        metadata.get(JOURNEY_STAGE_REVIEWS_KEY)
    )
    review = learning_review(
        messages,
        journey,
        detail=journey["response_detail"],
        deep_review_snapshot=snapshot if isinstance(snapshot, dict) else None,
        journey_stage_reviews=checkpoint_blob,
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
    strength_sections = _merge_checkpoint_items_into_sections(
        review.get("strength_sections"),
        checkpoint_blob,
        field="strengths",
    )
    improvement_sections = _merge_checkpoint_items_into_sections(
        review.get("improvement_sections"),
        checkpoint_blob,
        field="areas_to_revisit",
    )
    conclusion_sections = _conclusion_sections_from_checkpoints(
        blob=checkpoint_blob,
        current_stage_id=current_stage_id,
        whole_conclusion=str(review.get("conclusion") or ""),
    )
    # Show pending/failed checkpoint captions without duplicating cards.
    pending_labels: list[str] = []
    for stage in THINKING_STAGES:
        job = (checkpoint_blob.get("jobs") or {}).get(stage.id) or {}
        status = str(job.get("status") or "")
        if status in {STAGE_REVIEW_QUEUED, STAGE_REVIEW_RUNNING}:
            pending_labels.append(f"{stage.label}: reviewing…")
        elif status == STAGE_REVIEW_FAILED:
            pending_labels.append(f"{stage.label}: stage review unavailable.")

    _render_deep_review_chrome(metadata)
    if pending_labels:
        for label in pending_labels:
            st.caption(label)
    with st.expander("Working conclusion", expanded=False):
        _render_review_stage_expanders(
            sections=conclusion_sections,
            current_stage_id=current_stage_id,
            key_prefix="conclusions",
            content="body",
            empty_label="No working conclusion yet.",
        )
    with st.expander("Strengths", expanded=False):
        _render_review_stage_expanders(
            sections=strength_sections,
            current_stage_id=current_stage_id,
            key_prefix="strengths",
        )
    with st.expander("Areas for improvement", expanded=False):
        _render_review_stage_expanders(
            sections=improvement_sections,
            current_stage_id=current_stage_id,
            key_prefix="improvements",
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


@st.fragment(run_every="2s")
def _watch_stage_review_attention_fragment() -> None:
    """Remount the workspace when a stage Haiku job needs a badge refresh.

    Mounted outside ``studio_panel`` so ticks do not churn Thinking Path DOM.
    Idle notebooks no-op after reading the durable blob.
    """
    thread_id = str(st.session_state.get("thread_id") or "").strip()
    if not thread_id:
        return
    try:
        blob = get_journey_stage_reviews(thread_id)
    except Exception:
        return
    if not isinstance(blob, dict):
        blob = {}
    attention = stage_reviews_need_attention(blob)
    active = any(
        str((job or {}).get("status") or "") in {STAGE_REVIEW_QUEUED, STAGE_REVIEW_RUNNING}
        for job in (blob.get("jobs") or {}).values()
        if isinstance(job, dict)
    )
    prev_attention = st.session_state.get("_stage_review_attention")
    prev_active = bool(st.session_state.get("_stage_review_active"))
    st.session_state["_stage_review_attention"] = attention
    st.session_state["_stage_review_active"] = active
    if prev_attention is None:
        return
    if (not prev_attention and attention) or (prev_active and not active):
        rerun_app()


def mount_stage_review_attention_watch() -> None:
    """Register the stage-review badge poller outside ``.st-key-studio_panel``.

    Call from the workspace on every paint so Streamlit keeps the ``run_every``
    timer registered. Idle ticks no-op when no checkpoint job is in flight.
    """
    _watch_stage_review_attention_fragment()


@st.fragment
def render_studio_panel() -> None:
    """Render Thinking Path with Journey/Review sections and the Next footer.

    With ``STUDENT_STAGE_SELECTION=true``, Journey exposes audited stage picks.
    Otherwise stage changes require a coach ADVANCE recommendation, then Next
    confirmation (unless auto-advance is enabled).

    Mounted as a fragment so Journey preview toggles stay panel-local. Stage
    selection and transition confirmations still call ``rerun_app()`` because
    they change shared coach/chat state. Selecting Review while stage-review
    feedback is unread clears the durable unread flag via the workspace API.
    """
    st.session_state["_studio_fragment_runs"] = (
        int(st.session_state.get("_studio_fragment_runs") or 0) + 1
    )
    journey = normalize_journey(st.session_state.learning_journey)
    thread_id = str(st.session_state.thread_id or "")
    thread_meta = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey_reviews = parse_journey_stage_reviews(
        thread_meta.get(JOURNEY_STAGE_REVIEWS_KEY)
    )
    journey_attention = stage_reviews_need_attention(journey_reviews)

    def _studio_section_label(value: str) -> str:
        if value == "Review" and journey_attention:
            return f"Review {_REVIEW_UNREAD_BADGE}"
        return value

    st.markdown(
        '<div class="pane-heading"><span class="pane-title">Thinking Path</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="studio_scroll", height="stretch"):
        with st.container(key="studio_section_tabs"):
            selected = st.radio(
                "Thinking Path section",
                ["Journey", "Review"],
                horizontal=True,
                key="studio_tab",
                format_func=_studio_section_label,
                label_visibility="collapsed",
            )
        # Clear durable unread when Review is opened, but still render the
        # Review body in this run. An early return left a blank Studio pane
        # (and a follow-up rerun refreshes the top Journey 🛑 badge).
        clear_unread_rerun = False
        if (
            selected == "Review"
            and bool(journey_reviews.get("unread"))
            and thread_id
        ):
            try:
                mark_journey_stage_reviews_read(thread_id)
                clear_unread_rerun = True
            except Exception:
                logger.exception(
                    "Clearing Thinking Path review unread failed for notebook %s",
                    thread_id,
                )
        pending = _fetch_pending_transition()
        if selected == "Review":
            st.session_state.review_seen_fingerprint = st.session_state.get(
                "review_fingerprint", ""
            )
            render_learning_review(journey)
        else:
            render_journey_track()
            render_pending_transition(pending)
    with st.container(key="thinking_path_footer"):
        render_thinking_path_footer(pending)
    if st.session_state.get("confirm_next_transition_id"):
        _confirm_next_stage_dialog()
    if clear_unread_rerun:
        rerun_app()
