"""Sources panel, dialogs, and source display helpers."""

from __future__ import annotations

import logging
import re
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from backend.settings import settings
from backend.source_library import COURSE_MATERIAL_GROUPS, is_locked_course_source
from ui.components import empty_state_html
from ui.menu_popovers import close_menu_popover, menu_popover_widget_key
from ui.rename import (
    bump_rename_epoch,
    discard_rename_draft,
    render_enter_to_apply_rename,
    sync_rename_select_all,
)
from ui.runtime import coach_turn_is_streaming, rerun_app, rerun_fragment, store

logger = logging.getLogger(__name__)

# Student-facing copy only — never pass raw exception text into the UI.
_SOURCE_UPLOAD_ERROR = (
    "The file could not be added. Check the type and size, then try again."
)
_SOURCE_SYNC_ERROR = "Course materials could not be loaded."
_SOURCE_IMPORT_PARTIAL_ERROR = (
    "Some course materials could not be imported. "
    "Try again later or contact the course team."
)
_SOURCE_RENAME_ERROR = "The source could not be renamed. Try again."
_SOURCE_DOWNLOAD_ERROR = "The file could not be downloaded. Try again."


def format_size(size: int) -> str:
    """Format a byte count for source metadata captions."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def source_kind_label(source: dict[str, Any]) -> str:
    kind = source.get("kind")
    if kind == "url":
        return "Web page"
    if kind == "text":
        return "Pasted text"
    if kind == "image":
        return "Image"
    suffix = Path(str(source.get("title") or "")).suffix.lstrip(".").upper()
    return suffix or "File"


def _source_has_downloadable_file(source: dict[str, Any]) -> bool:
    """Return True when the source has file bytes available via the workspace API."""
    if "has_file" in source:
        return bool(source.get("has_file"))
    return bool(source.get("path"))


def _import_uploaded_sources(uploads: list[Any]) -> None:
    """Persist selected files into the active notebook and reset the picker.

    Dedupes against the current uploader widget generation (``source_upload_nonce``)
    so the 1s Sources fragment cannot re-import the same selection, while a later
    picker generation can re-add the same filenames after delete or retry.
    """
    if not uploads:
        return
    thread_id = st.session_state.thread_id
    nonce = int(st.session_state.get("source_upload_nonce") or 0)
    fingerprint = tuple(
        (upload.name, int(getattr(upload, "size", 0) or 0)) for upload in uploads
    )
    handled_key = f"source-upload-handled-{thread_id}-{nonce}"
    if st.session_state.get(handled_key) == fingerprint:
        return
    # Claim this selection before the slow import so the fragment cannot start
    # a second concurrent attempt while the first is still running.
    st.session_state[handled_key] = fingerprint
    try:
        added = store.upload_sources(
            thread_id,
            [
                (upload.name, upload.getvalue(), getattr(upload, "type", None))
                for upload in uploads
            ],
            origin="source_panel",
        )
    except Exception:
        logger.exception(
            "Source panel upload failed for notebook %s",
            thread_id,
        )
        st.session_state["source_upload_error"] = _SOURCE_UPLOAD_ERROR
        # Clear the picker so the fragment stops retrying the failed selection.
        st.session_state["source_upload_nonce"] = nonce + 1
        rerun_fragment()
        return
    st.session_state.pop("source_upload_error", None)
    if added:
        st.session_state.allow_model_knowledge = False
        store.update_thread(
            thread_id,
            metadata={"allow_model_knowledge": False},
        )
        st.toast(f"Added {len(added)} source{'s' if len(added) != 1 else ''}.")
    st.session_state["source_upload_nonce"] = nonce + 1
    rerun_fragment()


@st.dialog("Source", width="large")
def source_viewer_dialog(source_id: str) -> None:
    source = store.get_source(st.session_state.thread_id, source_id)
    if not source:
        st.error("This source is no longer available.")
        return
    st.markdown(f"### {source['title']}")
    st.caption(
        f"{source_kind_label(source)} · {format_size(int(source.get('size') or 0))}"
    )
    if source.get("sourceUrl"):
        st.link_button(
            "Open original webpage",
            str(source["sourceUrl"]),
            icon=":material/open_in_new:",
        )
    content = None
    if _source_has_downloadable_file(source):
        try:
            content = store.get_source_content(st.session_state.thread_id, source_id)
        except Exception:
            content = None
    if content and (
        content.filename.lower().endswith(".pdf")
        or content.mime == "application/pdf"
    ):
        st.pdf(content.data, height=560, key=f"pdf-preview-{source_id}")
    elif content and str(source.get("mime") or content.mime).startswith("image/"):
        st.image(content.data, use_container_width=True)
    else:
        text = str(source.get("extractedText") or "").strip()
        if text:
            with st.container(height=500, border=True):
                st.write(text)
        else:
            st.info("No readable text preview is available for this file.")


def _source_type_bucket(source: dict[str, Any]) -> str:
    """Map a source to a filter bucket for the Sources library."""
    if is_locked_course_source(source):
        return "Course"
    kind = str(source.get("kind") or "")
    mime = str(source.get("mime") or "").lower()
    title = str(source.get("title") or "").lower()
    if kind == "url":
        return "Web"
    if kind == "text":
        return "Text"
    if kind == "image" or mime.startswith("image/"):
        return "Image"
    if mime == "application/pdf" or title.endswith(".pdf"):
        return "PDF"
    return "File"


def _natural_sort_key(value: str) -> tuple[Any, ...]:
    """Split titles into text/number chunks for Week 2 before Week 10 ordering."""
    parts = re.split(r"(\d+)", value.lower())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _filter_sources(
    sources: list[dict[str, Any]],
    *,
    query: str,
    type_filter: str,
    sort_mode: str,
) -> list[dict[str, Any]]:
    """Apply search, type filter, and sort to notebook sources."""
    needle = query.strip().lower()
    filtered = []
    for source in sources:
        if needle and needle not in str(source.get("title") or "").lower():
            continue
        bucket = _source_type_bucket(source)
        if type_filter != "All" and bucket != type_filter:
            continue
        filtered.append(source)
    if sort_mode == "Name":
        filtered.sort(key=lambda item: _natural_sort_key(str(item.get("title") or "")))
    else:
        filtered.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return filtered


def _sort_course_sources_by_name(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return course materials in ascending natural title order for folder lists."""
    return sorted(
        sources,
        key=lambda item: _natural_sort_key(str(item.get("title") or "")),
    )


def _sources_expander_widget_key(section: str) -> str:
    """Stable Streamlit key for a Sources section expander."""
    slug = re.sub(r"[^a-z0-9]+", "_", section.strip().lower()).strip("_")
    return f"sources_expander_{slug}"


def _sources_expander_prefs() -> dict[str, Any]:
    """Return persisted expander open/closed flags for this student."""
    prefs = store.get_user_preferences() or {}
    saved = prefs.get("sources_expander_state")
    return dict(saved) if isinstance(saved, dict) else {}


def _ensure_sources_expander_state(
    section: str,
    *,
    default: bool = True,
    saved: dict[str, Any] | None = None,
) -> str:
    """Seed expander open/closed state from preferences after a browser refresh.

    Returns:
        The Streamlit widget key for ``st.expander``.
    """
    widget_key = _sources_expander_widget_key(section)
    if widget_key not in st.session_state:
        stored = _sources_expander_prefs() if saved is None else saved
        if section in stored:
            st.session_state[widget_key] = bool(stored[section])
        else:
            st.session_state[widget_key] = default
    return widget_key


def _persist_sources_expander_state(section: str, widget_key: str) -> None:
    """Remember expander open/closed state across refreshes when it changes."""
    expanded = bool(st.session_state.get(widget_key, True))
    saved = _sources_expander_prefs()
    if saved.get(section) is expanded:
        return
    saved[section] = expanded
    store.update_user_preferences({"sources_expander_state": saved})


def _persist_sources_expander_states(
    sections: list[tuple[str, str]],
) -> None:
    """Write every listed expander flag in one preference update.

    Args:
        sections: ``(section title, widget key)`` pairs rendered this run.
    """
    saved = _sources_expander_prefs()
    changed = False
    for section, widget_key in sections:
        expanded = bool(st.session_state.get(widget_key, True))
        if saved.get(section) is expanded:
            continue
        saved[section] = expanded
        changed = True
    if changed:
        store.update_user_preferences({"sources_expander_state": saved})


def _sources_expander_changed(section: str, widget_key: str) -> None:
    """Persist as soon as the student expands or collapses a Sources section."""
    _persist_sources_expander_state(section, widget_key)


def _select_all_checkbox_state(
    selected_count: int,
    total_count: int,
) -> tuple[bool, bool]:
    """Return ``(checked, indeterminate)`` for the source master checkbox."""
    if total_count <= 0:
        return False, False
    if selected_count >= total_count:
        return True, False
    return False, selected_count > 0


def _set_select_all_checkbox_state(*, checked: bool, indeterminate: bool) -> None:
    """Apply the tri-state visual state to Streamlit's native checkbox.

    Streamlit exposes a boolean checkbox value, so the partial-selection state
    is applied to the rendered native input after the widget mounts. Clicking
    an indeterminate checkbox follows the native browser behavior and selects
    every source.
    """
    state = "indeterminate" if indeterminate else "checked" if checked else "unchecked"
    aria_state = "mixed" if indeterminate else "true" if checked else "false"
    components.html(
        f"""
<script>
(() => {{
  const state = {state!r};
  const ariaState = {aria_state!r};
  let attempts = 0;
  const applyState = () => {{
    try {{
      const root = window.parent.document.querySelector(
        '.st-key-sources_select_all'
      );
      const control = root && root.querySelector(
        '[role="checkbox"], input[type="checkbox"]'
      );
      if (root) {{
        root.dataset.cdSelectAllState = state;
        if (control) {{
          if ('indeterminate' in control) {{
            control.indeterminate = state === 'indeterminate';
          }}
          control.setAttribute('aria-checked', ariaState);
          const label = control.closest('label');
          if (label) label.setAttribute('aria-checked', ariaState);
        }}
        if (control || attempts++ >= 20) return;
        window.setTimeout(applyState, 50);
        return;
      }}
    }} catch (error) {{
    }}
    if (attempts++ < 20) window.setTimeout(applyState, 50);
  }};
  window.setTimeout(applyState, 0);
}})();
</script>
""",
        height=0,
    )


def _source_selected_widget_key(source_id: str) -> str:
    """Return the stable checkbox key for one personal source."""
    return f"source-selected-{source_id}"


def _select_all_widget_key(thread_id: str, personal_count: int) -> str:
    """Return the select-all key (remounts when the personal source count changes)."""
    return f"all-sources-{thread_id}-{personal_count}"


def _persist_source_selected(source_id: str, widget_key: str) -> None:
    """Write one source selection to the store from the checkbox widget state.

    Session state mirrors the widget only for Streamlit binding; the store/API
    remains authoritative for coaching and refresh.
    """
    selected = bool(st.session_state.get(widget_key))
    thread_id = st.session_state.thread_id
    store.set_source_selected(thread_id, source_id, selected)
    if selected:
        st.session_state.allow_model_knowledge = False
        store.update_thread(
            thread_id,
            metadata={"allow_model_knowledge": False},
        )


def _persist_select_all_sources(
    thread_id: str,
    widget_key: str,
    source_ids: tuple[str, ...],
) -> None:
    """Persist select-all and mirror personal checkbox keys from the new value."""
    selected = bool(st.session_state.get(widget_key))
    store.set_all_sources_selected(thread_id, selected)
    for source_id in source_ids:
        st.session_state[_source_selected_widget_key(source_id)] = selected
    if selected:
        st.session_state.allow_model_knowledge = False
        store.update_thread(
            thread_id,
            metadata={"allow_model_knowledge": False},
        )


def _sync_source_selection_widgets(personal_sources: list[dict[str, Any]]) -> None:
    """Align checkbox session keys with store-selected flags before render."""
    for source in personal_sources:
        st.session_state[_source_selected_widget_key(source["id"])] = bool(
            source.get("selected")
        )


def _render_source_sort_dropdown(thread_id: str) -> str:
    """Render a compact Sort menu (popover, not an editable select field).

    Returns:
        The active sort mode: ``Recent`` or ``Name``.
    """
    sort_key = f"source-sort-{thread_id}"
    if st.session_state.get(sort_key) not in {"Recent", "Name"}:
        st.session_state[sort_key] = "Recent"
    current = str(st.session_state[sort_key])
    with st.container(key="sources_sort_menu"):
        with st.popover(
            current,
            key=menu_popover_widget_key("source-sort", thread_id),
        ):
            for mode in ("Recent", "Name"):
                if st.button(
                    mode,
                    key=f"source-sort-option-{thread_id}-{mode.lower()}",
                    use_container_width=True,
                    type="tertiary",
                ):
                    if mode != current:
                        st.session_state[sort_key] = mode
                    close_menu_popover("source-sort", thread_id)
                    rerun_fragment()
    return str(st.session_state[sort_key])


def render_sources_panel() -> None:
    """Render the Sources column.

    Auto-refresh (``run_every``) runs only while course-material sync is in
    progress. A permanent 1s timer leaves stale fragment IDs after full-app
    reruns (auth gate, logout, notebook switches) and Streamlit logs
    "The fragment with id … does not exist anymore". While a coach turn is
    streaming, keep the stable fragment so a sync-complete remount cannot
    stack a second workspace under the in-flight run.
    """
    sync_future = store.request_course_material_sync(st.session_state.thread_id)
    if coach_turn_is_streaming() or sync_future.done():
        _render_sources_panel_stable()
    else:
        _render_sources_panel_polling()


@st.fragment
def _render_sources_panel_stable() -> None:
    """Sources UI without a client auto-refresh timer."""
    _render_sources_panel_body()
    if coach_turn_is_streaming():
        return
    if not store.request_course_material_sync(st.session_state.thread_id).done():
        rerun_app()


@st.fragment(run_every="1s")
def _render_sources_panel_polling() -> None:
    """Sources UI that refreshes every second until course sync finishes."""
    _render_sources_panel_body()
    if coach_turn_is_streaming():
        return
    if store.request_course_material_sync(st.session_state.thread_id).done():
        # Remount the stable fragment so the browser drops the 1s timer.
        rerun_app()


def _render_sources_panel_body() -> None:
    """Shared Sources panel body used by the stable and polling fragments."""
    st.session_state["_sources_fragment_runs"] = (
        int(st.session_state.get("_sources_fragment_runs") or 0) + 1
    )
    store.backfill_legacy_sources(st.session_state.thread_id)
    sync_future = store.request_course_material_sync(st.session_state.thread_id)
    sync_loading = not sync_future.done()
    lecture_sync = None
    sync_error = ""
    if not sync_loading:
        try:
            lecture_sync = sync_future.result()
        except Exception:
            logger.exception(
                "Course material sync failed for notebook %s",
                st.session_state.thread_id,
            )
            sync_error = _SOURCE_SYNC_ERROR
    sources = store.list_sources(st.session_state.thread_id)
    personal_sources_all = [
        source for source in sources if not is_locked_course_source(source)
    ]
    _sync_source_selection_widgets(personal_sources_all)
    personal_selected_count = sum(
        1 for source in personal_sources_all if source["selected"]
    )
    count_label = (
        "Loading…"
        if sync_loading
        else f"{personal_selected_count} selected"
    )
    with st.container(key="sources_header"):
        # Match Thinking Path: markdown title first (no st.columns chrome), Add overlaid.
        with st.container(key="sources_title_row"):
            st.markdown(
                '<div class="pane-heading source-pane-heading">'
                '<div class="source-heading-group">'
                '<span class="pane-title">Sources</span>'
                f'<span class="pane-count">{count_label}</span>'
                "</div></div>",
                unsafe_allow_html=True,
            )
            with st.container(key="add-sources"):
                size_hint = f"Max {settings.max_file_size_mb} MB per file"
                st.markdown(
                    f'<div class="cd-sources-add-face" data-tooltip="{escape(size_hint)}" '
                    'aria-hidden="true">+ Add</div>',
                    unsafe_allow_html=True,
                )
                upload_nonce = int(st.session_state.get("source_upload_nonce") or 0)
                uploads = st.file_uploader(
                    "Add",
                    accept_multiple_files=True,
                    label_visibility="collapsed",
                    key=(
                        f"source-upload-{st.session_state.thread_id}-"
                        f"{upload_nonce}"
                    ),
                    help=size_hint,
                    max_upload_size=settings.max_file_size_mb,
                )
                if uploads:
                    _import_uploaded_sources(list(uploads))
            upload_error = st.session_state.pop("source_upload_error", None)
            if upload_error:
                st.error(upload_error)
        if lecture_sync and lecture_sync.errors:
            logger.warning(
                "Course material import issues for notebook %s: %s",
                st.session_state.thread_id,
                "; ".join(lecture_sync.errors),
            )
            st.caption(_SOURCE_IMPORT_PARTIAL_ERROR)
        if sync_error:
            st.error(sync_error)
        if sync_loading:
            st.caption("Loading course materials in the background…")

        search = st.text_input(
            "Search sources",
            placeholder="Search sources",
            label_visibility="collapsed",
            key=f"source-search-{st.session_state.thread_id}",
        )
        # Always show Select all; it only toggles My Sources (personal uploads).
        all_selected, select_all_indeterminate = _select_all_checkbox_state(
            personal_selected_count,
            len(personal_sources_all),
        )
        select_all_state = (
            "indeterminate"
            if select_all_indeterminate
            else "checked"
            if all_selected
            else "unchecked"
        )
        select_all_key = _select_all_widget_key(
            st.session_state.thread_id,
            len(personal_sources_all),
        )
        personal_ids = tuple(str(source["id"]) for source in personal_sources_all)
        st.session_state[select_all_key] = all_selected
        with st.container(key="sources_filters"):
            select_column, sort_column = st.columns([0.58, 0.42], gap="small")
            with select_column:
                with st.container(key="sources_select_all"):
                    st.markdown(
                        f'<span class="cd-select-all-state" '
                        f'data-state="{select_all_state}" aria-hidden="true"></span>',
                        unsafe_allow_html=True,
                    )
                    st.checkbox(
                        "Select all sources",
                        disabled=not personal_sources_all,
                        key=select_all_key,
                        on_change=_persist_select_all_sources,
                        args=(
                            st.session_state.thread_id,
                            select_all_key,
                            personal_ids,
                        ),
                    )
            with sort_column:
                with st.container(key="sources_sort"):
                    sort_label_column, sort_menu_column = st.columns(
                        [0.34, 0.66],
                        gap="small",
                    )
                    sort_label_column.markdown(
                        '<p class="sources-sort-label">Sort:</p>',
                        unsafe_allow_html=True,
                    )
                    with sort_menu_column:
                        sort_mode = _render_source_sort_dropdown(
                            st.session_state.thread_id
                        )
        _set_select_all_checkbox_state(
            checked=all_selected,
            indeterminate=select_all_indeterminate,
        )
        visible_sources = _filter_sources(
            sources,
            query=search,
            type_filter="All",
            sort_mode=sort_mode,
        )
        if sync_loading and not personal_sources_all:
            st.caption(
                "Chat and Thinking Path stay available while course materials import."
            )

    def render_source_card(source: dict[str, Any]) -> None:
        """Render one source row: selectable personal, lock-only course materials."""
        safe_id = source["id"].replace("-", "_")
        locked = is_locked_course_source(source)
        card_key = (
            f"source_card_locked_{safe_id}" if locked else f"source_card_{safe_id}"
        )
        with st.container(key=card_key):
            if locked:
                title_column, menu_column = st.columns(
                    [0.88, 0.12],
                    gap="small",
                )
            else:
                check_column, title_column, menu_column = st.columns(
                    [0.12, 0.76, 0.12],
                    gap="small",
                )
                selected_key = _source_selected_widget_key(source["id"])
                check_column.checkbox(
                    f"Use {source['title']}",
                    label_visibility="collapsed",
                    key=selected_key,
                    on_change=_persist_source_selected,
                    args=(source["id"], selected_key),
                )
            with title_column:
                if title_column.button(
                    source["title"],
                    type="tertiary",
                    use_container_width=True,
                    key=f"view-source-title-{source['id']}",
                ):
                    source_viewer_dialog(source["id"])
                title_column.markdown(
                    f'<div class="source-meta">{escape(source_kind_label(source))} · '
                    f'{format_size(int(source.get("size") or 0))}</div>',
                    unsafe_allow_html=True,
                )
            if locked:
                menu_column.button(
                    "Managed course material",
                    icon=":material/lock:",
                    type="tertiary",
                    disabled=True,
                    key=f"locked-source-{source['id']}",
                    help="Always included in coaching",
                )
            else:
                # Icon in the label (not icon=) so Streamlit hides the expand chevron.
                # Fragment widget interactions already re-run this panel; no app rerun.
                menu = menu_column.popover(
                    ":material/more_horiz:",
                    type="tertiary",
                    key=f"source-menu-{source['id']}",
                    help="Source actions",
                )
                was_open_key = f"source-menu-was-open-{source['id']}"
                was_open = bool(st.session_state.get(was_open_key))
                is_open = bool(menu.open)
                if was_open and not is_open:
                    discard_rename_draft("source", str(source["id"]))
                    bump_rename_epoch("source", str(source["id"]))
                st.session_state[was_open_key] = is_open
                with menu:
                    current_title = str(source.get("title") or "").strip()
                    with st.container(key=f"source_rename_{safe_id}"):
                        applied, cleaned = render_enter_to_apply_rename(
                            kind="source",
                            item_id=str(source["id"]),
                            label="Rename",
                            current_value=current_title,
                        )
                    if applied and cleaned and cleaned != current_title:
                        try:
                            store.rename_source(
                                st.session_state.thread_id,
                                source["id"],
                                cleaned,
                            )
                            rerun_fragment()
                        except Exception:
                            logger.exception(
                                "Source rename failed for notebook %s source %s",
                                st.session_state.thread_id,
                                source["id"],
                            )
                            st.error(_SOURCE_RENAME_ERROR)
                    sync_rename_select_all(
                        root_selector=(
                            f'[data-testid="stPopoverBody"]'
                            f':has(.st-key-source_rename_{safe_id})'
                        ),
                        aria_label="Rename",
                    )
                    if _source_has_downloadable_file(source):
                        try:
                            content = store.get_source_content(
                                st.session_state.thread_id, source["id"]
                            )
                        except Exception:
                            logger.exception(
                                "Source download failed for notebook %s source %s",
                                st.session_state.thread_id,
                                source["id"],
                            )
                            st.error(_SOURCE_DOWNLOAD_ERROR)
                        else:
                            st.download_button(
                                "Download File",
                                data=content.data,
                                file_name=content.filename,
                                mime=content.mime,
                                use_container_width=True,
                                key=f"download-source-{source['id']}",
                            )
                    with st.container(key=f"source_action_danger_{safe_id}"):
                        st.markdown("#### Delete source")
                        confirm = st.checkbox(
                            "I understand this cannot be undone",
                            key=f"confirm-remove-source-{source['id']}",
                        )
                        if st.button(
                            "Delete permanently",
                            icon=":material/delete:",
                            use_container_width=True,
                            disabled=not confirm,
                            key=f"remove-source-{source['id']}",
                        ):
                            store.delete_source(
                                st.session_state.thread_id,
                                source["id"],
                            )
                            rerun_fragment()

    with st.container(key="sources_scroll", height="stretch"):
        grouped_course_sources = {
            group: [
                source
                for source in visible_sources
                if is_locked_course_source(source)
                and (source.get("metadata") or {}).get("course_material_group") == group
            ]
            for group in COURSE_MATERIAL_GROUPS
        }
        personal_sources = [
            source
            for source in visible_sources
            if not is_locked_course_source(source)
        ]
        expander_prefs = _sources_expander_prefs()
        expander_sections: list[tuple[str, str]] = []
        my_sources_key = _ensure_sources_expander_state("My Sources", default=True, saved=expander_prefs)
        expander_sections.append(("My Sources", my_sources_key))
        with st.expander(
            f"My Sources · {len(personal_sources)}",
            expanded=bool(st.session_state.get(my_sources_key, True)),
            key=my_sources_key,
            on_change=_sources_expander_changed,
            args=("My Sources", my_sources_key),
        ):
            if personal_sources:
                for source in personal_sources:
                    render_source_card(source)
            elif not any(not is_locked_course_source(source) for source in sources):
                st.markdown(
                    empty_state_html(
                        title="Add your first source",
                        body=(
                            "Upload a file in the chat or\n"
                            "Add a file in the Sources panel"
                        ),
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No matching personal sources.")
        for group in COURSE_MATERIAL_GROUPS:
            # Keep empty course expanders visible when not filtering away the group.
            group_all = [
                source
                for source in sources
                if is_locked_course_source(source)
                and (source.get("metadata") or {}).get("course_material_group") == group
            ]
            group_sources = _sort_course_sources_by_name(grouped_course_sources[group])
            # Collapsed by default; students open Lecture Notes / Readings as needed.
            group_key = _ensure_sources_expander_state(group, default=False, saved=expander_prefs)
            expander_sections.append((group, group_key))
            with st.expander(
                f"{group} · {len(group_all)}",
                expanded=bool(st.session_state.get(group_key, False)),
                key=group_key,
                # Required for session_state[key] to track open/closed. Without
                # this, the 1s Sources fragment re-applies the seeded expanded
                # value and collapsed sections snap back open.
                on_change=_sources_expander_changed,
                args=(group, group_key),
            ):
                if group_sources:
                    for source in group_sources:
                        render_source_card(source)
                elif not search.strip():
                    st.caption("No materials available yet.")
                else:
                    st.caption("No matching materials in this group.")
        _persist_sources_expander_states(expander_sections)
