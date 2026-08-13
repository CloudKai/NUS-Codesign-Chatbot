from pathlib import Path

from streamlit.testing.v1 import AppTest

from backend.settings import settings


def test_student_message_actions_are_always_visible():
    """Keep copy/edit discoverable without requiring hover or touch guessing."""
    chat_css = Path("ui/assets/styles/30-chat.css").read_text(encoding="utf-8")
    actions_rule = chat_css.split(
        '[class*="st-key-user_message_actions_"] {', 1
    )[1].split("}", 1)[0]

    assert "opacity:1 !important" in actions_rule
    assert "opacity:0" not in actions_rule


def test_completed_journey_stages_keep_their_icon_and_add_green_tick():
    """Completion supplements rather than replaces each stage-specific icon."""
    studio_source = Path("ui/studio.py").read_text(encoding="utf-8")
    foundations = Path("ui/assets/styles/00-foundations.css").read_text(
        encoding="utf-8"
    )

    assert "icon_name = stage_icons[stage.id]" in studio_source
    assert "journey-complete-badge" in studio_source
    assert '"check_circle</span>"' in studio_source
    assert "max(completed_count, stage_index - 1)" not in studio_source
    assert "progress_bar_html" not in studio_source
    assert "Revisit a completed stage." not in studio_source
    assert ".cd-roadmap-node .journey-complete-badge" in foundations
    assert "color:var(--cd-success)" in foundations
    assert "background:var(--cd-surface)" in foundations
    assert "if stage.id in completed" in studio_source


def test_chat_composer_attachment_error_is_recoverable(monkeypatch):
    """Rejecting a chat attachment leaves the notebook usable and unsent."""
    from ui import chat

    class FailedUpload:
        """Minimal uploaded-file stand-in for the composer submission."""

        name = "oversized.pdf"
        type = "application/pdf"

        @staticmethod
        def getvalue() -> bytes:
            """Return deterministic content if the UI reaches the upload adapter."""
            return b"not actually uploaded"

    def reject_upload(*_args, **_kwargs):
        raise ValueError("Attachment exceeds the permitted size")

    monkeypatch.setattr(
        chat,
        "normalize_composer_value",
        lambda _value: ("Please review this attachment.", [FailedUpload()]),
    )
    monkeypatch.setattr(chat.store, "upload_sources", reject_upload)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    assert not app.exception
    rendered_errors = "\n".join(error.value or "" for error in app.error)
    assert "attachment could not be added" in rendered_errors.lower()
    assert "no message was sent" in rendered_errors.lower()
    thread_id = app.session_state["thread_id"]
    from backend.student_store import StudentStore

    assert [message["role"] for message in StudentStore().get_messages(thread_id)] == [
        "assistant"
    ]


def test_streamlit_notebook_workspace_smoke():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert app.session_state["appearance"] == "Light"
    assert "AttributeError" not in "\n".join(
        str(exception.value) for exception in app.exception
    )
    assert len(app.chat_input) == 1
    composer = app.chat_input[0]
    assert composer.placeholder == "Ask a question or share your thinking"
    assert composer.proto.accept_file
    assert not composer.proto.accept_audio
    assert composer.proto.max_upload_size_mb == settings.max_file_size_mb

    assert not any(
        (button.key or "").startswith("profile-language-") for button in app.button
    )
    assert any(control.label == "Appearance" for control in app.segmented_control)
    workspace_panel = next(
        radio for radio in app.radio if radio.label == "Workspace panel"
    )
    assert workspace_panel.options == ["Journey", "Chat", "Sources"]
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    coaching_style = next(
        control
        for control in app.segmented_control
        if control.label == "Coaching style"
    )
    assert coaching_style.options == ["Quick", "Strict"]
    assert {tab.label for tab in app.tabs} >= {"Journey", "Review"}

    assert '<span class="pane-title">Sources</span>' in rendered
    assert "Welcome back. What are you working through today?" in rendered
    assert "question assumptions" in rendered
    notebook_title = next(
        text_input for text_input in app.text_input if text_input.label == "Notebook title"
    )
    assert notebook_title.value == "Untitled notebook"
    assert '<span class="pane-title">Thinking Path</span>' in rendered
    assert "CDE2300 Design Thinking Companion" in rendered
    assert "Product Design and Innovation" in rendered
    assert 'aria-label="Critical-thinking journey"' in rendered
    assert "Focus" in rendered
    assert "Conclusion" in rendered
    assert "Summary" in rendered
    assert "Critical thinking (Facione)" in rendered
    assert "strongest evidence demonstrated under the Quick profile" in rendered
    assert "Intended to support reflection, not grading." in rendered
    assert "Discussion summary" in rendered
    assert "What to strengthen" in rendered
    assert {expander.label for expander in app.expander} >= {
        "Strengths",
        "Areas for improvement",
        "Working conclusion",
        "Define the focus",
        "Examine evidence",
        "Lecture Notes · 0",
        "Readings · 0",
        "My Sources · 0",
    }
    sources_py = Path("ui/sources.py").read_text(encoding="utf-8")
    my_sources_at = sources_py.index('f"My Sources · {len(personal_sources)}"')
    lecture_at = sources_py.index('f"{group} · {len(group_all)}"')
    assert my_sources_at < lecture_at
    assert '_ensure_sources_expander_state(group, default=False)' in sources_py
    assert '_ensure_sources_expander_state("My Sources", default=True)' in sources_py
    assert "source_card_locked_" in sources_py
    assert "Course material · Available for relevant reference" in rendered
    assert "disabled=locked" not in sources_py
    assert 'key="sources_filters"' in sources_py
    assert "sources-sort-label" in sources_py
    assert "_render_source_sort_dropdown" in sources_py
    assert "personal_sources_all" in sources_py
    assert "Select all sources" in sources_py
    assert "Clarify the question, problem, or claim" in rendered
    assert "Add your first source" in rendered
    assert "Loading course materials in the background…" in Path("ui/sources.py").read_text(
        encoding="utf-8"
    )
    assert 'st.session_state["source_upload_error"] = str(exc)' not in sources_py
    assert "st.error(str(exc))" not in sources_py
    assert "st.error(str(exc))" not in Path("ui/studio.py").read_text(encoding="utf-8")
    assert "_STAGE_SELECT_ERROR" in Path("ui/studio.py").read_text(encoding="utf-8")
    assert "_TRANSITION_RESOLVE_ERROR" in Path("ui/studio.py").read_text(
        encoding="utf-8"
    )
    assert 'click Send' in Path("ui/chat.py").read_text(encoding="utf-8")
    assert "st.session_state.pop(\"pending_edit\", None)" in Path("ui/chat.py").read_text(
        encoding="utf-8"
    )
    assert "_SOURCE_UPLOAD_ERROR" in sources_py
    assert "_SOURCE_SYNC_ERROR" in sources_py
    assert "_SOURCE_RENAME_ERROR" in sources_py
    assert "_SOURCE_DOWNLOAD_ERROR" in sources_py
    assert "logger.exception" in sources_py
    assert "st.caption(_SOURCE_IMPORT_PARTIAL_ERROR)" in sources_py
    assert 'st.caption(\n                "Some lecture notes could not be imported:' not in sources_py
    assert rendered.index('<span class="pane-title">Thinking Path</span>') < rendered.index(
        'class="message-meta coach-welcome"'
    ) < rendered.index('<span class="pane-title">Sources</span>')
    assert ".st-key-chat_log" in rendered
    assert "overflow-y:auto" in rendered
    assert "scrollbar-color:var(--cd-scrollbar) transparent" in rendered
    assert "max-height:calc(1em * 1.45 * 5)" in rendered
    assert "max-width:80ch" in rendered
    assert "max-width:min(100%, calc(80ch + 16px))" in rendered
    assert "max-height:none !important" in rendered
    assert "max-height:11rem" not in rendered
    assert "min-height:3.25rem" in rendered
    assert "MAX_ROWS = 5" in Path("ui/layout/composer_layout.py").read_text(
        encoding="utf-8"
    )
    assert "MAX_COLS" not in Path("ui/layout/composer_layout.py").read_text(
        encoding="utf-8"
    )
    edit_layout = Path("ui/layout/user_message_edit_layout.py").read_text(
        encoding="utf-8"
    )
    assert "USER_BUBBLE_MAX_ROWS = 8" in edit_layout
    assert "USER_MESSAGE_EDIT_HEIGHT_PX" in edit_layout
    assert "__cdUserEditCleanup" in edit_layout
    assert "--cd-user-bubble-max-rows:8" in rendered
    assert "--cd-user-bubble-max-height" in rendered
    chat_py = Path("ui/chat.py").read_text(encoding="utf-8")
    assert "USER_MESSAGE_EDIT_HEIGHT_PX" in chat_py
    assert '"height": USER_MESSAGE_EDIT_HEIGHT_PX' in chat_py or (
        "height=USER_MESSAGE_EDIT_HEIGHT_PX" in chat_py
    )
    assert "sync_user_message_edit_layout" in chat_py
    assert "user_message_edit_" in chat_py
    assert "revise_message" in chat_py
    assert "pending_edit" in chat_py
    assert "_restore_pending_edit_draft" in chat_py
    assert "_conversation_revision_label" not in chat_py
    assert "conversation-revision-label" not in chat_py
    assert 'f"Conversation {revision + 1:02d}"' not in chat_py
    assert "idempotency_key" in chat_py
    assert 'stage=f"revise:{message' in chat_py or "revise:" in chat_py
    assert "creates a new conversation revision" in chat_py
    assert "remain in revision history" in chat_py
    assert "will replace the conversation after this point" not in chat_py
    assert "truncate" not in chat_py.lower()
    assert "Save & resend" not in chat_py
    assert "Editing message" not in chat_py
    assert "composer_edit" not in chat_py
    assert "conversation-revision-label" not in rendered
    assert "Conversation 01" not in rendered
    assert ".conversation-revision-label" not in Path(
        "ui/assets/styles/30-chat.css"
    ).read_text(encoding="utf-8")
    assert 'appearance == "Dark"' in Path("ui/chat.py").read_text(encoding="utf-8")
    assert "#5B6875" in Path("ui/chat.py").read_text(encoding="utf-8")
    assert "rgba(255, 255, 255, 0.35)" in Path("ui/chat.py").read_text(
        encoding="utf-8"
    )
    assert "#A4ADB3" in Path("ui/chat.py").read_text(encoding="utf-8")
    assert "rgba(15, 20, 25, 0.72)" not in Path("ui/chat.py").read_text(
        encoding="utf-8"
    )
    assert "writing-mode:horizontal-tb" in rendered
    assert "grid-template-columns:minmax(0,1fr) auto" in rendered
    assert "stChatInputTextArea" in rendered
    assert "arrow_upward" in rendered
    assert "cd-composer-card" in Path("ui/layout/composer_layout.py").read_text(encoding="utf-8")
    assert (
        '[data-testid="stHeaderActionElements"] {\n'
        "        display:none !important;"
    ) in rendered
    assert "stChatInputMicButton" in rendered
    assert "coach-welcome-title" in rendered
    assert "st-key-topbar_navigation" in rendered
    assert "color:var(--cd-text) !important" in rendered
    assert "background:transparent !important" in rendered
    assert "place-items:center" in rendered
    assert (
        '[data-testid="stChatMessageAvatarCustom"] {\n'
        "        display:none !important;"
    ) in rendered
    assert "st-key-topbar_profile" in rendered
    assert "gap:.82rem" in rendered
    assert "margin-bottom:.34rem" in rendered
    assert "journey-stage-detail" in rendered
    assert "journey-copy-stack" in rendered
    assert "st-key-journey-toggle-" in rendered
    assert "justify-content:flex-end" in rendered
    assert "text-align:left" in rendered
    assert "background:var(--cd-surface)" in rendered
    assert "justify-content:flex-start !important" in rendered
    assert ".journey-question-list {" in rendered
    assert '[role="listbox"] [role="option"]' in rendered
    assert "-webkit-text-fill-color:currentColor" in rendered
    assert "--cd-bg:#F4F6F7" in rendered
    assert "--cd-panel:#F1F3F4" in rendered
    assert "--cd-text:#15202B" in rendered
    assert "--cd-accent:#0F766E" in rendered
    assert "cd-col-resize-handle" in rendered
    assert "cd-col-rail" in rendered
    assert ":has(.st-key-studio_rail)" in rendered
    assert any(button.label == "‹" for button in app.button)
    assert any(button.label == "›" for button in app.button)
    assert "cd-roadmap" in rendered
    # Footer Next is present but disabled without a pending coach recommendation / local API.
    assert any(button.label == "Next" for button in app.button)
    journey_block = Path("ui/studio.py").read_text(encoding="utf-8").split(
        "with journey_tab:", 1
    )[1].split("with review_tab:", 1)[0]
    assert "render_thinking_path_footer()" in journey_block
    assert "IBM Plex Sans" in rendered
    assert "background:var(--cd-panel)" in rendered

    button_labels = {button.label for button in app.button}
    assert "Notebooks" in button_labels
    assert len(app.file_uploader) >= 1
    assert any(
        (uploader.label or "") == "Add" for uploader in app.file_uploader
    )

    assert any(input_widget.label == "Display name" for input_widget in app.text_input)
    assert any(control.label == "Appearance" for control in app.segmented_control)
    assert "cd-profile-language-label" not in rendered
    assert "cd-profile-menu" in rendered
    assert "cd-profile-help-title" in rendered
    assert "cd-profile-help-title" in rendered
    assert "cd-profile-help-body" in rendered
    assert "stTooltipHoverTarget" in rendered
    assert "st-key-composer_model_slot" not in rendered
    assert not any(
        (button.key or "").startswith("composer-model-") for button in app.button
    )
    assert not any(
        (button.key or "").startswith("composer-effort-") for button in app.button
    )
    assert "st-key-chat_composer" in rendered
    assert len(app.chat_message) == 1
    assert app.chat_message[0].name == "assistant"


def test_profile_coaching_style_maps_to_existing_response_detail():
    """Human-facing labels persist the existing short/long journey values."""
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    strict = next(
        control
        for control in app.segmented_control
        if control.label == "Coaching style"
    )
    assert strict.value == "Quick"
    strict.set_value("Strict").run()

    assert not app.exception
    assert app.session_state["response_detail"] == "long"
    assert app.session_state["learning_journey"]["response_detail"] == "long"
    stored = StudentStore().get_thread(app.session_state["thread_id"])
    assert stored is not None
    assert stored["metadata"]["learning_journey"]["response_detail"] == "long"


def test_facione_table_is_numeric_and_preserves_accessible_rubric_meaning():
    """Numeric scores retain the canonical rubric cues without duplicating speech."""
    from ui.components import facione_scores_table_html

    rendered = facione_scores_table_html(
        {
            "analysis": 0,
            "interpretation": 1,
            "inference": 2,
            "evaluation": 3,
            "explanation": 4,
        }
    )

    assert "1 / 4" in rendered
    assert "2 / 4" in rendered
    assert "3 / 4" in rendered
    assert "4 / 4" in rendered
    assert "Not started" in rendered
    assert 'aria-label="Inference: 2 out of 4, Unacceptable"' in rendered
    rubric_glyphs = {
        "Not started": "radio_button_unchecked",
        "Weak": "sentiment_very_dissatisfied",
        "Unacceptable": "sentiment_dissatisfied",
        "Acceptable": "sentiment_satisfied",
        "Strong": "sentiment_very_satisfied",
    }
    for rubric, glyph in rubric_glyphs.items():
        assert (
            f'aria-hidden="true" title="{rubric}">{glyph}</span>' in rendered
        )
    assert "Intended to support reflection, not grading." in rendered
    assert "strongest evidence demonstrated under the Quick profile" in rendered

    strict_rendered = facione_scores_table_html(
        {"analysis": 2},
        coaching_style="long",
    )
    assert "Existing progress is retained" in strict_rendered
    assert "higher Strict threshold" in strict_rendered


def test_legacy_welcome_message_renders_current_canonical_copy():
    """Older persisted welcome content needs no destructive data migration."""
    from backend.models import LOCKED_CHAT_MODEL_ID
    from backend.student_store import StudentStore
    from backend.student_support import DEFAULT_SUPPORT_MODE

    local_store = StudentStore()
    thread_id = local_store.create_thread(
        name="Existing notebook",
        model_id=LOCKED_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
    )
    local_store.add_message(
        thread_id,
        "assistant",
        "**Welcome to your critical-thinking coach**\n\nOld welcome body.",
        metadata={"kind": "coach_welcome", "workflow": "welcome"},
    )
    local_store.update_user_preferences({"active_thread_id": thread_id})

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Welcome back. What are you working through today?" in rendered
    assert "Old welcome body." not in rendered
    assert not app.exception


def test_notebook_activity_helpers_use_existing_payload_fields():
    """Notebook metadata stays presentation-only and deterministic."""
    from datetime import datetime, timezone

    from ui.notebooks import _message_count_label, _relative_activity

    now = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    assert _relative_activity("2026-08-12T01:00:00Z", now=now) == "today"
    assert _relative_activity("2026-08-11T01:00:00Z", now=now) == "yesterday"
    assert _relative_activity("2026-08-09T01:00:00Z", now=now) == "3 days ago"
    assert _message_count_label(1) == "1 message"
    assert _message_count_label(2) == "2 messages"


def test_student_composer_hides_model_infrastructure_but_keeps_internal_config():
    """Configured model values remain available without a student-facing picker."""
    from backend.models import DEFAULT_CHAT_MODEL_ID

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert app.session_state["selected_model"] == DEFAULT_CHAT_MODEL_ID
    assert app.session_state["reasoning_effort"] == "low"
    assert not any(
        (button.key or "").startswith(("composer-model-", "composer-effort-"))
        for button in app.button
    )
    assert len(app.chat_input) == 1
    assert not app.exception


def test_add_source_explains_configured_per_file_size_limit() -> None:
    """The compact Add control exposes only the configured per-file size limit."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    add_uploader = next(
        uploader for uploader in app.file_uploader if uploader.label == "Add"
    )

    assert not add_uploader.help
    assert "cd-sources-add-hint" not in rendered

    sources_css = Path("ui/assets/styles/40-sources.css").read_text(encoding="utf-8")
    assert "cd-sources-add-hint" not in sources_css

    sources_source = Path("ui/sources.py").read_text(encoding="utf-8")
    composer_source = Path("ui/layout/composer_layout.py").read_text(
        encoding="utf-8"
    )
    chat_source = Path("ui/chat.py").read_text(encoding="utf-8")
    assert "_sync_add_source_upload_hint(upload_limits_hint)" in sources_source
    assert 'tooltip.id = "cd-sources-add-tooltip"' in sources_source
    assert 'width: "max-content"' in sources_source
    assert 'whiteSpace: "nowrap"' in sources_source
    assert 'doc.body.appendChild(tooltip)' in sources_source
    assert 'target.removeAttribute("title")' in sources_source
    assert 'target.setAttribute("aria-label", "Upload files · " + hint)' in sources_source
    assert 'f"Up to {settings.max_files} files per message"' not in sources_source
    assert 'uploadTargets.forEach((target)' in composer_source
    assert 'target.removeAttribute("title")' in composer_source
    assert "appendLimitsToTooltip" in composer_source
    assert 'limit.className = "cd-composer-upload-limit"' in composer_source
    assert 'tooltip.appendChild(limit)' in composer_source
    assert "win.__cdComposerLayoutCleanup" in composer_source
    assert "mutationObserver.disconnect()" in composer_source
    assert "resizeObserver.disconnect()" in composer_source
    assert 'win.removeEventListener("resize", inputHandler)' in composer_source
    assert "sync_composer_layout(upload_limits_hint=upload_limits_hint)" in chat_source
    assert 'f"Up to {settings.max_files} files per message"' not in chat_source
    assert 'upload_limits_hint = f"{settings.max_file_size_mb} MB max per file"' in (
        chat_source
    )


def test_add_pasted_source_then_chat_with_citation():
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert any((uploader.label or "") == "Add" for uploader in app.file_uploader)

    local_store = StudentStore()
    add_text_source(
        local_store,
        app.session_state["thread_id"],
        "Lecture evidence",
        "The study included eighty students and compared two teaching methods.",
    )
    app.run()
    assert not app.exception
    assert any(
        checkbox.label == "Select all sources" for checkbox in app.checkbox
    )
    assert any(
        button.label == "Lecture evidence" for button in app.button
    )

    app.chat_input[0].set_value("What evidence does my source provide?").run()
    assert not app.exception
    # Welcome + student turn + coach reply.
    assert len(app.chat_message) == 3
    assert not any(
        (expander.label or "").startswith("Sources used (") for expander in app.expander
    )
    assert any(
        (button.label or "").startswith("[S1] Lecture evidence")
        for button in app.button
    )


def test_select_all_sources_renders_indeterminate_marker_for_partial_selection():
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    local_store = StudentStore()
    thread_id = app.session_state["thread_id"]
    add_text_source(local_store, thread_id, "First source", "First source text.")
    add_text_source(local_store, thread_id, "Second source", "Second source text.")
    app.run()

    next(
        checkbox
        for checkbox in app.checkbox
        if checkbox.label == "Use First source"
    ).set_value(False).run()

    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert 'class="cd-select-all-state"' in rendered
    assert 'data-state="indeterminate"' in rendered
    select_all = next(
        checkbox for checkbox in app.checkbox if checkbox.label == "Select all sources"
    )
    assert select_all.value is False


def test_multiple_selected_sources_do_not_force_sources_used_footer():
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    local_store = StudentStore()
    thread_id = app.session_state["thread_id"]
    add_text_source(local_store, thread_id, "Lecture evidence", "First source.")
    add_text_source(local_store, thread_id, "Reading evidence", "Second source.")
    app.run()

    app.chat_input[0].set_value("Compare the selected evidence.").run()

    assert not app.exception
    source_expanders = [
        expander
        for expander in app.expander
        if expander.label.startswith("Sources used (")
    ]
    assert source_expanders == []


def test_pdf_source_opens_in_installed_viewer():
    from io import BytesIO

    from backend.source_library import add_file_sources
    from backend.student_store import StudentStore
    from pypdf import PdfWriter

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    pdf_buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(pdf_buffer)
    local_store = StudentStore()
    add_file_sources(
        local_store,
        app.session_state["thread_id"],
        [("Preview test.pdf", pdf_buffer.getvalue(), "application/pdf")],
    )

    app.run()
    next(button for button in app.button if button.label == "Preview test.pdf").click().run()

    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Preview test.pdf" in rendered


def test_learning_studio_and_notebook_history_controls():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Thinking Path" in rendered
    assert "Summary" in rendered
    assert "Critical thinking (Facione)" in rendered
    assert "Discussion summary" in rendered
    next(button for button in app.button if button.label == "Notebooks").click().run()
    assert not app.exception
    assert any(
        text_input.label == "Search notebooks" for text_input in app.text_input
    )
    assert any(
        button.label == "New notebook" for button in app.button
    )
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "notebook-card-meta" in rendered
    assert "of 6" in rendered


def test_english_only_theme_and_journey_has_no_manual_progression_control():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    # Preferences live in the profile settings popover (content exposed to AppTest).

    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    profile_source = Path("ui/profile.py").read_text(encoding="utf-8")
    assert "cd-profile-language-label" not in rendered
    assert "profile-language" not in profile_source
    assert app.session_state["response_language"] == "English"
    assert 'doc.addEventListener("pointerover", onProfilePointerOver, true)' in profile_source
    assert "documentBody && documentBody.nodeType === 1" in profile_source

    # Profile content remains available for appearance changes.
    appearance = next(
        control
        for control in app.segmented_control
        if control.label == "Appearance"
    )
    assert appearance.options == ["System", "Light", "Dark"]
    appearance.set_value("Dark").run()
    assert app.session_state["appearance"] == "Dark"
    assert StudentStore().get_user_preferences().get("appearance") == "Dark"
    assert not app.exception

    # Fresh session reload restores the stored appearance.
    restored = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert restored.session_state["appearance"] == "Dark"
    assert restored.session_state["setting_appearance"] == "Dark"
    assert StudentStore().get_user_preferences().get("appearance") == "Dark"

    assert app.session_state["learning_journey"]["current_stage"] == "focus"
    assert not any(button.label == "Work on this stage" for button in app.button)
    assert not app.exception


def test_phase_two_journey_selects_any_non_current_stage(monkeypatch):
    from backend.student_store import StudentStore
    from backend.settings import settings

    monkeypatch.setattr(settings, "student_stage_selection", True)
    monkeypatch.setattr(settings, "auto_advance_stages", False)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = app.session_state["thread_id"]
    work_buttons = [
        button for button in app.button if button.label == "Work on this stage"
    ]
    assert len(work_buttons) == 5
    assert {button.key for button in work_buttons} == {
        "journey-select-evidence",
        "journey-select-assumptions",
        "journey-select-perspectives",
        "journey-select-synthesis",
        "journey-select-conclusion",
    }
    next(
        button
        for button in work_buttons
        if button.key == "journey-select-synthesis"
    ).click().run()
    assert app.session_state["learning_journey"]["current_stage"] == "synthesis"
    assert app.session_state["learning_journey"]["completed_stages"] == []

    journey = {
        "current_stage": "evidence",
        "completed_stages": ["focus"],
    }
    StudentStore().update_thread(
        thread_id,
        metadata={"thinking_stage": "evidence", "learning_journey": journey},
    )
    app.session_state["learning_journey"] = journey
    app.run()

    revisit_buttons = [
        button for button in app.button if button.label == "Revisit this stage"
    ]
    work_buttons = [
        button for button in app.button if button.label == "Work on this stage"
    ]
    assert len(revisit_buttons) == 1
    assert revisit_buttons[0].key == "journey-select-focus"
    assert len(work_buttons) == 4
    assert {button.key for button in work_buttons} == {
        "journey-select-assumptions",
        "journey-select-perspectives",
        "journey-select-synthesis",
        "journey-select-conclusion",
    }
    captions = "\n".join(caption.value or "" for caption in app.caption)
    assert "Revisit a completed stage." not in captions

    revisit_buttons[0].click().run()
    assert app.session_state["learning_journey"]["current_stage"] == "focus"
    assert app.session_state["learning_journey"]["completed_stages"] == ["focus"]
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "journey-complete-badge" in rendered

    mixed_journey = {
        "current_stage": "conclusion",
        "completed_stages": ["focus", "evidence"],
    }
    StudentStore().update_thread(
        thread_id,
        metadata={
            "thinking_stage": "conclusion",
            "learning_journey": mixed_journey,
        },
    )
    app.session_state["learning_journey"] = mixed_journey
    app.run()
    assert len(
        [button for button in app.button if button.label == "Revisit this stage"]
    ) == 2
    assert len(
        [button for button in app.button if button.label == "Work on this stage"]
    ) == 3
    assert not app.exception


def test_stage_selection_action_renders_after_preview_guidance():
    """Expanded stage actions follow the description and suggested questions."""
    studio_source = Path("ui/studio.py").read_text(encoding="utf-8")
    inactive_stage_block = studio_source.split(
        'if state == "current" or is_preview_open:', 1
    )[1].split("def _sync_review_stage_expander_state", 1)[0]

    assert inactive_stage_block.index("_render_stage_suggestions(stage)") < (
        inactive_stage_block.index("_render_stage_selection_action(stage")
    )
    assert 'st.columns([0.13, 0.87], gap="small")' in studio_source


def test_stale_appearance_widget_does_not_overwrite_stored_dark():
    """DB appearance wins over a leftover settings-widget value on init."""
    from backend.student_store import StudentStore

    StudentStore().update_user_preferences({"appearance": "Dark"})

    app = AppTest.from_file("streamlit_app.py", default_timeout=30)
    app.session_state["setting_appearance"] = "Light"
    app.run()

    assert app.session_state["appearance"] == "Dark"
    assert app.session_state["setting_appearance"] == "Dark"
    assert StudentStore().get_user_preferences().get("appearance") == "Dark"
    assert not app.exception

    appearance = next(
        control
        for control in app.segmented_control
        if control.label == "Appearance"
    )
    appearance.set_value("System").run()
    assert app.session_state["appearance"] == "System"
    assert StudentStore().get_user_preferences().get("appearance") == "System"
    assert not app.exception


def test_suggested_questions_are_view_only_and_do_not_change_the_composer():
    from backend.student_journey import stage_guidance_questions

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    starting_stage = app.session_state["learning_journey"]["current_stage"]
    questions = stage_guidance_questions(starting_stage)
    starting_messages = len(app.chat_message)
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)

    assert all(question in rendered for question in questions)
    assert not any(button.label in questions for button in app.button)
    assert not app.chat_input[0].value
    assert len(app.chat_message) == starting_messages
    assert app.session_state["learning_journey"]["current_stage"] == starting_stage
    assert not app.exception


def test_collapsed_sources_expander_survives_refresh():
    from backend.student_store import StudentStore
    from ui.sources import _sources_expander_widget_key

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    key = _sources_expander_widget_key("Lecture Notes")
    app.session_state[key] = False
    app.run()
    prefs = StudentStore().get_user_preferences().get("sources_expander_state") or {}
    assert prefs.get("Lecture Notes") is False

    # Browser refresh drops Streamlit session; preferences should restore collapsed.
    del app.session_state[key]
    app.run()
    assert app.session_state[key] is False
    assert not app.exception


def test_refresh_restores_last_open_notebook():
    from backend.models import LOCKED_CHAT_MODEL_ID
    from backend.student_store import StudentStore
    from backend.student_support import DEFAULT_SUPPORT_MODE

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    local_store = StudentStore()
    first_id = app.session_state["thread_id"]
    assert local_store.get_user_preferences().get("active_thread_id") == first_id

    other_id = local_store.create_thread(
        name="Persisted research notebook",
        model_id=LOCKED_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
    )
    local_store.update_user_preferences({"active_thread_id": other_id})

    # Browser refresh clears Streamlit session; preferences should reopen the
    # notebook that was active before the reload.
    app.session_state["thread_id"] = None
    app.run()
    assert app.session_state["thread_id"] == other_id
    assert local_store.get_user_preferences().get("active_thread_id") == other_id
    assert not app.exception


def test_current_notebook_title_is_directly_editable_and_syncs_with_history():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "Notebooks").click().run()
    next(button for button in app.button if button.label == "New notebook").click().run()
    current = StudentStore().get_thread(app.session_state["thread_id"])
    assert current
    title = next(
        text_input for text_input in app.text_input if text_input.label == "Notebook title"
    )
    assert title.value == current["name"]
    # Enter-only form: value changes alone must not persist until Apply/Enter.
    title.set_value("Should Not Persist").run()
    assert StudentStore().get_thread(app.session_state["thread_id"])["name"] == current["name"]
    title = next(
        text_input for text_input in app.text_input if text_input.label == "Notebook title"
    )
    title.set_value("Road Safety Research")
    next(button for button in app.button if button.label == "Apply").click().run()
    assert StudentStore().get_thread(app.session_state["thread_id"])["name"] == (
        "Road Safety Research"
    )
    next(button for button in app.button if button.label == "Notebooks").click().run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Road Safety Research" in rendered
    assert not app.exception


def test_rename_and_icon_controls_expose_accessible_instructions():
    """Static a11y contracts for Enter-only rename and icon-only controls."""
    from ui.theme import _template_stylesheet

    rename_source = Path("ui/rename.py").read_text(encoding="utf-8")
    sources = Path("ui/sources.py").read_text(encoding="utf-8")
    profile = Path("ui/profile.py").read_text(encoding="utf-8")
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    css = _template_stylesheet()

    assert '_ENTER_HINT = "Press Enter to apply"' in rename_source
    assert '"help": _ENTER_HINT' not in rename_source
    assert 'help="Source actions"' in sources
    assert "with st.popover(initial)" in profile
    assert 'help="Settings"' not in profile
    assert 'help="Collapse Thinking Path"' in workspace
    assert 'help="Collapse Sources"' in workspace
    assert 'help=f"Expand {label}"' in workspace
    assert (
        '[class*="st-key-source_card_"] [data-testid="stPopover"] button:focus-visible'
        in css
    )
    assert 'content:"Press Enter to apply"' in css
    assert (
        '.st-key-current_notebook_identity [data-testid="stFormSubmitButton"]' in css
    )
    assert "position:relative !important" in css
    assert "calc(100dvh - 9.2rem)" in css
    assert "ResizeObserver" in Path("ui/layout/sources_scroll.py").read_text(
        encoding="utf-8"
    )


def test_notebook_history_card_highlights_active_notebook_without_folders():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "Notebooks").click().run()
    next(button for button in app.button if button.label == "New notebook").click().run()
    local_store = StudentStore()
    thread_id = app.session_state["thread_id"]
    local_store.update_thread(thread_id, name="Active research notebook")

    app.run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    title = next(
        text_input for text_input in app.text_input if text_input.label == "Notebook title"
    )
    assert title.value == local_store.get_thread(thread_id)["name"]

    next(button for button in app.button if button.label == "Notebooks").click().run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "notebook-current-badge" in rendered
    assert "Active research notebook" in rendered
    assert not app.exception


def test_notebook_history_confirmed_delete_removes_the_selected_notebook():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "Notebooks").click().run()
    next(button for button in app.button if button.label == "New notebook").click().run()
    deleted_thread_id = app.session_state["thread_id"]

    app.session_state["pending_notebook_actions"] = deleted_thread_id
    app.run()
    confirmation = next(
        checkbox
        for checkbox in app.checkbox
        if checkbox.key == f"confirm-delete-{deleted_thread_id}"
    )
    confirmation.set_value(True).run()
    delete_button = next(
        button for button in app.button if button.label == "Delete permanently"
    )
    assert not delete_button.disabled
    delete_button.click().run()

    assert StudentStore().get_thread(deleted_thread_id) is None
    assert app.session_state["thread_id"] != deleted_thread_id
    assert app.session_state["pending_notebook_actions"] is None
    # Closing/deleting from actions returns to the notebook library.
    assert any(button.label == "New notebook" for button in app.button)
    assert not app.exception


def test_legacy_chat_turn_does_not_move_the_learning_stage_without_confirmation():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "Notebooks").click().run()
    next(button for button in app.button if button.label == "New notebook").click().run()
    app.chat_input[0].set_value(
        "My focus is to evaluate whether the study evidence supports the main claim."
    ).run()

    assert not app.exception
    assert app.session_state["learning_journey"]["current_stage"] == "focus"
    assert app.session_state["learning_journey"]["completed_stages"] == []


def test_pending_edit_failure_keeps_chat_visible(monkeypatch):
    """A failed revise must not blank the discussion panel."""
    from ui import chat
    from backend.student_store import StudentStore

    def reject_revise(*_args, **_kwargs):
        raise RuntimeError("revise failed for AppTest")

    monkeypatch.setattr(chat.store, "revise_message", reject_revise)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    app.chat_input[0].set_value(
        "I want to study safer street crossings for older pedestrians."
    ).run()
    assert not app.exception

    thread_id = app.session_state["thread_id"]
    user_message = next(
        message
        for message in StudentStore().get_messages(thread_id)
        if message.get("role") == "user"
    )
    app.session_state["pending_edit"] = {
        "message_id": user_message["id"],
        "prompt": "I want to study safer crossings near schools.",
        "idempotency_key": "11111111-1111-1111-1111-111111111111",
    }
    app.run()

    assert not app.exception
    rendered_errors = "\n".join(error.value or "" for error in app.error)
    assert "Could not finish this edit" in rendered_errors or "Could not" in rendered_errors
    # Explicit retry: failed revise must not leave pending_edit (auto-resubmit).
    assert "pending_edit" not in app.session_state or app.session_state[
        "pending_edit"
    ] in (None, {})
    assert app.session_state["editing_message"] == user_message["id"]
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Conversation 01" not in rendered
    assert "conversation-revision-label" not in rendered
    assert "Welcome back. What are you working through today?" in rendered
    assert (
        app.session_state[f"edit-text-{user_message['id']}"]
        == "I want to study safer crossings near schools."
    )
    # Stable revise key remains for the next explicit Send.
    from ui.retry_keys import RETRY_KEYS_SESSION_KEY, _scope_sha256

    assert RETRY_KEYS_SESSION_KEY in app.session_state
    records = app.session_state[RETRY_KEYS_SESSION_KEY]
    scope = _scope_sha256(
        thread_id,
        f"revise:{user_message['id']}",
        "I want to study safer crossings near schools.",
    )
    assert isinstance(records, dict)
    assert records[scope]["key"] == "11111111-1111-1111-1111-111111111111"
    # Active history remains in the store; panel still shows coach welcome.
    roles = [message["role"] for message in StudentStore().get_messages(thread_id)]
    assert "assistant" in roles
    assert "user" in roles
