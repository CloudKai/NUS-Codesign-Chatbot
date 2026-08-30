import inspect
from pathlib import Path

from streamlit.testing.v1 import AppTest

import ui.chat as chat_module
import ui.sources as sources_module
import ui.studio as studio_module

from backend.settings import settings
from ui.components import facione_scores_table_html
from ui.profile import COACHING_STYLE_COPY, COACHING_STYLE_VALUES


def _coaching_style_radio(app: AppTest):
    """Return the profile Coaching style radio from a running AppTest."""
    return next(radio for radio in app.radio if radio.label == "Coaching style")


def _visible_profile_copy(app: AppTest) -> str:
    """Join markdown, captions, and radio captions so coaching-style copy can be asserted."""
    markdown = "\n".join(item.value or "" for item in app.markdown)
    captions = "\n".join(item.value or "" for item in app.caption)
    radio_captions = "\n".join(
        caption
        for radio in app.radio
        for caption in list(radio.proto.captions)
    )
    return f"{markdown}\n{captions}\n{radio_captions}"


def _implementation_source(module: object) -> str:
    """Read the module that owns behavior behind a compatibility alias."""
    return Path(inspect.getfile(module)).read_text(encoding="utf-8")


def _open_library(app: AppTest) -> AppTest:
    """Open the center Library through the same navigation control as users."""
    next(button for button in app.button if button.label == "Library").click().run()
    assert app.session_state["center_view"] == "library"
    assert not app.exception
    return app


def _return_to_chat_from_library(app: AppTest) -> AppTest:
    """Toggle the active Library navigation item back to Chat."""
    next(button for button in app.button if button.label == "Library").click().run()
    assert app.session_state["center_view"] == "chat"
    assert not app.exception
    return app


def test_facione_score_shows_numeric_value_before_icon():
    html = facione_scores_table_html({"analysis": 3, "evaluation": 1})
    analysis = html.index("Analysis")
    numeric = html.index(">3/4<", analysis)
    icon = html.index("sentiment_satisfied", analysis)
    assert numeric < icon
    assert ">1/4<" in html
    assert "Analysis: 3/4, Acceptable" in html


def test_student_coach_error_copy_is_category_safe():
    """Safety-blocked turns must not blame start.sh or claim the provider is down."""
    from ui.panels.chat import student_coach_error_message

    blocked = student_coach_error_message("safety_blocked")
    assert "safety check" in blocked.lower()
    assert "notebook was not updated" in blocked.lower()
    assert "start.sh" not in blocked
    assert "provider" not in blocked.lower()
    malformed = student_coach_error_message("structured_output_failure")
    assert "couldn't complete" in malformed.lower()
    assert "json" not in malformed.lower()
    assert "502" not in malformed
    assert "agentresult" not in malformed.lower()
    assert student_coach_error_message("malformed") == malformed
    unavailable = student_coach_error_message("unavailable")
    assert "temporarily unavailable" in unavailable.lower()
    assert "start.sh" not in unavailable
    chat_py = _implementation_source(chat_module)
    assert "Prefer `sh scripts/start.sh`" not in chat_py
    assert "check the local provider" not in chat_py


def test_composer_profile_is_opt_in_and_unavailable_in_production(monkeypatch):
    """Keep browser-only composer diagnostics out of production script output."""
    from ui.layout import composer_layout

    rendered: list[str] = []
    monkeypatch.setattr(
        composer_layout.components,
        "html",
        lambda script, **_kwargs: rendered.append(script),
    )
    monkeypatch.setenv("CO_DESIGN_COMPOSER_PROFILE", "true")
    monkeypatch.setattr(composer_layout.settings, "app_env", "development")
    composer_layout.sync_composer_layout(max_file_size_mb=10)
    assert "const PROFILE_ENABLED = true;" in rendered[-1]
    assert "__cdComposerProfile" in rendered[-1]
    assert "__cdComposerProfileSnapshot" in rendered[-1]
    assert "__cdComposerProfileReset" in rendered[-1]

    monkeypatch.setattr(composer_layout.settings, "app_env", "production")
    composer_layout.sync_composer_layout(max_file_size_mb=10)
    assert "const PROFILE_ENABLED = false;" in rendered[-1]


def test_composer_typing_path_stays_local_and_structural() -> None:
    """Keep ordinary typing out of the heavyweight composer layout path."""
    composer_layout = Path("ui/layout/composer_layout.py").read_text(
        encoding="utf-8"
    )
    resize_path = composer_layout.split(
        "function scheduleTextareaResize(textarea, refreshMetrics = false)", 1
    )[1].split("function observeTextareaWidth", 1)[0]
    assert "if (resizeFrame) return;" in resize_path
    assert "const composer = root();" not in resize_path
    assert "chatInput(composer)" not in resize_path
    assert "scheduleModelPlacement" not in resize_path
    assert "currentTextarea.isConnected" in resize_path

    width_observer = composer_layout.split("function observeTextareaWidth", 1)[1].split(
        "function capTextarea", 1
    )[0]
    assert "new win.ResizeObserver((entries)" in width_observer
    assert "scheduleApply" not in width_observer
    assert "scheduleTextareaResize(observedTextarea, true);" in width_observer

    input_handler = composer_layout.split("const onComposerDraft", 1)[1].split(
        'composer.addEventListener("input"', 1
    )[0]
    assert "scheduleTextareaResize(textarea);" in input_handler
    assert "scheduleApply" not in input_handler
    paste_handler = composer_layout.split('"paste",', 1)[1].split(
        "win.addEventListener", 1
    )[0]
    assert "onComposerDraft(event);" in paste_handler
    assert "scheduleApply" not in paste_handler
    assert "measurementMirror" in composer_layout
    assert "model_placement_calls" in composer_layout
    assert "textarea_resize_frames" in composer_layout
    assert "attachment_annotation_calls" in composer_layout
    assert "attachment_tooltip_bind_calls" in composer_layout
    assert "overlay_rewrite_calls" in composer_layout
    assert "native_tooltip_scan_calls" in composer_layout
    assert "watchNativeUploadTooltips" in composer_layout
    assert "cd-native-upload-tip" in composer_layout
    assert "uploadTipObserver" in composer_layout
    assert "hideNativeUploadTooltips();" in composer_layout.split(
        "function showAttachTooltip", 1
    )[1].split("function hideAttachTooltip", 1)[0]


def test_composer_observes_native_send_stop_state_and_cleans_stopped_turn() -> None:
    """Send-to-Stop must not depend on a viewport resize or a custom rerun."""
    composer_layout = Path("ui/layout/composer_layout.py").read_text(
        encoding="utf-8"
    )
    observer = composer_layout.split("const observer = new win.MutationObserver", 1)[
        1
    ].split("let overlayFrame", 1)[0]
    assert 'record.attributeName === "data-testid"' in observer
    assert 'current === "stChatInputSubmitButton"' in observer
    assert 'current === "stChatInputStopButton"' in observer
    assert 'record.attributeName === "disabled"' in observer
    assert "if (structural || controlStateChanged) scheduleApply();" in observer
    assert 'attributeFilter: ["data-testid", "disabled"]' in observer
    assert "attributeOldValue: true" in observer
    assert 'attributeFilter: ["style"' not in observer
    assert 'attributeFilter: ["value"' not in observer

    cleanup = composer_layout.split("function bindNativeStopCleanup", 1)[1].split(
        "function apply", 1
    )[0]
    assert 'stChatInputStopButton' in cleanup
    assert 'stChatInputSubmitButton' in cleanup
    assert "hideStoppedInflightUi();" in cleanup
    assert "clearStoppedInflightUi();" in cleanup
    assert "scheduleApply();" in cleanup
    assert 'input.addEventListener(' in cleanup
    assert '"click"' in cleanup
    assert "preventDefault" not in cleanup
    assert "stopPropagation" not in cleanup
    assert "function setBusyComposer" not in composer_layout
    assert "cdComposerBusy" not in composer_layout

    styles = Path("ui/assets/styles/30-chat.css").read_text(encoding="utf-8")
    assert ".st-key-chat_inflight.cd-turn-stopped" in styles
    assert "stStatusWidget" in styles
    assert "inflight_user_message_row" in styles
    assert "Collapse it to a single stop row" not in styles

    chat = _implementation_source(chat_module)
    composer_fragment = chat.split("def _render_composer_submit_fragment", 1)[1]
    assert "StopException" not in composer_fragment


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
    monkeypatch.setattr(chat.store, "upload_attachments", reject_upload)

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


def test_empty_assistant_rows_are_not_rendered():
    """Failed or skeleton assistant rows with no text stay off the chat log."""
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    starting = len(app.chat_message)
    store = StudentStore()
    store.add_message(app.session_state["thread_id"], "assistant", "")
    app.run()
    assert not app.exception
    assert len(app.chat_message) == starting


def test_streamlit_notebook_workspace_smoke():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert "AttributeError" not in "\n".join(
        str(exception.value) for exception in app.exception
    )
    assert len(app.chat_input) == 1
    composer = app.chat_input[0]
    assert composer.placeholder == "Ask a question or share your thinking"
    assert composer.proto.accept_file
    assert not composer.proto.accept_audio
    assert composer.proto.max_upload_size_mb == settings.max_file_size_mb
    composer_layout = Path("ui/layout/composer_layout.py").read_text(encoding="utf-8")
    assert "Max {size_mb} MB per file" in composer_layout
    assert "cd-attach-tooltip" in composer_layout
    sources_py = _implementation_source(sources_module)
    assert "data-tooltip=" in sources_py
    assert "Max {settings.max_file_size_mb} MB per file" in sources_py

    assert not any(
        (button.key or "").startswith("profile-language-") for button in app.button
    )
    assert any(control.label == "Appearance" for control in app.segmented_control)
    assert not any(radio.label == "Workspace panel" for radio in app.radio)
    assert any((button.key or "") == "mobile-nav-menu" for button in app.button)
    assert any((button.key or "") == "mobile-new-chat" for button in app.button)
    assert app.session_state["mobile_panel"] == "Chat"
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "cd-mobile-view" in rendered or 'data-panel="Chat"' in rendered
    assert "Guidance Level:" not in rendered
    assert any(control.label == "Coaching style" for control in app.radio)
    coaching_style = _coaching_style_radio(app)
    assert coaching_style.options == ["Guide", "Free"]
    assert coaching_style.value == "Guide"
    assert app.session_state["response_detail"] == "short"
    assert app.session_state["learning_journey"]["response_detail"] == "short"
    studio_section = next(
        radio for radio in app.radio if radio.label == "Thinking Path section"
    )
    assert studio_section.options == ["Progression", "Review"]
    app.session_state["studio_tab"] = "Review"
    app.run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Guidance Level:" not in rendered
    assert '<span class="pane-title">Sources</span>' not in rendered
    assert "Welcome to your critical-thinking coach" in rendered
    assert "What design challenge or problem are you working on today?" in rendered
    assert '<span class="pane-title">Thinking Path</span>' in rendered
    assert "CDE2300" in rendered
    assert 'aria-label="Critical-thinking journey"' not in rendered
    assert "Critical thinking (Facione)" in rendered
    assert "0/4" in rendered
    assert "Discussion summary" in rendered
    assert "What to strengthen" in rendered
    expander_labels = [expander.label for expander in app.expander]
    assert {label for label in expander_labels} >= {
        "Strengths",
        "Areas for improvement",
        "Working conclusion",
        "Problem identification",
        "Concept generation",
    }
    assert "Critical Thinking" not in expander_labels
    assert expander_labels.index("Working conclusion") < expander_labels.index(
        "Strengths"
    )
    assert expander_labels.index("Strengths") < expander_labels.index(
        "Areas for improvement"
    )
    app.session_state["studio_tab"] = "Progression"
    app.run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert 'aria-label="Critical-thinking journey"' in rendered
    assert 'class="journey-short-label">Problem identification</span>' in rendered
    assert 'class="journey-short-label">Concept generation</span>' in rendered
    assert 'class="journey-short-label">Design specification</span>' in rendered
    assert 'class="journey-short-label">Ethics &amp; Critical Thinking</span>' in rendered
    assert 'class="journey-short-label">Reflection</span>' in rendered
    assert 'class="journey-short-label">Problem</span>' not in rendered
    assert 'class="journey-short-label">Concepts</span>' not in rendered
    assert 'class="journey-short-label">Specification</span>' not in rendered
    assert 'class="journey-short-label">Ethics & CT</span>' not in rendered
    assert "Frame the design problem, who it affects, and why it matters." in rendered
    chat_rendered = rendered
    _open_library(app)
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert '<span class="pane-title">Sources</span>' in rendered
    assert f"Max {settings.max_file_size_mb} MB per file" in rendered
    assert "Welcome to your critical-thinking coach" not in rendered
    expander_labels = [expander.label for expander in app.expander]
    assert {"Lecture Notes · 0", "Readings · 0", "My Sources · 0"} <= set(
        expander_labels
    )
    sources_py = _implementation_source(sources_module)
    my_sources_at = sources_py.index('f"My Sources · {len(personal_sources)}"')
    lecture_at = sources_py.index('f"{group} · {len(group_all)}"')
    assert my_sources_at < lecture_at
    assert '_ensure_sources_expander_state(group, default=False' in sources_py
    assert '_ensure_sources_expander_state("My Sources", default=True' in sources_py
    assert "source_card_locked_" in sources_py
    assert "disabled=locked" not in sources_py
    assert 'key="sources_filters"' in sources_py
    assert "sources-sort-label" in sources_py
    assert "_render_source_sort_dropdown" in sources_py
    assert "personal_sources_all" in sources_py
    assert "Select all sources" in sources_py
    assert "Add your first source" in rendered
    assert "Loading course materials in the background…" in _implementation_source(
        sources_module
    )
    assert 'st.session_state["source_upload_error"] = str(exc)' not in sources_py
    assert "st.error(str(exc))" not in sources_py
    assert "st.error(str(exc))" not in _implementation_source(studio_module)
    assert "_STAGE_SELECT_ERROR" in _implementation_source(studio_module)
    assert "_TRANSITION_RESOLVE_ERROR" in _implementation_source(studio_module)
    assert 'click Send' in _implementation_source(chat_module)
    assert "st.session_state.pop(\"pending_edit\", None)" in _implementation_source(
        chat_module
    )
    assert "_SOURCE_UPLOAD_ERROR" in sources_py
    assert "_SOURCE_SYNC_ERROR" in sources_py
    assert "_SOURCE_RENAME_ERROR" in sources_py
    assert "_SOURCE_DOWNLOAD_ERROR" in sources_py
    assert "logger.exception" in sources_py
    assert "st.caption(_SOURCE_IMPORT_PARTIAL_ERROR)" in sources_py
    assert 'st.caption(\n                "Some lecture notes could not be imported:' not in sources_py
    # Library replaces Chat in the center while Thinking Path remains visible.
    assert rendered.index('<span class="pane-title">Sources</span>') < rendered.index(
        '<span class="pane-title">Thinking Path</span>'
    )
    assert 'class="message-meta coach-welcome"' in chat_rendered
    _return_to_chat_from_library(app)
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert ".st-key-chat_log" in rendered
    assert ".st-key-chat_inflight" in rendered
    assert ".st-key-chat_panel" in rendered
    assert "overflow-y:auto" in rendered
    assert "scroll-behavior:auto" in rendered
    assert "scrollbar-color:var(--cd-scrollbar) transparent" in rendered
    assert "max-height:calc(1em * 1.45 * 5)" in rendered
    assert "max-width:80ch" in rendered
    assert "max-width:min(100%, calc(80ch + 16px))" in rendered
    assert "max-height:none !important" in rendered
    assert "max-height:11rem" not in rendered
    assert "min-height:5.5rem" in rendered
    composer_layout = Path("ui/layout/composer_layout.py").read_text(
        encoding="utf-8"
    )
    assert "lineHeight * 5 + padY" in composer_layout
    assert 'setProperty("height", "auto"' in composer_layout
    assert 'addEventListener("input", onComposerDraft, true)' in composer_layout
    assert "scheduleTextareaResize(textarea);" in composer_layout
    assert "if (applyFrame) return;" in composer_layout
    assert "full_apply_calls" in composer_layout
    assert "textarea_resize_calls" in composer_layout
    assert 'attributeFilter: ["data-testid", "disabled"]' in composer_layout
    assert "characterData: true" not in composer_layout
    assert "watchNativeUploadTooltips" in composer_layout
    assert "uploadTipObserver.observe(doc.body, { childList: true, subtree: true })" in composer_layout
    assert "hideNativeUploadTooltips();" in composer_layout
    assert "CO_DESIGN_COMPOSER_PROFILE" in composer_layout
    assert "MAX_COLS" not in composer_layout
    assert "field-sizing:content" in rendered.replace(" ", "")
    assert "contain:layoutstyle" in rendered.replace(" ", "")
    edit_layout = Path("ui/layout/user_message_edit_layout.py").read_text(
        encoding="utf-8"
    )
    assert "USER_BUBBLE_MAX_ROWS = 8" in edit_layout
    assert "USER_MESSAGE_EDIT_HEIGHT_PX" in edit_layout
    assert "components.html" not in edit_layout
    assert "def sync_user_message_edit_layout()" in edit_layout
    assert "--cd-user-bubble-max-rows:8" in rendered
    assert "--cd-user-bubble-max-height" in rendered
    chat_py = _implementation_source(chat_module)
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
    assert 'appearance == "Dark"' in _implementation_source(chat_module)
    assert "#5B6B7C" in _implementation_source(chat_module)
    assert "rgba(255, 255, 255, 0.35)" in _implementation_source(chat_module)
    assert "#9AA8B5" in _implementation_source(chat_module)
    assert "rgba(15, 20, 25, 0.72)" not in _implementation_source(chat_module)
    assert "writing-mode:horizontal-tb" in rendered
    assert "grid-template-columns:minmax(0,1fr) auto" in rendered
    assert "stChatInputTextArea" in rendered
    assert "arrow_upward" in rendered
    assert "stChatInputStopButton" in rendered
    assert "content:\"stop\"" in rendered
    assert 'type="compact"' in _implementation_source(chat_module)
    assert "cd-composer-card" in Path("ui/layout/composer_layout.py").read_text(encoding="utf-8")
    assert (
        '[data-testid="stHeaderActionElements"] {\n'
        "        display:none !important;"
    ) in rendered
    assert "stChatInputMicButton" in rendered
    assert "coach-welcome-title" in rendered
    assert "st-key-notebook_topbar" in rendered  # retired selectors remain harmless
    assert "color:var(--cd-text) !important" in rendered
    assert "background:transparent !important" in rendered
    assert "place-items:center" in rendered
    assert (
        '[data-testid="stChatMessageAvatarCustom"] {\n'
        "        display:none !important;"
    ) in rendered
    assert "st-key-sidebar_profile" in rendered
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
    assert "--cd-bg:#F7F9FC" in rendered
    assert "--cd-panel:#F7F9FB" in rendered
    assert "--cd-text:#1F2933" in rendered
    assert "--cd-accent:#179E90" in rendered
    assert "cd-col-resize-handle" in rendered
    assert "cd-col-rail" in rendered
    assert ":has(.st-key-studio_rail)" in rendered
    assert any((button.key or "") == "collapse-studio" for button in app.button)
    assert "cd-roadmap" in rendered
    assert "IBM Plex Sans" in rendered
    assert "background:var(--cd-nav)" in rendered

    button_labels = {button.label for button in app.button}
    assert "New chat" in button_labels
    assert "Search chats" in button_labels
    assert "Library" in button_labels
    assert "Notebooks" not in button_labels
    assert '<span class="pane-title">Sources</span>' not in rendered

    assert any(input_widget.label == "Display name" for input_widget in app.text_input)
    assert any(control.label == "Appearance" for control in app.segmented_control)
    assert "cd-profile-language-label" not in rendered
    assert not any(
        (button.key or "").startswith("profile-language-") for button in app.button
    )
    assert "cd-profile-menu" in rendered
    assert "cd-profile-help" not in rendered
    assert "Will input myself later" not in rendered
    assert any((button.key or "") == "profile-logout-button" for button in app.button)
    assert "cd-profile-logout-link" not in rendered
    assert "stTooltipHoverTarget" in rendered
    assert not any(
        (button.key or "").startswith("composer-model-") for button in app.button
    )
    assert not any(
        (button.key or "").startswith("composer-effort-") for button in app.button
    )
    assert "_render_composer_model_picker" not in _implementation_source(chat_module)
    assert "st-key-chat_composer" in rendered
    assert len(app.chat_message) == 1
    assert app.chat_message[0].name == "assistant"


def test_composer_has_no_model_picker_and_keeps_default_model():
    """Students cannot choose a model; the locked default stays in session."""
    from backend.models import DEFAULT_CHAT_MODEL_ID, DEFAULT_REASONING_EFFORT

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert app.session_state["selected_model"] == DEFAULT_CHAT_MODEL_ID
    assert app.session_state["reasoning_effort"] == DEFAULT_REASONING_EFFORT
    assert not any(
        (button.key or "").startswith("composer-model-") for button in app.button
    )
    assert not any(
        (button.key or "").startswith("composer-effort-") for button in app.button
    )
    assert "_render_composer_model_picker" not in _implementation_source(chat_module)
    assert "sync_studio_scroll" in Path("ui/workspace.py").read_text(encoding="utf-8")
    studio_py = _implementation_source(studio_module)
    assert "stage.short_label" not in studio_py
    assert 'escape(stage.label)' in studio_py
    assert 'key="studio_scroll", height="stretch"' in studio_py


def test_add_pasted_source_then_chat_with_citation():
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    _open_library(app)
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

    # Start a clean AppTest tree when leaving Library; Streamlit's test harness
    # otherwise retains removed source rename-form widget ids.
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.chat_input[0].set_value("What evidence does my source provide?").run()
    assert not app.exception
    thread_id = app.session_state["thread_id"]
    persisted = [
        message
        for message in StudentStore().get_messages(thread_id)
        if str(message.get("content") or "").strip()
    ]
    assert [message.get("role") for message in persisted] == [
        "assistant",
        "user",
        "assistant",
    ]
    app.run()
    assert not app.exception
    persisted_after = [
        message
        for message in StudentStore().get_messages(thread_id)
        if str(message.get("content") or "").strip()
    ]
    assert [message.get("role") for message in persisted_after] == [
        "assistant",
        "user",
        "assistant",
    ]
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
    _open_library(app)

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

    _open_library(app)
    next(button for button in app.button if button.label == "Preview test.pdf").click().run()

    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Preview test.pdf" in rendered


def test_learning_studio_and_notebook_history_controls():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Thinking Path" in rendered
    app.session_state["studio_tab"] = "Review"
    app.run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Critical thinking (Facione)" in rendered
    assert "0/4" in rendered
    assert "Discussion summary" in rendered
    assert "Critical Thinking" not in {
        expander.label for expander in app.expander
    }
    next(button for button in app.button if button.label == "New chat").click().run()
    assert not app.exception
    assert any(button.label == "Search chats" for button in app.button)
    assert any(button.label == "Library" for button in app.button)
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Recents" in rendered
    assert "cd-nav-section-label" in rendered
    assert 'class="notebook-card-meta"' not in rendered
    assert "Stage Progression" in rendered


def test_notebook_activity_helpers_format_relative_time_and_counts():
    from datetime import datetime, timezone

    from ui.notebooks import _relative_activity

    now = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)
    assert _relative_activity("2026-08-12T01:00:00Z", now=now) == "today"
    assert _relative_activity("2026-08-11T01:00:00Z", now=now) == "yesterday"
    assert _relative_activity("2026-08-09T01:00:00Z", now=now) == "3 days ago"
    assert _relative_activity("2026-07-01T01:00:00Z", now=now) == "01 Jul 2026"
    assert _relative_activity("", now=now) == "Unknown"


def test_coaching_style_keeps_existing_short_long_mapping():
    """Guide/Free remain a display layer over persisted short/long values."""
    from ui.profile import _coaching_style_caption, _persist_coaching_style, _select_coaching_style

    assert COACHING_STYLE_VALUES["Guide"] == "short"
    assert COACHING_STYLE_VALUES["Free"] == "long"
    assert "quick" not in COACHING_STYLE_VALUES.values()
    assert "strict" not in COACHING_STYLE_VALUES.values()
    assert _coaching_style_caption("short") == COACHING_STYLE_COPY["short"]
    assert _coaching_style_caption("long") == COACHING_STYLE_COPY["long"]
    assert "Keep me moving" not in _coaching_style_caption("short")
    assert "Check the idea I have" not in _coaching_style_caption("long")
    persist_source = inspect.getsource(_persist_coaching_style)
    select_source = inspect.getsource(_select_coaching_style)
    assert "COACHING_STYLE_VALUES" in persist_source
    assert "save_journey(journey)" in select_source
    coaching_block = Path("ui/profile.py").read_text(encoding="utf-8").split(
        "def _select_coaching_style", 1
    )[1].split("def render_profile_menu", 1)[0]
    assert "local_api_client" not in coaching_block
    assert "store.update_thread" not in coaching_block


def test_persisted_long_coaching_style_renders_strict_selected():
    """Reloading a notebook stored as long must select Free, not the Guide default."""
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = app.session_state["thread_id"]
    assert _coaching_style_radio(app).value == "Guide"
    StudentStore().update_thread(thread_id, metadata={"response_detail": "long"})

    restored = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert restored.session_state["thread_id"] == thread_id
    assert restored.session_state["response_detail"] == "long"
    assert restored.session_state["learning_journey"]["response_detail"] == "long"
    assert restored.session_state["setting_coaching_style"] == "Free"
    assert _coaching_style_radio(restored).value == "Free"
    assert any(item.label == "Display name" for item in restored.text_input)
    assert any(control.label == "Appearance" for control in restored.segmented_control)
    assert not restored.exception


def test_theme_coaching_style_and_journey_has_no_manual_progression_control():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    # Preferences live in the profile settings popover (content exposed to AppTest).

    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "cd-profile-language-label" not in rendered
    assert "The coach responds in this language" not in rendered
    assert not any(
        (button.key or "").startswith("profile-language-") for button in app.button
    )

    coaching_style = _coaching_style_radio(app)
    assert coaching_style.options == ["Guide", "Free"]
    assert coaching_style.value == "Guide"
    visible_copy = _visible_profile_copy(app)
    assert COACHING_STYLE_COPY["short"] in visible_copy
    assert COACHING_STYLE_COPY["long"] in visible_copy
    assert "Keep me moving" not in visible_copy
    assert "Check the idea I have" not in visible_copy
    coaching_style.set_value("Free").run()
    assert app.session_state["response_detail"] == "long"
    assert app.session_state["learning_journey"]["response_detail"] == "long"
    assert StudentStore().get_thread(app.session_state["thread_id"])["metadata"][
        "response_detail"
    ] == "long"
    coaching_style = _coaching_style_radio(app)
    assert coaching_style.value == "Free"
    coaching_style.set_value("Guide").run()
    assert app.session_state["response_detail"] == "short"
    assert app.session_state["learning_journey"]["response_detail"] == "short"
    assert StudentStore().get_thread(app.session_state["thread_id"])["metadata"][
        "response_detail"
    ] == "short"

    # A later notebook must start Guide even if this session had Free selected.
    next(button for button in app.button if button.label == "New chat").click().run()
    coaching_style = _coaching_style_radio(app)
    assert coaching_style.value == "Guide"
    assert app.session_state["response_detail"] == "short"
    assert app.session_state["learning_journey"]["response_detail"] == "short"
    assert app.session_state["setting_coaching_style"] == "Guide"
    created = StudentStore().get_thread(app.session_state["thread_id"])
    assert created is not None
    assert created["metadata"]["response_detail"] == "short"

    # Popover content remains available for further preference changes.
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

    assert app.session_state["learning_journey"]["current_stage"] == "problem_identification"
    assert not any(button.label == "Work on this stage" for button in app.button)
    assert not app.exception


def test_journey_fresh_problem_stage_keeps_next_stage_locked(monkeypatch):
    from backend.settings import settings

    monkeypatch.setattr(settings, "student_stage_selection", True)
    monkeypatch.setattr(settings, "auto_advance_stages", False)

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not any(button.label == "Work on this stage" for button in app.button)
    compact_buttons = [button for button in app.button if button.label == "Work on.."]
    assert compact_buttons == []
    captions = "\n".join(caption.value or "" for caption in app.caption)
    assert "Choose a stage to work on." not in captions
    assert not app.exception


def test_journey_linear_accordion_and_ctas_follow_unlocked_frontier(monkeypatch):
    """Journey previews are scalar and selection CTAs follow server access."""
    from backend.settings import settings

    monkeypatch.setattr(settings, "student_stage_selection", True)
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()

    assert app.session_state["learning_journey"]["current_stage"] == (
        "problem_identification"
    )
    assert not any(button.label == "Work on this stage" for button in app.button)
    assert not any(button.key == "journey-select-deep_analysis" for button in app.button)

    app.session_state["journey_preview_stage"] = "reflection"
    app.run()
    assert app.session_state["journey_preview_stage"] == "reflection"
    assert app.session_state["learning_journey"]["current_stage"] == (
        "problem_identification"
    )
    assert any(
        "Available after Ethics & Critical Thinking." in (caption.value or "")
        for caption in app.caption
    )
    assert not any(button.key == "journey-select-reflection" for button in app.button)

    app.session_state["journey_preview_stage"] = "deep_analysis"
    app.run()
    assert app.session_state["journey_preview_stage"] == "deep_analysis"
    assert app.session_state["learning_journey"]["current_stage"] == (
        "problem_identification"
    )

    from backend.student_store import StudentStore

    store = StudentStore()
    thread = store.get_thread(app.session_state["thread_id"]) or {}
    metadata = dict(thread.get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = ["problem_identification"]
    metadata["learning_journey"] = journey
    store.update_thread(app.session_state["thread_id"], metadata=metadata)
    app.session_state["learning_journey"]["completed_stages"] = [
        "problem_identification"
    ]
    app.run()
    assert any(button.label == "Work on this stage" for button in app.button)
    assert not any(button.key == "journey-select-problem_identification" for button in app.button)

    app.button(key="journey-select-concept_generation").click().run()
    assert app.session_state["learning_journey"]["current_stage"] == (
        "concept_generation"
    )
    assert app.session_state["mobile_panel"] == "Chat"
    assert "chat_follow_bottom" not in app.session_state
    assert app.session_state["stage_move_notice"] is None
    messages = store.get_messages(app.session_state["thread_id"])
    briefing = [
        message
        for message in messages
        if message.get("role") == "assistant"
        and str(message.get("content") or "").startswith(
            "Moved to Stage: Concept generation."
        )
    ]
    assert len(briefing) == 1
    assert "What to work on next:" in briefing[0]["content"]
    assert not any(
        str(message.get("content") or "").lower().startswith("move me to")
        for message in messages
        if message.get("role") == "user"
    )
    labels = [button.label for button in app.button]
    assert "Work on this stage" not in labels
    assert "Revisit" in labels
    assert "Work on.." not in labels
    assert "Suggested questions" in Path(
        "ui/panels/studio.py"
    ).read_text(encoding="utf-8")
    assert not any(button.key == "journey-select-concept_generation" for button in app.button)
    assert app.session_state["journey_preview_stage"] is None
    assert not app.exception


def test_journey_ready_next_stage_is_not_focus_highlighted(monkeypatch):
    """Ready next stage keeps Work on this stage but is not the current card."""
    from backend.settings import settings
    from backend.student_store import StudentStore

    monkeypatch.setattr(settings, "student_stage_selection", True)
    monkeypatch.setattr(settings, "auto_advance_stages", False)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    store = StudentStore()
    thread = store.get_thread(app.session_state["thread_id"]) or {}
    metadata = dict(thread.get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["current_stage"] = "concept_generation"
    journey["completed_stages"] = [
        "problem_identification",
        "concept_generation",
    ]
    metadata["learning_journey"] = journey
    store.update_thread(app.session_state["thread_id"], metadata=metadata)
    app.session_state["learning_journey"]["current_stage"] = "concept_generation"
    app.session_state["learning_journey"]["completed_stages"] = [
        "problem_identification",
        "concept_generation",
    ]
    app.run()
    assert not app.exception
    assert app.session_state["learning_journey"]["current_stage"] == (
        "concept_generation"
    )
    assert any(button.label == "Work on this stage" for button in app.button)
    assert any(
        button.key == "journey-select-design_specification" for button in app.button
    )
    blob = "\n".join(str(markdown.value or "") for markdown in app.markdown)
    assert "journey-state completed focus" in blob
    assert "journey-state current focus" not in blob
    assert "journey-state current" in blob


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
    _open_library(app)
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


def test_current_notebook_title_is_editable_from_recent_chat_menu():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "New chat").click().run()
    current = StudentStore().get_thread(app.session_state["thread_id"])
    assert current
    thread_id = str(app.session_state["thread_id"])
    title = next(
        text_input
        for text_input in app.text_input
        if text_input.label == "Rename"
        and "mobile-chat" in (text_input.key or "")
    )
    assert title.value == current["name"]
    # Enter-only form: value changes alone must not persist until Apply/Enter.
    title.set_value("Should Not Persist").run()
    assert StudentStore().get_thread(app.session_state["thread_id"])["name"] == current["name"]
    title = next(
        text_input
        for text_input in app.text_input
        if text_input.label == "Rename"
        and "mobile-chat" in (text_input.key or "")
    )
    title.set_value("Road Safety Research")
    next(
        button
        for button in app.button
        if button.label == "Apply"
        and "mobile-chat" in (button.key or "")
    ).click().run()
    assert StudentStore().get_thread(app.session_state["thread_id"])["name"] == (
        "Road Safety Research"
    )
    assert "Road Safety Research" in {
        button.label for button in app.button
    }
    assert not app.exception


def test_rename_and_icon_controls_expose_accessible_instructions():
    """Static a11y contracts for Enter-only rename and icon-only controls."""
    from ui.theme import _template_stylesheet

    rename_source = Path("ui/rename.py").read_text(encoding="utf-8")
    sources = _implementation_source(sources_module)
    profile = Path("ui/profile.py").read_text(encoding="utf-8")
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    css = _template_stylesheet()

    assert '"help": _ENTER_HINT' not in rename_source
    assert '_ENTER_HINT' not in rename_source
    assert 'help="Source actions"' in sources
    assert "data-tooltip=" in sources
    assert "Max {settings.max_file_size_mb} MB per file" in sources
    assert ".cd-sources-add-face::after" in css
    assert 'content:attr(data-tooltip)' in css
    assert ":material/settings:" in profile
    assert 'icon=":material/account_circle:"' not in profile
    assert 'help="Settings"' in profile
    assert "cd-sidebar-profile-avatar" in profile
    assert "cd-sidebar-profile-name" in profile
    assert "profile_initial" in profile
    assert 'help="Collapse Thinking Path"' in workspace
    assert 'help=f"Expand Analyse / {label}"' in workspace
    assert (
        '[class*="st-key-source_card_"] [data-testid="stPopover"] button:focus-visible'
        in css
    )
    # Rename fields hide Streamlit's "Press Enter to submit form" chrome.
    assert 'st-key-nav_rename_"] [data-testid="InputInstructions"]' in css
    assert 'st-key-mobile_rename_"] [data-testid="InputInstructions"]' in css
    assert 'st-key-source_rename_"] [data-testid="InputInstructions"]' in css
    assert 'content:"Press Enter to apply"' not in css
    assert "position:relative !important" in css
    assert "height:100vh" in css
    assert "ResizeObserver" in Path("ui/layout/sources_scroll.py").read_text(
        encoding="utf-8"
    )
    studio_scroll = Path("ui/layout/studio_scroll.py").read_text(encoding="utf-8")
    assert "ResizeObserver" in studio_scroll
    assert ".st-key-studio_scroll" in studio_scroll
    assert "[role='tabpanel']" in studio_scroll
    assert "sync_studio_scroll" in workspace
    assert ".st-key-studio_scroll [role=\"tabpanel\"]" in css
    assert "overflow:visible !important;" in css


def test_notebook_history_card_highlights_active_notebook_without_folders():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "New chat").click().run()
    local_store = StudentStore()
    thread_id = app.session_state["thread_id"]
    local_store.update_thread(thread_id, name="Active research notebook")

    app.run()
    assert "Active research notebook" in {
        button.label for button in app.button
    }
    assert not app.exception


def test_notebook_history_confirmed_delete_removes_the_selected_notebook():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "New chat").click().run()
    deleted_thread_id = app.session_state["thread_id"]

    app.session_state["pending_delete_chat_id"] = deleted_thread_id
    app.run()
    delete_button = next(
        button for button in app.button if button.label == "Delete" and "nav-delete-confirm" in (button.key or "")
    )
    assert not delete_button.disabled
    delete_button.click().run()

    assert StudentStore().get_thread(deleted_thread_id) is None
    assert app.session_state["thread_id"] != deleted_thread_id
    assert "pending_delete_chat_id" not in app.session_state or not app.session_state[
        "pending_delete_chat_id"
    ]
    assert any(button.label == "New chat" for button in app.button)
    assert not app.exception


def test_dismissed_delete_dialog_does_not_remount_and_new_chat_clears_pending():
    """Esc/dismiss marker and New chat must not leave a sticky Delete chat dialog."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = app.session_state["thread_id"]

    app.session_state["pending_delete_chat_id"] = thread_id
    app.session_state["_delete_chat_dialog_dismissed_id"] = thread_id
    app.run()
    assert not any(
        (button.key or "").startswith("nav-delete-confirm")
        or (button.key or "") == "nav-delete-cancel"
        for button in app.button
    )
    assert "pending_delete_chat_id" not in app.session_state or not app.session_state[
        "pending_delete_chat_id"
    ]
    assert not app.exception

    app.session_state["pending_delete_chat_id"] = thread_id
    if "_delete_chat_dialog_dismissed_id" in app.session_state:
        del app.session_state["_delete_chat_dialog_dismissed_id"]
    next(button for button in app.button if button.label == "New chat").click().run()
    assert "pending_delete_chat_id" not in app.session_state or not app.session_state[
        "pending_delete_chat_id"
    ]
    assert not any(
        (button.key or "") == "nav-delete-confirm" for button in app.button
    )
    assert not app.exception


def test_logout_requires_confirmation_dialog():
    """Settings Logout opens a Cancel/Logout dialog instead of signing out immediately."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    logout = next(
        button
        for button in app.button
        if (button.key or "") == "profile-logout-button"
    )
    logout.click().run()
    assert app.session_state["pending_logout_confirm"] is True
    assert "_menu_popover_epoch_profile-settings" in app.session_state
    assert int(app.session_state["_menu_popover_epoch_profile-settings"]) >= 1
    assert any((button.key or "") == "profile-logout-cancel" for button in app.button)
    assert any((button.key or "") == "profile-logout-confirm" for button in app.button)

    cancel = next(
        button
        for button in app.button
        if (button.key or "") == "profile-logout-cancel"
    )
    cancel.click().run()
    assert (
        "pending_logout_confirm" not in app.session_state
        or not app.session_state["pending_logout_confirm"]
    )
    assert not any(
        (button.key or "") == "profile-logout-confirm" for button in app.button
    )
    assert not app.exception


def test_notebook_actions_offers_transcript_download():
    """Chat menus expose on-click transcript prepare, not paint-time prefetch."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    prepare = next(
        button
        for button in app.button
        if (button.key or "").startswith(
            ("nav-chat-prepare-transcript-", "mobile-chat-prepare-transcript-")
        )
    )
    assert "transcript" in str(prepare.help).lower()
    assert not any(
        (control.key or "").startswith(
            ("nav-chat-save-transcript-", "mobile-chat-save-transcript-")
        )
        for control in app.download_button
    )
    assert not app.exception


def test_transcript_download_is_prepared_on_click_only() -> None:
    """Recents must not call download_transcript while painting closed menus."""
    nav = Path("ui/panels/nav.py").read_text(encoding="utf-8")
    assert "def prepare_transcript_export(" in nav
    assert "def render_transcript_download_control(" in nav
    assert "on_click=prepare_transcript_export" in nav
    menu = nav.split("def render_chat_actions_menu", 1)[1].split(
        "def _render_recent_menu", 1
    )[0]
    assert "store.download_transcript(" not in menu
    assert "render_transcript_download_control(" in menu
    notebooks = Path("ui/notebooks.py").read_text(encoding="utf-8")
    assert "render_transcript_download_control(" in notebooks
    assert "store.download_transcript(" not in notebooks


def test_legacy_chat_turn_does_not_move_the_learning_stage_without_confirmation():
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "New chat").click().run()
    app.chat_input[0].set_value(
        "My focus is to evaluate whether the study evidence supports the main claim."
    ).run()

    assert not app.exception
    assert app.session_state["learning_journey"]["current_stage"] == "problem_identification"
    assert app.session_state["learning_journey"]["completed_stages"] == []


def test_latest_message_edit_stays_in_the_chat_fragment():
    """Editing the active user turn avoids an app-wide remount."""
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
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
    edit = next(
        button
        for button in app.button
        if button.key == f"edit-{user_message['id']}"
    )
    before_edit_runs = app.session_state["_app_runs"]
    edit.click().run()

    assert not app.exception
    # AppTest.run() always drives a full script run (it cannot issue a
    # fragment-scoped websocket rerun); the source contract below proves the
    # callback itself does not request an additional app rerun.
    assert app.session_state["_app_runs"] == before_edit_runs + 1
    assert app.session_state["editing_message"] == user_message["id"]
    assert "edit_confirm_message_id" not in app.session_state or app.session_state[
        "edit_confirm_message_id"
    ] in (None, "")
    assert any(
        text_area.key == f"edit-text-{user_message['id']}"
        for text_area in app.text_area
    )


def test_earlier_message_edit_keeps_the_app_scoped_confirmation_dialog():
    """Editing an earlier turn still opens the existing confirmation dialog."""
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.chat_input[0].set_value("First framing question.").run()
    app.chat_input[0].set_value("Second framing question.").run()
    assert not app.exception

    messages = [
        message
        for message in StudentStore().get_messages(app.session_state["thread_id"])
        if message.get("role") == "user"
    ]
    assert len(messages) >= 2
    earlier_id = messages[0]["id"]
    next(
        button
        for button in app.button
        if button.key == f"edit-{earlier_id}"
    ).click().run()

    assert not app.exception
    assert app.session_state["edit_confirm_message_id"] == earlier_id
    assert any(button.label == "Edit & continue" for button in app.button)

    cancel_runs = app.session_state["_app_runs"]
    next(button for button in app.button if button.label == "Cancel").click().run()
    assert not app.exception
    assert app.session_state["_app_runs"] > cancel_runs
    assert app.session_state["edit_confirm_message_id"] in (None, "")

    next(
        button
        for button in app.button
        if button.key == f"edit-{earlier_id}"
    ).click().run()
    assert not app.exception
    continue_button = next(
        button for button in app.button if button.label == "Edit & continue"
    )
    continue_runs = app.session_state["_app_runs"]
    continue_button.click().run()
    assert not app.exception
    assert app.session_state["_app_runs"] > continue_runs
    assert app.session_state["editing_message"] == earlier_id


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
    assert "Welcome to your critical-thinking coach" in rendered
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


def test_edit_failure_message_distinguishes_busy_conflicts():
    """429 / notebook-busy revise failures get a specific wait-and-retry hint."""
    from ui.panels.chat import (
        _EDIT_BUSY_RETRY_MESSAGE,
        _EDIT_GENERIC_FAILURE_MESSAGE,
        _edit_failure_message,
        _exception_is_coach_busy,
    )

    class _Resp:
        status_code = 429

    class _HttpError(Exception):
        def __init__(self) -> None:
            super().__init__("429 Too Many Requests")
            self.response = _Resp()

    busy = _HttpError()
    assert _exception_is_coach_busy(busy)
    assert _edit_failure_message(busy) == _EDIT_BUSY_RETRY_MESSAGE
    assert _edit_failure_message(RuntimeError("boom")) == _EDIT_GENERIC_FAILURE_MESSAGE


def test_pending_edit_retries_when_coach_is_temporarily_busy(monkeypatch):
    """Revise retries briefly when the notebook lease is held by a finishing turn."""
    from ui import chat
    from backend.domain import CoachTurn, EducationalAssessment
    from backend.student_store import StudentStore

    calls = {"n": 0}

    def flaky_revise(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:

            class _Resp:
                status_code = 429

            error = Exception("429 Too Many Requests")
            error.response = _Resp()  # type: ignore[attr-defined]
            raise error
        return CoachTurn(
            response_text="Revised coach reply",
            assessment=EducationalAssessment(current_stage="problem_identification"),
        )

    monkeypatch.setattr(chat.store, "revise_message", flaky_revise)
    # Do not patch stdlib time.sleep — ui.panels.chat.time is the stdlib module.
    monkeypatch.setattr(chat, "_REVISE_BUSY_SLEEP_SECONDS", 0)

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
        "idempotency_key": "22222222-2222-2222-2222-222222222222",
    }
    app.run()

    assert not app.exception
    assert calls["n"] == 3
    assert "pending_edit" not in app.session_state or app.session_state[
        "pending_edit"
    ] in (None, {})
    editing = (
        app.session_state["editing_message"]
        if "editing_message" in app.session_state
        else None
    )
    assert not editing
    assert not any(
        "Could not finish this edit" in (error.value or "")
        or "still finishing another reply" in (error.value or "")
        for error in app.error
    )
