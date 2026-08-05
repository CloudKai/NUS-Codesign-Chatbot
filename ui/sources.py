"""Sources panel, dialogs, and source display helpers."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from backend.settings import settings
from backend.source_library import COURSE_MATERIAL_GROUPS, is_locked_course_source
from ui.components import empty_state_html
from ui.rename import (
    bump_rename_epoch,
    discard_rename_draft,
    render_enter_to_apply_rename,
    sync_rename_select_all,
)
from ui.runtime import rerun, store


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
    except Exception as exc:
        st.session_state["source_upload_error"] = str(exc)
        # Clear the picker so the fragment stops retrying the failed selection.
        st.session_state["source_upload_nonce"] = nonce + 1
        rerun()
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
    rerun()


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


def _ensure_sources_expander_state(section: str, *, default: bool = True) -> str:
    """Seed expander open/closed state from preferences after a browser refresh.

    Returns:
        The Streamlit widget key for ``st.expander``.
    """
    widget_key = _sources_expander_widget_key(section)
    if widget_key not in st.session_state:
        prefs = store.get_user_preferences() or {}
        saved = prefs.get("sources_expander_state")
        if isinstance(saved, dict) and section in saved:
            st.session_state[widget_key] = bool(saved[section])
        else:
            st.session_state[widget_key] = default
    return widget_key


def _persist_sources_expander_state(section: str, widget_key: str) -> None:
    """Remember expander open/closed state across refreshes when it changes."""
    expanded = bool(st.session_state.get(widget_key, True))
    prefs = store.get_user_preferences() or {}
    saved_raw = prefs.get("sources_expander_state")
    saved = dict(saved_raw) if isinstance(saved_raw, dict) else {}
    if saved.get(section) is expanded:
        return
    saved[section] = expanded
    store.update_user_preferences({"sources_expander_state": saved})


def _sources_expander_changed(section: str, widget_key: str) -> None:
    """Persist as soon as the student expands or collapses a Sources section."""
    _persist_sources_expander_state(section, widget_key)

@st.fragment(run_every="1s")
def render_sources_panel() -> None:
    store.backfill_legacy_sources(st.session_state.thread_id)
    sync_future = store.request_course_material_sync(st.session_state.thread_id)
    sync_loading = not sync_future.done()
    lecture_sync = None
    sync_error = ""
    if not sync_loading:
        try:
            lecture_sync = sync_future.result()
        except Exception as exc:
            sync_error = str(exc) or "Course materials could not be loaded."
    sources = store.list_sources(st.session_state.thread_id)
    selected_count = sum(1 for source in sources if source["selected"])
    count_label = "Loading…" if sync_loading else f"{selected_count} selected"
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
                st.markdown(
                    '<div class="cd-sources-add-face" aria-hidden="true">+ Add</div>',
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
                    help=(
                        f"Choose files to add · up to {settings.max_files} files · "
                        f"{settings.max_file_size_mb} MB each"
                    ),
                )
                if uploads:
                    _import_uploaded_sources(list(uploads))
            upload_error = st.session_state.pop("source_upload_error", None)
            if upload_error:
                st.error(upload_error)
        if lecture_sync and lecture_sync.errors:
            st.caption(
                "Some lecture notes could not be imported: "
                + "; ".join(lecture_sync.errors)
            )
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
        visible_sources = _filter_sources(
            sources,
            query=search,
            type_filter="All",
            sort_mode="Recent",
        )
        if sources:
            all_selected = selected_count == len(sources)
            with st.container(key="sources_select_all"):
                next_all = st.checkbox(
                    "Select all sources",
                    value=all_selected,
                    key=(
                        f"all-sources-{st.session_state.thread_id}-"
                        f"{len(sources)}-{selected_count}"
                    ),
                )
            if next_all != all_selected:
                store.set_all_sources_selected(st.session_state.thread_id, next_all)
                if next_all:
                    st.session_state.allow_model_knowledge = False
                    store.update_thread(
                        st.session_state.thread_id,
                        metadata={"allow_model_knowledge": False},
                    )
                rerun()
        elif sync_loading:
            st.caption(
                "Chat and Thinking Path stay available while course materials import."
            )

    def render_source_card(source: dict[str, Any]) -> None:
        """Render one selectable source with preview and edit actions."""
        safe_id = source["id"].replace("-", "_")
        locked = is_locked_course_source(source)
        with st.container(key=f"source_card_{safe_id}"):
            check_column, title_column, menu_column = st.columns(
                [0.12, 0.76, 0.12],
                gap="small",
            )
            selected = check_column.checkbox(
                f"Use {source['title']}",
                value=source["selected"],
                label_visibility="collapsed",
                key=f"source-selected-{source['id']}-{int(source['selected'])}",
            )
            if selected != source["selected"]:
                store.set_source_selected(
                    st.session_state.thread_id,
                    source["id"],
                    selected,
                )
                if selected:
                    st.session_state.allow_model_knowledge = False
                    store.update_thread(
                        st.session_state.thread_id,
                        metadata={"allow_model_knowledge": False},
                    )
                rerun()
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
                    help="Managed course material",
                )
            else:
                # Icon in the label (not icon=) so Streamlit hides the expand chevron.
                menu = menu_column.popover(
                    ":material/more_horiz:",
                    type="tertiary",
                    key=f"source-menu-{source['id']}",
                    help="Source actions",
                    on_change="rerun",
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
                            rerun()
                        except Exception as exc:
                            st.error(str(exc))
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
                        except Exception as exc:
                            st.error(str(exc))
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
                            rerun()

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
        for group in COURSE_MATERIAL_GROUPS:
            # Keep empty course expanders visible when not filtering away the group.
            group_all = [
                source
                for source in sources
                if is_locked_course_source(source)
                and (source.get("metadata") or {}).get("course_material_group") == group
            ]
            group_sources = _sort_course_sources_by_name(grouped_course_sources[group])
            group_key = _ensure_sources_expander_state(group, default=True)
            with st.expander(
                f"{group} · {len(group_all)}",
                expanded=bool(st.session_state.get(group_key, True)),
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
            _persist_sources_expander_state(group, group_key)
        my_sources_key = _ensure_sources_expander_state("My Sources", default=True)
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
        _persist_sources_expander_state("My Sources", my_sources_key)
