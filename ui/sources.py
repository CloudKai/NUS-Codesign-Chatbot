"""Sources panel, dialogs, and source display helpers."""

from __future__ import annotations

import mimetypes
import re
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from backend.settings import settings
from backend.source_library import (
    COURSE_MATERIAL_GROUPS,
    SourceImportError,
    add_file_sources,
    add_text_source,
    add_url_source,
    backfill_legacy_sources,
    is_locked_course_source,
)
from ui.components import empty_state_html
from ui.runtime import course_material_sync, rerun, store


def format_size(size: int) -> str:
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


def safe_source_path(source: dict[str, Any]) -> Path | None:
    path_value = source.get("path")
    if not path_value:
        return None
    path = Path(str(path_value)).resolve()
    files_root = settings.files_dir.resolve()
    if not path.is_file() or files_root not in path.parents:
        return None
    return path


@st.dialog("Add sources", width="medium")
def add_sources_dialog() -> None:
    st.caption("Choose material to ground this notebook’s responses.")
    upload_tab, web_tab, text_tab = st.tabs(["Upload", "Website", "Paste text"])
    with upload_tab:
        uploads = st.file_uploader(
            "Drop files here or browse",
            accept_multiple_files=True,
            key=f"source-upload-{st.session_state.thread_id}",
            help=f"Up to {settings.max_files} files, {settings.max_file_size_mb} MB each.",
        )
        st.caption(
            "PDF, Word, PowerPoint, Excel, images, audio, or text · "
            f"up to {settings.max_files} files · {settings.max_file_size_mb} MB each"
        )
        if st.button(
            "Add to notebook",
            type="primary",
            use_container_width=True,
            disabled=not uploads,
        ):
            try:
                added = add_file_sources(
                    store,
                    st.session_state.thread_id,
                    [
                        (upload.name, upload.getvalue(), getattr(upload, "type", None))
                        for upload in uploads
                    ],
                )
                if added:
                    st.session_state.allow_model_knowledge = False
                    store.update_thread(
                        st.session_state.thread_id,
                        metadata={"allow_model_knowledge": False},
                    )
                st.success(f"Added {len(added)} source{'s' if len(added) != 1 else ''}.")
                rerun()
            except Exception as exc:
                st.error(str(exc))
        st.caption("Files stay in this local notebook.")

    with web_tab:
        url = st.text_input(
            "Public webpage URL",
            placeholder="https://example.edu/article",
            key=f"source-url-{st.session_state.thread_id}",
        )
        st.caption(
            "Safely import a public HTML or plain-text webpage. "
            "Local network URLs are blocked."
        )
        if st.button(
            "Import webpage",
            type="primary",
            use_container_width=True,
            disabled=not url.strip(),
        ):
            try:
                add_url_source(store, st.session_state.thread_id, url)
                st.session_state.allow_model_knowledge = False
                store.update_thread(
                    st.session_state.thread_id,
                    metadata={"allow_model_knowledge": False},
                )
                st.success("Web source added.")
                rerun()
            except SourceImportError as exc:
                st.error(str(exc))

    with text_tab:
        title = st.text_input(
            "Source title",
            placeholder="Lecture notes",
            key=f"pasted-title-{st.session_state.thread_id}",
        )
        text = st.text_area(
            "Source text",
            placeholder="Paste notes, an article excerpt, or assignment material…",
            height=230,
            key=f"pasted-text-{st.session_state.thread_id}",
        )
        if st.button(
            "Add pasted text",
            type="primary",
            use_container_width=True,
            disabled=not text.strip(),
        ):
            try:
                add_text_source(store, st.session_state.thread_id, title, text)
                st.session_state.allow_model_knowledge = False
                store.update_thread(
                    st.session_state.thread_id,
                    metadata={"allow_model_knowledge": False},
                )
                st.success("Text source added.")
                rerun()
            except SourceImportError as exc:
                st.error(str(exc))


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
    path = safe_source_path(source)
    if source.get("sourceUrl"):
        st.link_button(
            "Open original webpage",
            str(source["sourceUrl"]),
            icon=":material/open_in_new:",
        )
    if path and path.suffix.lower() == ".pdf":
        st.pdf(path.read_bytes(), height=560, key=f"pdf-preview-{source_id}")
    elif path and str(source.get("mime") or "").startswith("image/"):
        st.image(str(path), use_container_width=True)
    else:
        text = str(source.get("extractedText") or "").strip()
        if text:
            with st.container(height=500, border=True):
                st.write(text)
        else:
            st.info("This file is stored for download but has no readable text preview.")
    if path and not is_locked_course_source(source):
        mime = str(
            source.get("mime")
            or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream"
        )
        st.download_button(
            "Download source",
            data=path.read_bytes(),
            file_name=path.name,
            mime=mime,
            use_container_width=True,
        )


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


@st.fragment(run_every="1s")
def render_sources_panel() -> None:
    backfill_legacy_sources(store, st.session_state.thread_id)
    sync_future = course_material_sync().request(store, st.session_state.thread_id)
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
        title_column, add_column = st.columns(
            [0.8, 0.2],
            gap="small",
        )
        title_column.markdown(
            '<div class="pane-heading source-pane-heading">'
            '<div class="source-heading-group">'
            '<span class="pane-title">Sources</span>'
            f'<span class="pane-count">{count_label}</span>'
            "</div></div>",
            unsafe_allow_html=True,
        )
        if add_column.button(
            "Add",
            icon=":material/add:",
            use_container_width=True,
            key="add-sources",
        ):
            add_sources_dialog()
        notification_key = f"source-sync-notified-{st.session_state.thread_id}"
        if lecture_sync and (
            lecture_sync.added or lecture_sync.updated or lecture_sync.removed
        ) and st.session_state.get(notification_key) != id(sync_future):
            st.session_state[notification_key] = id(sync_future)
            st.toast("Course materials are ready.")
        if lecture_sync and lecture_sync.errors:
            st.caption(
                "Some lecture notes could not be imported: "
                + "; ".join(lecture_sync.errors)
            )
        if sync_error:
            st.error(sync_error)
        if sync_loading:
            st.status(
                "Loading course materials…",
                state="running",
                expanded=False,
            )
            st.caption(
                "Chat and Thinking Path remain available while Sources finish loading."
            )
            return

        search = st.text_input(
            "Search sources",
            placeholder="Search sources",
            label_visibility="collapsed",
            key=f"source-search-{st.session_state.thread_id}",
        )
        with st.container(key="sources_filters"):
            type_column, sort_column = st.columns(2, gap="small")
            type_filter = type_column.selectbox(
                "Source type",
                ["All", "PDF", "Web", "Text", "Image", "Course", "File"],
                key=f"source-type-filter-{st.session_state.thread_id}",
            )
            sort_mode = sort_column.selectbox(
                "Sort",
                ["Recent", "Name"],
                key=f"source-sort-{st.session_state.thread_id}",
            )
        visible_sources = _filter_sources(
            sources,
            query=search,
            type_filter=type_filter,
            sort_mode=sort_mode,
        )
        if sources:
            all_selected = selected_count == len(sources)
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
            if title_column.button(
                source["title"],
                type="tertiary",
                use_container_width=True,
                key=f"view-source-title-{source['id']}",
            ):
                source_viewer_dialog(source["id"])
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
                with menu_column.popover(
                    "⋯",
                    type="tertiary",
                    help="Preview, rename, or delete",
                ):
                    if st.button(
                        "Preview",
                        icon=":material/visibility:",
                        use_container_width=True,
                        key=f"view-source-{source['id']}",
                    ):
                        source_viewer_dialog(source["id"])
                    renamed = st.text_input(
                        "Rename",
                        value=str(source.get("title") or ""),
                        key=f"rename-source-input-{source['id']}",
                    )
                    if st.button(
                        "Save name",
                        use_container_width=True,
                        key=f"rename-source-{source['id']}",
                    ):
                        try:
                            store.rename_source(
                                st.session_state.thread_id,
                                source["id"],
                                renamed,
                            )
                            st.toast("Source renamed.")
                            rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    path = safe_source_path(source)
                    if path:
                        st.download_button(
                            "Download",
                            data=path.read_bytes(),
                            file_name=path.name,
                            mime=str(source.get("mime") or "application/octet-stream"),
                            use_container_width=True,
                            key=f"download-source-{source['id']}",
                        )
                    st.divider()
                    confirm = st.checkbox(
                        "Confirm delete",
                        key=f"confirm-remove-source-{source['id']}",
                    )
                    if st.button(
                        "Delete",
                        icon=":material/delete:",
                        use_container_width=True,
                        disabled=not confirm,
                        key=f"remove-source-{source['id']}",
                    ):
                        store.delete_source(st.session_state.thread_id, source["id"])
                        rerun()
            st.markdown(
                f'<div class="source-meta">{escape(source_kind_label(source))} · '
                f'{format_size(int(source.get("size") or 0))}</div>',
                unsafe_allow_html=True,
            )

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
            show_group = type_filter in {"All", "Course"} or bool(group_sources)
            if not show_group and type_filter != "All":
                continue
            with st.expander(
                f"{group} · {len(group_sources if type_filter != 'All' else group_all)}",
                expanded=True,
            ):
                if group_sources:
                    for source in group_sources:
                        render_source_card(source)
                elif type_filter == "All" and not search.strip():
                    st.caption("No materials available yet.")
                else:
                    st.caption("No matching materials in this group.")
        with st.expander(f"My Sources · {len(personal_sources)}", expanded=True):
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

