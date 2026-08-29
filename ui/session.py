"""Notebook session initialization and lifecycle helpers.

Owns Streamlit ``session_state`` defaults, notebook create/select/delete, and
journey persistence. Appearance is always loaded from the user preference store
and forced onto ``setting_appearance`` so a stale settings widget cannot rewrite
the database on the next sync.
"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from backend.models import (
    DEFAULT_CHAT_MODEL_ID,
    DEFAULT_REASONING_EFFORT,
    MODEL_BY_ID,
    get_model,
    validate_reasoning,
)
from backend.student_journey import (
    DEFAULT_RESPONSE_DETAIL,
    DEFAULT_STAGE,
    STAGE_BY_ID,
    THINKING_STAGES,
    default_journey,
    normalize_journey,
)
from backend.student_support import DEFAULT_SUPPORT_MODE

from ui.coach_welcome import seed_coach_welcome
from ui.constants import APPEARANCE_MODES, DEFAULT_APPEARANCE, RESPONSE_LANGUAGES
from ui.rename import bump_rename_epoch, discard_rename_draft
from ui.runtime import rerun_app, store
from ui.retry_keys import purge_notebook_retry_keys
from ui.settings import apply_selected_model


_COACHING_STYLE_LABELS = {
    "short": "Quick",
    "long": "Strict",
}


def initialize_session() -> None:
    """Seed session defaults and restore the active notebook plus appearance.

    Side effects:
        - Writes missing keys into ``st.session_state``.
        - Loads appearance from ``StudentStore`` user preferences and realigns
          ``setting_appearance`` to that value.
        - Restores the last-open notebook from preferences when the Streamlit
          session has no valid ``thread_id`` (e.g. browser refresh).
        - Creates or selects a notebook when none is active.
        - Backfills legacy message attachments into the source library.
    """
    defaults: dict[str, Any] = {
        "thread_id": None,
        "selected_model": DEFAULT_CHAT_MODEL_ID,
        "support_mode": DEFAULT_SUPPORT_MODE,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "web_search": False,
        "image_generation": False,
        "allow_model_knowledge": False,
        "response_detail": DEFAULT_RESPONSE_DETAIL,
        "response_language": "English",
        "appearance": DEFAULT_APPEARANCE,
        "learning_journey": default_journey(),
        "assignment": {"title": "", "course": "", "brief": "", "rubric": ""},
        "composer_nonce": 0,
        "pending_edit": None,
        "edit_error_message": None,
        "editing_message": None,
        "edit_confirm_message_id": None,
        "_coach_turn_streaming": False,
        "awaiting_coach_turn": None,
        "pending_notebook_actions": None,
        "reopen_notebooks_dialog": False,
        "pending_delete_chat_id": None,
        "mobile_panel": "Chat",
        "mobile_nav_open": False,
        "mobile_studio_open": False,
        "center_view": "chat",
        "nav_section": "Chat",
        "studio_tab": "Progression",
        "workspace_nav_collapsed": False,
        "workspace_studio_collapsed": False,
        "display_name": "Student",
        "review_fingerprint": "",
        "review_seen_fingerprint": "",
        "stage_move_notice": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    # Pre-rename sessions may still hold the old Thinking Path tab label.
    if st.session_state.get("studio_tab") == "Journey":
        st.session_state.studio_tab = "Progression"
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.web_search = False
    st.session_state.image_generation = False
    if st.session_state.selected_model not in MODEL_BY_ID:
        st.session_state.selected_model = DEFAULT_CHAT_MODEL_ID
    apply_selected_model(st.session_state.selected_model)
    preferences = store.get_user_preferences() or {}
    stored_appearance = str(preferences.get("appearance") or "").strip()
    # Prefer an explicit saved choice; otherwise force the app default.
    # Do not keep a leftover session value (e.g. old "Light" default) when the
    # preference store has no appearance key yet.
    if stored_appearance in APPEARANCE_MODES:
        st.session_state.appearance = stored_appearance
    else:
        st.session_state.appearance = DEFAULT_APPEARANCE
    # Always realign the widget key from persisted appearance so a stale
    # popover value cannot rewrite the database on the next sync.
    st.session_state.setting_appearance = st.session_state.appearance
    if not st.session_state.thread_id or not store.get_thread(st.session_state.thread_id):
        preferred_id = str(preferences.get("active_thread_id") or "").strip()
        threads = store.list_threads()
        if preferred_id and store.get_thread(preferred_id):
            select_thread(preferred_id, should_rerun=False)
        elif threads:
            select_thread(threads[0]["id"], should_rerun=False)
        else:
            new_notebook(should_rerun=False)
    store.backfill_legacy_sources(st.session_state.thread_id)


def _persist_active_thread(thread_id: str | None) -> None:
    """Remember which notebook should reopen after a browser refresh."""
    store.update_user_preferences({"active_thread_id": thread_id})


def new_notebook(should_rerun: bool = True) -> None:
    """Create an untitled notebook with a fresh Quick coaching journey.

    User-initiated creates stay on Chat with Sources open so course materials
    can load. Shows a short loading toast, then reruns the app. The profile
    Coaching style widget is reset to Quick so a prior Strict choice cannot
    leak onto the new notebook.

    Args:
        should_rerun: When True, trigger a Streamlit rerun after session updates.
    """
    if notebook_switch_locked():
        return
    journey = default_journey()
    thread_id = store.create_thread(
        name="Untitled notebook",
        model_id=st.session_state.get("selected_model") or DEFAULT_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
        assignment={"title": "", "course": "", "brief": "", "rubric": ""},
    )
    store.update_thread(
        thread_id,
        metadata={
            "response_detail": journey["response_detail"],
            "response_language": "English",
            "allow_model_knowledge": False,
        },
    )
    seed_coach_welcome(store, thread_id)
    st.session_state.thread_id = thread_id
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.learning_journey = journey
    st.session_state.response_detail = journey["response_detail"]
    st.session_state.setting_coaching_style = _COACHING_STYLE_LABELS[
        journey["response_detail"]
    ]
    st.session_state.response_language = "English"
    st.session_state.assignment = {"title": "", "course": "", "brief": "", "rubric": ""}
    st.session_state.allow_model_knowledge = False
    st.session_state.editing_message = None
    st.session_state.pending_edit = None
    st.session_state.edit_error_message = None
    st.session_state.edit_confirm_message_id = None
    clear_stage_move_notice()
    _persist_active_thread(thread_id)
    st.session_state.mobile_nav_open = False
    st.session_state.mobile_studio_open = False
    if should_rerun:
        st.session_state.pending_mobile_panel = "Chat"
        st.session_state.center_view = "chat"
        st.session_state.nav_section = "Chat"
        st.session_state.toast_course_materials_loading = True
        rerun_app()


def set_stage_move_notice(message: str) -> None:
    """Show a session-only line above the composer (locked stage hops).

    Args:
        message: Notice text such as ``Must complete … to reach …``.
    """
    cleaned = " ".join(str(message or "").split()).strip()
    st.session_state.stage_move_notice = cleaned or None


def clear_stage_move_notice() -> None:
    """Drop the ephemeral stage-move composer notice."""
    st.session_state.stage_move_notice = None


def locked_stage_move_notice(stage_id: str, journey: Any | None = None) -> str:
    """Return composer copy when ``stage_id`` is beyond the unlocked frontier.

    Always names the immediate predecessor stage — the one students must
    complete before the requested stage can unlock.

    Args:
        stage_id: Canonical Thinking Path stage the student asked for.
        journey: Unused; kept for call-site compatibility.

    Returns:
        A ``Must complete <prior> to reach <target>`` line, or a generic
        fallback when the target is the first stage or unknown.
    """
    del journey  # Call sites may pass journey; predecessor is path-order only.
    cleaned = str(stage_id or "").strip()
    target = STAGE_BY_ID.get(cleaned)
    target_label = target.label if target is not None else cleaned or "that stage"
    stage_ids = [stage.id for stage in THINKING_STAGES]
    try:
        index = stage_ids.index(cleaned)
    except ValueError:
        return f"Must complete earlier stages to reach {target_label}"
    if index <= 0:
        return f"Must complete earlier stages to reach {target_label}"
    prior = STAGE_BY_ID[stage_ids[index - 1]]
    return f"Must complete {prior.label} to reach {target_label}"


_AWAITING_COACH_TURN_TIMEOUT_SECONDS = 90


def set_awaiting_coach_turn(
    *,
    thread_id: str,
    idempotency_key: str,
    prompt: str,
    baseline_message_count: int,
) -> None:
    """Record a durable in-flight coach turn that must survive Chat remounts.

    Args:
        thread_id: Notebook that owns the turn.
        idempotency_key: Server turn scope for diagnostics (not re-submitted).
        prompt: Student text shown in the recovery inflight bubble.
        baseline_message_count: Persisted message count before this turn.
    """
    cleaned_thread = str(thread_id or "").strip()
    cleaned_key = str(idempotency_key or "").strip()
    cleaned_prompt = str(prompt or "").strip()
    if not cleaned_thread or not cleaned_key:
        return
    st.session_state.awaiting_coach_turn = {
        "thread_id": cleaned_thread,
        "idempotency_key": cleaned_key,
        "prompt": cleaned_prompt,
        "baseline_message_count": max(0, int(baseline_message_count or 0)),
        "started_at": time.time(),
    }


def clear_awaiting_coach_turn() -> None:
    """Drop the durable in-flight coach-turn marker."""
    st.session_state.awaiting_coach_turn = None


def get_awaiting_coach_turn() -> dict[str, Any] | None:
    """Return the awaiting marker when present and well-formed."""
    pending = st.session_state.get("awaiting_coach_turn")
    if not isinstance(pending, dict):
        return None
    thread_id = str(pending.get("thread_id") or "").strip()
    if not thread_id:
        return None
    return pending


def awaiting_coach_turn_for_thread(thread_id: str | None = None) -> dict[str, Any] | None:
    """Return the awaiting marker when it matches ``thread_id`` (or the active one)."""
    pending = get_awaiting_coach_turn()
    if pending is None:
        return None
    target = str(thread_id or st.session_state.get("thread_id") or "").strip()
    if not target or pending.get("thread_id") != target:
        return None
    return pending


def notebook_switch_locked() -> bool:
    """Return True when notebook create/switch must wait for an in-flight turn."""
    from ui.runtime import coach_turn_is_streaming

    if coach_turn_is_streaming():
        return True
    return get_awaiting_coach_turn() is not None


def awaiting_coach_turn_timed_out(pending: dict[str, Any] | None = None) -> bool:
    """Return True when the awaiting marker has exceeded the recovery window."""
    marker = pending if isinstance(pending, dict) else get_awaiting_coach_turn()
    if marker is None:
        return False
    try:
        started = float(marker.get("started_at") or 0.0)
    except (TypeError, ValueError):
        return True
    if started <= 0:
        return True
    return (time.time() - started) >= _AWAITING_COACH_TURN_TIMEOUT_SECONDS


def apply_manual_stage_move(thread_id: str, stage_id: str) -> bool:
    """Move Thinking Path focus and let the service persist a coach briefing.

    Calls ``store.select_stage``, refreshes session journey, and does **not**
    write a composer notice for successful moves or already-on-stage taps.
    Locked jumps still set ``stage_move_notice`` at the call site.

    Args:
        thread_id: Active notebook id.
        stage_id: Canonical Thinking Path stage id.

    Returns:
        True when ``current_stage`` changed; False when already on ``stage_id``.

    Raises:
        ValueError: When the stage is unknown, locked, or the notebook is missing.
    """
    cleaned = str(stage_id or "").strip()
    stage = STAGE_BY_ID.get(cleaned)
    if stage is None:
        raise ValueError(f"Unknown thinking stage: {cleaned}")
    previous = str(
        normalize_journey(st.session_state.get("learning_journey")).get(
            "current_stage"
        )
        or ""
    ).strip()
    metadata = store.select_stage(thread_id, cleaned)
    journey = normalize_journey(metadata.get("learning_journey"))
    st.session_state.learning_journey = journey
    st.session_state.response_detail = journey["response_detail"]
    selected = str(journey.get("current_stage") or cleaned).strip()
    clear_stage_move_notice()
    return selected != previous


def delete_notebook(thread_id: str) -> None:
    """Delete a notebook and clear inline library-dialog state if any.

    Recents delete uses the dedicated confirmation dialog; the legacy
    Your Notebooks reopen flag is cleared so the old dialog does not resurface.
    """
    if notebook_switch_locked():
        return
    st.session_state.pending_notebook_actions = None
    st.session_state.reopen_notebooks_dialog = False
    st.session_state.pop("_notebooks_suppress_dismiss", None)
    store.delete_thread(thread_id)
    purge_notebook_retry_keys(st.session_state, thread_id)
    if thread_id == st.session_state.thread_id:
        st.session_state.thread_id = None
        _persist_active_thread(None)


def dismiss_notebooks_dialog() -> None:
    """Clear library dialog state when Your Notebooks is closed (X / outside).

    Remounts for the inline actions panel set ``_notebooks_suppress_dismiss``
    so closing-and-reopening the same dialog does not wipe pending.
    """
    if st.session_state.pop("_notebooks_suppress_dismiss", False):
        return
    thread_id = st.session_state.get("pending_notebook_actions")
    if thread_id:
        discard_rename_draft("notebook", str(thread_id))
        bump_rename_epoch("notebook", str(thread_id))
    st.session_state.pending_notebook_actions = None
    st.session_state.reopen_notebooks_dialog = False


def request_notebook_actions(thread_id: str) -> None:
    """Show rename / download / delete for ``thread_id`` inside Your Notebooks."""
    # Keep dismiss from clearing pending when Streamlit remounts the dialog.
    st.session_state._notebooks_suppress_dismiss = True
    st.session_state.pending_notebook_actions = thread_id
    st.session_state.reopen_notebooks_dialog = True


def cancel_notebook_actions() -> None:
    """Leave the inline actions panel and return to the notebook list.

    Used by the Back control. Uncommitted rename drafts are discarded so the
    field restores the saved title. Does not dismiss Your Notebooks.
    """
    thread_id = st.session_state.get("pending_notebook_actions")
    if thread_id:
        discard_rename_draft("notebook", str(thread_id))
        bump_rename_epoch("notebook", str(thread_id))
    st.session_state.pending_notebook_actions = None


def select_thread(thread_id: str, should_rerun: bool = True) -> None:
    """Load a notebook into session state (journey, language, assignment).

    Args:
        thread_id: Persisted notebook identifier.
        should_rerun: When True, trigger a Streamlit rerun after loading.
    """
    cleaned = str(thread_id or "").strip()
    if (
        notebook_switch_locked()
        and cleaned
        and cleaned != str(st.session_state.get("thread_id") or "").strip()
    ):
        return
    thread = store.get_thread(thread_id)
    if not thread:
        return
    metadata = thread.get("metadata") or {}
    selected = metadata.get("selected_model")
    if selected in MODEL_BY_ID:
        apply_selected_model(str(selected))
    else:
        apply_selected_model(DEFAULT_CHAT_MODEL_ID)
    # Keep effort compatible with the restored model choice.
    st.session_state.reasoning_effort = validate_reasoning(
        get_model(st.session_state.selected_model),
        metadata.get("reasoning_effort"),
    )
    st.session_state.support_mode = DEFAULT_SUPPORT_MODE
    st.session_state.allow_model_knowledge = False
    raw_journey = metadata.get("learning_journey")
    if not isinstance(raw_journey, dict):
        raw_journey = {
            "current_stage": metadata.get("thinking_stage", DEFAULT_STAGE),
            "response_detail": metadata.get(
                "response_detail", DEFAULT_RESPONSE_DETAIL
            ),
        }
    journey = normalize_journey(raw_journey)
    st.session_state.learning_journey = journey
    st.session_state.response_detail = journey["response_detail"]
    st.session_state.setting_coaching_style = _COACHING_STYLE_LABELS[
        journey["response_detail"]
    ]
    language = str(metadata.get("response_language") or "English")
    st.session_state.response_language = (
        language if language in RESPONSE_LANGUAGES else "English"
    )
    st.session_state.assignment = {
        **{"title": "", "course": "", "brief": "", "rubric": ""},
        **(metadata.get("assignment") or {}),
    }
    display_name = str(metadata.get("display_name") or "").strip()
    if display_name:
        st.session_state.display_name = display_name
    st.session_state.thread_id = thread_id
    st.session_state.editing_message = None
    st.session_state.pending_edit = None
    st.session_state.edit_error_message = None
    st.session_state.edit_confirm_message_id = None
    clear_stage_move_notice()
    _persist_active_thread(thread_id)
    store.backfill_legacy_sources(thread_id)
    seed_coach_welcome(store, thread_id)
    if should_rerun:
        rerun_app()


def save_journey(journey: dict[str, Any]) -> None:
    """Normalize local display state and persist student-editable settings only.

    The session copy of ``current_stage`` is never sent back through generic
    notebook metadata; FastAPI and the learning service own persisted stages.
    """
    normalized = normalize_journey(journey)
    st.session_state.learning_journey = normalized
    st.session_state.response_detail = normalized["response_detail"]
    store.update_thread(
        st.session_state.thread_id,
        metadata={
            "response_detail": normalized["response_detail"],
            "response_language": st.session_state.get("response_language", "English"),
        },
    )
