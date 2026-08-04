from pathlib import Path

from streamlit.testing.v1 import AppTest

from backend.settings import settings


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

    assert not any(selectbox.label == "Guidance Level:" for selectbox in app.selectbox)
    assert not any(selectbox.label == "Model" for selectbox in app.selectbox)
    # Profile preferences live in the settings popover (exposed to AppTest).
    assert any(selectbox.label == "Language" for selectbox in app.selectbox)
    assert any(control.label == "Appearance" for control in app.segmented_control)
    assert not any(selectbox.label == "Current stage" for selectbox in app.selectbox)
    assert not any(selectbox.label == "Learning mode" for selectbox in app.selectbox)
    workspace_panel = next(
        radio for radio in app.radio if radio.label == "Workspace panel"
    )
    assert workspace_panel.options == ["Sources", "Chat", "Journey"]
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Guidance Level:" in rendered
    assert any(button.label == "Quick" for button in app.button)
    assert {tab.label for tab in app.tabs} >= {"Journey", "Review"}
    assert not any(
        button.label == "Use the suggested next question" for button in app.button
    )

    assert '<span class="pane-title">Sources</span>' in rendered
    assert '<div class="chat-heading">' not in rendered
    assert '<div class="chat-context-line">' not in rendered
    assert "Using OpenAI knowledge until you select a source" not in rendered
    assert "Hi, I’m your critical-thinking coach." in rendered
    assert "Start by describing the question, problem, or claim" in rendered
    notebook_title = next(
        text_input for text_input in app.text_input if text_input.label == "Notebook title"
    )
    assert notebook_title.value == "Untitled notebook"
    assert '<span class="pane-title">Thinking Path</span>' in rendered
    assert "Critical Thinking Companion" in rendered
    assert 'aria-label="Critical-thinking journey"' in rendered
    assert "Deeper explanations, examples, and follow-up prompts." not in rendered
    assert "Focus" in rendered
    assert "Conclusion" in rendered
    assert "Next question" not in rendered
    assert "Discussion summary" in rendered
    assert "What to strengthen" in rendered
    assert "What you have contributed" not in rendered
    assert "% complete" not in rendered
    assert "Clarify the question, problem, or claim" in rendered
    assert "Add your first source" in rendered
    assert "Drop files into lecture_notes/" not in rendered
    assert "Loading course materials…" in Path("ui/sources.py").read_text(
        encoding="utf-8"
    )
    assert not any("Course library" in (caption.value or "") for caption in app.caption)
    assert {expander.label for expander in app.expander} >= {
        "Lecture Notes · 0",
        "Readings · 0",
        "My Sources · 0",
    }
    assert rendered.index('<span class="pane-title">Thinking Path</span>') < rendered.index(
        'class="message-meta coach-welcome"'
    ) < rendered.index('<span class="pane-title">Sources</span>')
    assert ".st-key-chat_log" in rendered
    assert "overflow-y:auto" in rendered
    assert "scrollbar-color:var(--cd-scrollbar) transparent" in rendered
    assert "max-height:calc(1em * 1.45 * 3)" in rendered
    assert "min-height:4.5rem" in rendered
    assert "cd-composer-single" not in rendered
    assert "cd-composer-multiline" not in rendered
    assert "writing-mode:horizontal-tb" in rendered
    assert "height:7.9rem" not in rendered
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
    assert "Your latest contribution completed the previous step." not in rendered
    assert '[role="listbox"] [role="option"]' in rendered
    assert "-webkit-text-fill-color:currentColor" in rendered
    assert "--cd-bg:#F3F5F7" in rendered
    assert "--cd-panel:#EEF1F4" in rendered
    assert "--cd-text:#15202B" in rendered
    assert "--cd-accent:#0F766E" in rendered
    assert "cd-col-resize-handle" in rendered
    assert "cd-col-rail" in rendered
    assert ":has(.st-key-studio_rail)" in rendered
    assert "streamlit_adjustable_columns" not in rendered
    assert any(button.label == "‹" for button in app.button)
    assert any(button.label == "›" for button in app.button)
    assert "cd-roadmap" in rendered
    assert "cd-thinking-path-tip" not in rendered
    assert "less critical" not in rendered
    assert "ask to skip ahead" not in rendered
    assert "tell the coach you are ready to move on" not in rendered
    assert 'say "next" in Chat to move on' not in rendered
    assert "cd-progress-help" not in rendered
    assert "Stuck or want to move on" not in rendered
    assert "Stay on this step" not in {button.label for button in app.button}
    # Footer Next is present but disabled without a pending coach recommendation / local API.
    assert any(button.label == "Next" for button in app.button)
    assert "IBM Plex Sans" in rendered
    assert "background:var(--cd-panel)" in rendered

    button_labels = {button.label for button in app.button}
    assert {"Notebooks", "Add"} <= button_labels
    assert "About Sources" not in button_labels
    assert 'aria-label="About Sources"' not in rendered
    assert "source-title-help" not in rendered
    assert "New" not in button_labels
    assert "Assignment context" not in button_labels
    assert "Notebook details" not in button_labels
    assert "Move to next step" not in button_labels
    assert "Complete & continue" not in button_labels
    assert "Setting" not in button_labels
    assert "Settings" not in button_labels
    assert len(app.toggle) == 0
    assert len(app.feedback) == 0
    assert not any("login" in (button.label or "").lower() for button in app.button)
    assert len(app.warning) == 0

    assert any(input_widget.label == "Display name" for input_widget in app.text_input)
    assert any(control.label == "Appearance" for control in app.segmented_control)
    assert any(selectbox.label == "Language" for selectbox in app.selectbox)
    assert "cd-profile-menu" in rendered
    assert "cd-profile-help-title" in rendered
    assert "cd-profile-help-body" in rendered
    assert "stTooltipHoverTarget" in rendered
    assert not any(selectbox.label == "Model" for selectbox in app.selectbox)
    assert "st-key-composer_model_slot" in rendered
    assert any(
        (button.label or "").startswith("GPT") for button in app.button
    )
    assert not any(button.label == "Attach" for button in app.button)
    assert len(app.chat_message) == 1
    assert app.chat_message[0].name == "assistant"


def test_add_pasted_source_then_chat_with_citation():
    from backend.source_library import add_text_source
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(button for button in app.button if button.label == "Add").click().run()
    assert not app.exception
    assert {tab.label for tab in app.tabs} >= {
        "Upload",
        "Website",
        "Paste text",
    }
    assert any(item.label == "Source title" for item in app.text_input)
    assert any(item.label == "Source text" for item in app.text_area)

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
    assert len(app.chat_message) == 2
    assert any(
        "[S1] Lecture evidence" in (markdown.value or "")
        for markdown in app.markdown
    )
    assert any(
        button.label == "[S1] Lecture evidence" for button in app.button
    )


def test_multiple_citations_are_collapsed_into_sources_dropdown():
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
    assert len(source_expanders) == 1
    source_count = int(
        source_expanders[0].label.removeprefix("Sources used (").removesuffix(")")
    )
    assert source_count > 1
    assert any(
        button.label.endswith("Lecture evidence") for button in app.button
    )
    assert any(
        button.label.endswith("Reading evidence") for button in app.button
    )


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
    text_area_labels = {text_area.label for text_area in app.text_area}
    assert "My thinking at this stage" not in text_area_labels
    assert "My working conclusion" not in text_area_labels
    assert "How my understanding changed" not in text_area_labels
    assert not any(
        selectbox.label == "Current stage" for selectbox in app.selectbox
    )
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Thinking Path" in rendered
    assert "Discussion summary" in rendered
    assert "Next question" not in rendered
    next(button for button in app.button if button.label == "Notebooks").click().run()
    assert not app.exception
    assert any(
        text_input.label == "Search notebooks" for text_input in app.text_input
    )
    assert not any(selectbox.label == "Folder" for selectbox in app.selectbox)
    assert any(
        button.label == "New notebook" for button in app.button
    )
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "notebook-card-meta" in rendered
    assert "of 6" in rendered


def test_language_theme_and_journey_has_no_manual_progression_control():
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    # Preferences live in the profile settings popover (content exposed to AppTest).

    language = next(
        selectbox
        for selectbox in app.selectbox
        if selectbox.label == "Language"
    )
    assert language.options == ["English", "中文", "Bahasa Melayu", "தமிழ்"]
    language.set_value("中文").run()
    assert app.session_state["response_language"] == "中文"

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

    assert app.session_state["learning_journey"]["current_stage"] == "focus"
    assert not any(button.label == "Move to next step" for button in app.button)
    assert not any(button.label == "Move to Evidence" for button in app.button)
    assert not app.exception


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
    title.set_value("Road Safety Research").run()
    assert StudentStore().get_thread(app.session_state["thread_id"])["name"] == (
        "Road Safety Research"
    )
    next(button for button in app.button if button.label == "Notebooks").click().run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Road Safety Research" in rendered
    assert not any(button.label == "Edit title" for button in app.button)
    assert not app.exception


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
    assert "notebook-eyebrow" not in rendered
    assert "notebook-folder-tag" not in rendered
    title = next(
        text_input for text_input in app.text_input if text_input.label == "Notebook title"
    )
    assert title.value == local_store.get_thread(thread_id)["name"]

    next(button for button in app.button if button.label == "Notebooks").click().run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "notebook-card-folder" not in rendered or '<div class="notebook-card-folder">' not in rendered
    assert '<div class="notebook-card-folder">' not in rendered
    assert "notebook-current-badge" in rendered
    assert "Active research notebook" in rendered
    assert "cd-notebook-card is-active" not in rendered
    assert not any(selectbox.label == "Folder" for selectbox in app.selectbox)
    assert not any(button.label == "Manage folders" for button in app.button)
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
