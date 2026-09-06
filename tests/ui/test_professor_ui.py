"""Streamlit smoke coverage for the professor-only dashboard shell."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import auth_gate, professor


class _AnalyticsClient:
    """Deterministic FastAPI-client stand-in; the UI never reaches a store."""

    students_calls = 0
    student_detail_calls = 0
    workspace_calls = 0
    messages_calls = 0
    sources_calls = 0
    journey_calls = 0
    review_calls = 0
    transcript_calls = 0
    attachment_calls = 0
    source_calls = 0
    preferences_calls = 0
    preference_updates = []
    appearance_preferences = {"appearance": "System"}

    def professor_overview(self):
        return {
            "generated_at": "2026-08-11T09:00:00+00:00", "students": 2,
            "active_students_week": 1, "total_conversations": 1,
            "median_facione": {"value": None, "sample_size": 0},
            "median_stage": "Concept Generation", "median_active_days": 2,
            "stage_distribution": [{"stage": "Problem Identification", "count": 1, "percentage": 50}, {"stage": "Concept Generation", "count": 1, "percentage": 50}],
            "facione_profile": {"Analysis": {"value": 3, "sample_size": 1}, "Evaluation": {"value": None, "sample_size": 0}},
            "weekly_activity": [], "attention_students": [{
                "id": "student-1", "name": "Student One",
                "current_stage": "Concept Generation", "facione_overall": None,
                "last_active": None,
                "needs_attention": [{"reason": "No recent activity"}],
            }],
            "attention_students_count": 1,
            "summary": "Most students are currently working between Problem Identification and Concept Generation.",
        }

    def get_preferences(self):
        type(self).preferences_calls += 1
        return dict(type(self).appearance_preferences)

    def update_preferences(self, patch):
        type(self).preference_updates.append(dict(patch))
        type(self).appearance_preferences.update(patch)
        return dict(type(self).appearance_preferences)

    def professor_students(self, **_filters):
        type(self).students_calls += 1
        return {"total": 1, "students": [{"id": "student-1", "name": "Student One", "email": None, "current_stage": "Concept Generation", "stage_progress": 1, "facione_overall": None, "student_messages": 4, "active_days": 2, "last_active": None, "needs_attention": []}]}

    def professor_student_detail(self, _student_id):
        type(self).student_detail_calls += 1
        return {"student": self.professor_students()["students"][0], "completed_stages": ["Problem Identification"], "facione_profile": {"Analysis": 3, "Evaluation": None}, "class_facione_profile": {"Analysis": {"value": 2.5, "sample_size": 2}, "Evaluation": {"value": None, "sample_size": 0}}, "facione_trend": [{"at": "2026-08-01T00:00:00+00:00", "overall": 2.0}, {"at": "2026-08-08T00:00:00+00:00", "overall": 3.0}], "engagement": {"active_days": 2, "sessions": 1, "student_messages": 4, "assistant_messages": 4, "estimated_active_minutes": 5, "definition": "Session definition."}, "notebooks": [{"id": "notebook-1", "title": "Notebook", "stage": "Concept Generation", "messages": 7, "student_messages": 4, "coach_messages": 3, "last_active": None}], "conversations": []}

    def professor_notebook_messages(self, _student_id, _notebook_id, **_kwargs):
        type(self).messages_calls += 1
        return {
            "notebook": {
                "id": "notebook-1",
                "title": "Notebook",
                "current_stage": "Concept Generation",
                "last_active": None,
            },
            "messages": [{
                "id": "message-1",
                "role": "assistant",
                "content": "What evidence supports this design?",
                "attachments": [{"id": "attachment-1", "title": "lecture.pdf"}],
                "citations": [{"id": "source-1", "label": "S1", "title": "Lecture source"}],
            }],
            "next_cursor": None,
        }

    def professor_notebook_sources(self, _student_id, _notebook_id):
        type(self).sources_calls += 1
        return {
            "notebook": {"id": "notebook-1", "title": "Notebook"},
            "sources": [
                {
                    "id": "source-1",
                    "title": "Lecture source",
                    "selected": True,
                    "mime": "text/plain",
                    "has_file": True,
                    "group": "My Sources",
                    "locked": False,
                    "origin": "upload",
                    "kind": "file",
                    "size": 12,
                }
            ],
        }

    def professor_notebook_journey(self, _student_id, _notebook_id):
        type(self).journey_calls += 1
        return {
            "notebook": {"id": "notebook-1", "title": "Notebook"},
            "current_stage": "Concept Generation",
            "completed_stages": [],
            "stages": [
                {"id": "problem_identification", "label": "Problem Identification", "state": "not_completed"},
                {"id": "concept_generation", "label": "Concept Generation", "state": "current"},
            ],
            "hmw_scaffold": {"available": False},
        }

    def professor_notebook_review(self, _student_id, _notebook_id):
        type(self).review_calls += 1
        return {
            "notebook": {"id": "notebook-1", "title": "Notebook"},
            "summary": "The student is exploring evidence.",
            "facione_scores": {"analysis": 3},
            "strength_sections": [{
                "stage_id": "problem_identification",
                "stage": "Problem Identification",
                "items": [
                    "Names the affected people.",
                    "Deep review evidence.",
                    "Incremental coaching evidence.",
                ],
            }],
            "improvement_sections": [{
                "stage_id": "problem_identification",
                "stage": "Problem Identification",
                "items": [
                    "Clarify the success outcome.",
                    "Deep review improvement.",
                    "Incremental coaching improvement.",
                ],
            }],
            "conclusion": "",
            "stage_reviews": {
                "problem_identification": {
                    "stage_id": "problem_identification",
                    "stage": "Problem Identification",
                    "summary": "Checkpoint summary.",
                    "strengths": ["Raw-only checkpoint strength."],
                    "areas_to_revisit": ["Raw-only checkpoint improvement."],
                    "reasoning_progress": "Evidence is becoming testable.",
                    "facione_scores": {"analysis": 3},
                }
            },
            "has_personalized_assessment": True,
        }

    def professor_conversation_transcript(self, _student_id, _notebook_id):
        type(self).transcript_calls += 1
        return {"notebook_id": "notebook-1", "title": "Notebook", "messages": []}

    def professor_notebook_workspace(self, _student_id, _notebook_id):
        type(self).workspace_calls += 1
        raise AssertionError("Students UI must not call workspace")

    def professor_notebook_source(self, *_args):
        type(self).source_calls += 1
        raise AssertionError("source bytes must be fetched only on button click")

    def professor_conversation_attachment(self, *_args):
        type(self).attachment_calls += 1
        raise AssertionError("attachment bytes must be fetched only on button click")

    def professor_critical_thinking(self):
        return {"dimensions": {}, "distribution": [], "stage_comparison": [], "trend": []}

    def professor_engagement(self):
        return {"weekly_active_students": [], "weekly_messages": [], "active_day_distribution": [], "estimated_active_time_distribution": [], "inactive_students": [], "definition": "Session definition."}

    def professor_research_summary(self):
        return {
            "total_observations": 1,
            "active_observations": 1,
            "coding_status": {"coded": 1, "partial": 0, "uncoded": 0},
            "phases": {"problem_identification": 1},
            "mean_confidence": 0.8,
        }

    def professor_research_queue(self, **_filters):
        return {
            "total": 1,
            "limit": 100,
            "offset": 0,
            "items": [
                {
                    "observation_id": "observation-1",
                    "notebook_id": "notebook-1",
                    "student_id": "student-1",
                    "student_name": "Student One",
                    "student_email": None,
                    "phase": "problem_identification",
                    "coding_status": "coded",
                    "confidence": 0.8,
                    "clear_strategy": "explicit",
                    "facione_count": 1,
                    "ethics_count": 1,
                    "created_at": "2026-08-14T01:00:00+00:00",
                }
            ],
        }

    def professor_research_notebook(self, _notebook_id):
        return {
            "notebook_id": "notebook-1",
            "title": "Crossing design",
            "student": {"id": "student-1", "name": "Student One", "email": None},
            "transcript": [
                {
                    "role": "user",
                    "content": "Prioritize a safe crossing for older pedestrians.",
                    "created_at": "2026-08-14T00:55:00+00:00",
                },
            ],
            "observations": [
                {
                    "id": "observation-1",
                    "coding_status": "coded",
                    "phase_id": "problem_identification",
                    "dominant_clear": "explicit",
                    "facione_behaviors": ["analysis"],
                    "ethics_concepts": ["fairness"],
                    "evidence": [],
                    "reviews": [],
                    "adjudications": [],
                }
            ],
        }

    def professor_research_export(self, **_filters):
        return b"observation_id\nobservation-1\n"

    def professor_submit_research_review(self, payload):
        return {**payload, "id": "review-1"}

    def professor_submit_research_adjudication(self, payload):
        return {**payload, "id": "adjudication-1"}


class _FailingOverviewClient(_AnalyticsClient):
    """Client fixture that fails only the overview panel request."""

    def professor_overview(self):
        raise RuntimeError("simulated overview failure")


def _professor_auth(monkeypatch):
    """Make the existing app gate return a persisted lecturer profile."""
    user = {"id": "lecturer", "cognito_sub": "lecturer-sub", "display_name": "Dr Tan", "role": "lecturer"}
    monkeypatch.setattr(auth_gate, "authenticated_user", lambda: dict(user))
    monkeypatch.setattr(auth_gate, "current_user_claims", lambda _user=None: {"sub": "lecturer-sub", "given_name": "Dr Tan"})
    monkeypatch.setattr(professor, "local_api_client", lambda: _AnalyticsClient())
    _AnalyticsClient.students_calls = 0
    _AnalyticsClient.student_detail_calls = 0
    _AnalyticsClient.workspace_calls = 0
    _AnalyticsClient.messages_calls = 0
    _AnalyticsClient.sources_calls = 0
    _AnalyticsClient.journey_calls = 0
    _AnalyticsClient.review_calls = 0
    _AnalyticsClient.transcript_calls = 0
    _AnalyticsClient.attachment_calls = 0
    _AnalyticsClient.source_calls = 0
    _AnalyticsClient.preferences_calls = 0
    _AnalyticsClient.preference_updates = []
    _AnalyticsClient.appearance_preferences = {"appearance": "System"}


def test_professor_overview_uses_dashboard_shell_not_student_workspace(monkeypatch):
    """A lecturer sees neutral analytics and no notebook/composer initialization."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "CDE2300" in rendered
    assert "Course Analytics" in rendered
    assert len(app.chat_input) == 0
    assert any(radio.label == "Lecturer dashboard navigation" for radio in app.radio)
    assert "professor-page-context" not in rendered
    assert "Last refresh" in rendered
    assert '<span>Class snapshot</span>' not in rendered


def test_professor_display_labels_preserve_internal_page_tokens() -> None:
    """Lecturer copy is clear while durable navigation values stay compatible."""
    assert professor._PAGES == ("Overview", "Students", "Learning", "Engagement", "Research")
    assert [professor._page_display_label(page) for page in professor._PAGES] == [
        "Overview",
        "Students",
        "Critical thinking",
        "Participation",
        "Research review",
    ]


def test_professor_workbench_activity_filter_is_truthful() -> None:
    """The roster filter describes presence of activity, not an unimplemented date window."""
    rows = [
        {"id": "active", "last_active": None, "student_messages": 2},
        {"id": "idle", "last_active": None, "student_messages": 0},
    ]
    assert [row["id"] for row in professor._workbench_filter_rows(rows, "Has activity")] == ["active"]
    assert professor._workbench_filter_rows(rows, "Recent activity") == rows


def test_professor_line_chart_keeps_temporal_axis_with_explicit_domain(monkeypatch) -> None:
    """Trend charts preserve unequal time gaps without emitting empty extents."""
    captured = {}
    monkeypatch.setattr(
        professor.st,
        "altair_chart",
        lambda chart, **_kwargs: captured.setdefault("chart", chart),
    )
    professor._line_chart(
        [
            {"at": "2026-08-01T00:00:00+00:00", "overall": 2},
            {"at": "2026-08-08T00:00:00+00:00", "overall": 3},
        ],
        x="at",
        y="overall",
        x_label="Assessment",
        y_label="Overall score (0–4)",
        y_domain=(0, 4),
    )
    encoding = captured["chart"].to_dict()["encoding"]
    assert encoding["x"]["type"] == "temporal"
    assert encoding["x"]["field"] == "_professor_chart_date"
    assert encoding["x"]["scale"]["domain"] == [
        "2026-07-31T12:00:00+00:00",
        "2026-08-08T12:00:00+00:00",
    ]
    assert encoding["x"]["scale"]["type"] == "utc"
    assert encoding["x"]["axis"]["tickCount"] == {"interval": "day", "step": 1}
    assert encoding["x"]["axis"]["labelOverlap"] is True
    assert encoding["x"]["axis"]["labelFlush"] is True


def test_professor_overview_follow_up_opens_student_record(monkeypatch):
    """A follow-up signal routes directly to the matching student record."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    follow_up = next(
        button for button in app.button if button.key == "professor_followup_student-1"
    )
    assert follow_up.label == "Open"
    follow_up.click().run()
    assert not app.exception
    assert app.session_state["professor_page"] == "Students"
    assert app.session_state["professor_selected_student_id"] == "student-1"
    assert "#### Notebooks" in "\n".join(markdown.value or "" for markdown in app.markdown)


def test_professor_overview_failure_is_localized_to_panel(monkeypatch):
    """One unavailable analytics panel exposes a safe retry without a shell crash."""
    _professor_auth(monkeypatch)
    monkeypatch.setattr(professor, "local_api_client", lambda: _FailingOverviewClient())
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    errors = "\n".join(error.value or "" for error in app.error)
    assert "class snapshot is unavailable" in errors.lower()
    assert any(button.key == "professor_overview_retry" for button in app.button)
    assert "Professor analytics is unavailable" not in rendered


def test_professor_mobile_section_selector_keeps_one_desktop_navigation(monkeypatch):
    """Desktop keeps one persistent rail; the compact selector is mobile-only."""
    _professor_auth(monkeypatch)
    from ui import settings as settings_module

    class _PreferenceSink:
        def update_user_preferences(self, patch):
            _AnalyticsClient.preference_updates.append(dict(patch))

    monkeypatch.setattr(settings_module, "store", _PreferenceSink())
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception

    section = next(selectbox for selectbox in app.selectbox if selectbox.label == "Section")
    assert section.value == "Overview"
    section.set_value("Students").run()
    navigation = [
        radio for radio in app.radio if radio.label == "Lecturer dashboard navigation"
    ]
    assert len(navigation) == 1
    assert navigation[0].value == "Students"
    assert any(input.label == "Search students" for input in app.text_input)

    appearance = next(
        selectbox for selectbox in app.selectbox if selectbox.label == "Appearance"
    )
    appearance.set_value("Light").run()
    assert app.session_state["appearance"] == "Light"
    assert _AnalyticsClient.preference_updates[-1] == {"appearance": "Light"}


def test_professor_restores_and_persists_appearance_without_student_init(monkeypatch):
    """Lecturer appearance uses preferences without creating a notebook."""
    _professor_auth(monkeypatch)
    _AnalyticsClient.appearance_preferences = {"appearance": "Dark"}
    from ui import settings as settings_module

    class _PreferenceSink:
        def update_user_preferences(self, patch):
            _AnalyticsClient.preference_updates.append(dict(patch))

    monkeypatch.setattr(settings_module, "store", _PreferenceSink())
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert app.session_state["appearance"] == "Dark"
    assert app.session_state["setting_appearance"] == "Dark"
    assert _AnalyticsClient.preferences_calls == 1
    assert _AnalyticsClient.messages_calls == 0
    assert _AnalyticsClient.student_detail_calls == 0
    appearance = next(
        control for control in app.segmented_control if control.label == "Appearance"
    )
    appearance.set_value("Light").run()
    assert app.session_state["appearance"] == "Light"
    assert _AnalyticsClient.preference_updates == [{"appearance": "Light"}]


def test_professor_appearance_failure_keeps_dashboard_and_shows_recovery_copy(monkeypatch):
    """A preference outage is localized while the selected theme remains usable."""
    _professor_auth(monkeypatch)
    from ui import settings as settings_module

    class _FailingPreferenceSink:
        def update_user_preferences(self, _patch):
            raise RuntimeError("simulated preference outage")

    monkeypatch.setattr(settings_module, "store", _FailingPreferenceSink())
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    appearance = next(
        control for control in app.segmented_control if control.label == "Appearance"
    )
    appearance.set_value("Dark").run()
    assert not app.exception
    assert app.session_state["appearance"] == "Dark"
    captions = "\n".join(caption.value or "" for caption in app.caption)
    assert "Appearance updated for this session" in captions
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Overview" in rendered


def test_professor_students_renders_missing_score_and_filters(monkeypatch):
    """Students opens with a lightweight roster and no selected detail fetch."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation")
    navigation.set_value("Students").run()
    assert not app.exception
    assert any(input.label == "Search students" for input in app.text_input)
    assert _AnalyticsClient.students_calls == 1
    assert _AnalyticsClient.student_detail_calls == 0
    assert _AnalyticsClient.messages_calls == 0
    assert _AnalyticsClient.sources_calls == 0
    assert _AnalyticsClient.journey_calls == 0
    assert _AnalyticsClient.review_calls == 0
    assert professor._score(None) == "Not assessed"
    assert professor._PHASE_LABELS == (
        "Problem Identification",
        "Concept Generation",
        "Design Specification",
        "Ethics & Critical Thinking",
        "Reflection",
    )
    assert "/ 6" not in Path("ui/professor.py").read_text(encoding="utf-8")


def test_professor_research_renders_three_step_validation_workbench(monkeypatch):
    """Research stays in the professor shell with queue, transcript, and validation."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(
        radio for radio in app.radio
        if radio.label == "Lecturer dashboard navigation"
    )
    navigation.set_value("Research").run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Research review" in rendered
    assert "Validation queue" in rendered
    assert "Student transcript" in rendered
    assert "Automated coding" in rendered
    assert "Human validation" in rendered
    assert not app.chat_input


def test_professor_student_and_workspace_calls_are_progressive(monkeypatch):
    """Student detail waits for roster selection; tab endpoints wait for notebook open."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation")
    navigation.set_value("Students").run()
    assert _AnalyticsClient.students_calls == 1
    assert _AnalyticsClient.student_detail_calls == 0
    assert _AnalyticsClient.workspace_calls == 0
    assert _AnalyticsClient.messages_calls == 0
    student_open = next(
        button for button in app.button if button.key == "professor_open_student_student-1"
    )
    student_open.click().run()
    assert _AnalyticsClient.student_detail_calls == 1
    assert _AnalyticsClient.workspace_calls == 0
    assert _AnalyticsClient.messages_calls == 0
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "#### Notebooks" in rendered
    assert "#### Thinking path snapshot" in rendered
    assert "#### Participation" in rendered
    assert not any(
        'class="professor-page-header"' in (markdown.value or "")
        for markdown in app.markdown
    )
    assert any(
        button.key == "professor_open_notebook_btn_student-1_notebook-1"
        and button.label == "Open"
        for button in app.button
    )
    assert professor._notebook_row_caption({
        "title": "Notebook", "stage": "Concept Generation",
        "student_messages": 4, "coach_messages": 3, "last_active": None,
    }).startswith("Concept Generation · 4 student · 3 coach")
    notebook_open = next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    )
    notebook_open.click().run()
    assert _AnalyticsClient.messages_calls == 1
    assert _AnalyticsClient.sources_calls == 0
    assert _AnalyticsClient.journey_calls == 0
    assert _AnalyticsClient.review_calls == 0
    assert _AnalyticsClient.workspace_calls == 0
    workspace_tabs = next(
        radio for radio in app.radio if radio.label == "Notebook content"
    )
    assert workspace_tabs.value == "Chat"
    assert _AnalyticsClient.source_calls == 0
    workspace_rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Sources used" in workspace_rendered
    assert "Selected" in workspace_rendered
    workspace_tabs.set_value("Sources").run()
    assert _AnalyticsClient.sources_calls == 1
    assert _AnalyticsClient.journey_calls == 0
    next(
        button for button in app.button
        if button.key == "professor_path_progression_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.journey_calls == 1
    next(
        button for button in app.button
        if button.key == "professor_path_review_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.review_calls == 1
    assert next(
        radio for radio in app.radio if radio.label == "Notebook content"
    ).value == "Sources"


def test_professor_thinking_path_keeps_independent_tab_state(monkeypatch):
    """Thinking Path controls have independent selection and shared payload caches."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation").set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.messages_calls == 1
    assert _AnalyticsClient.review_calls == 0
    assert _AnalyticsClient.journey_calls == 0

    next(
        button for button in app.button
        if button.key == "professor_path_review_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.review_calls == 1
    assert _AnalyticsClient.journey_calls == 0
    workspace_tabs = next(radio for radio in app.radio if radio.label == "Notebook content")
    assert workspace_tabs.value == "Chat"

    next(
        button for button in app.button
        if button.key == "professor_path_progression_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.journey_calls == 1
    assert _AnalyticsClient.review_calls == 1
    assert next(radio for radio in app.radio if radio.label == "Notebook content").value == "Chat"

    next(
        button for button in app.button
        if button.key == "professor_path_review_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.review_calls == 1
    assert _AnalyticsClient.journey_calls == 1
    assert next(radio for radio in app.radio if radio.label == "Notebook content").value == "Chat"
    review_rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Checkpoint summary." in review_rendered
    assert "Names the affected people." in review_rendered
    assert "Deep review evidence." in review_rendered
    assert "Incremental coaching evidence." in review_rendered
    assert "Deep review improvement." in review_rendered
    assert "Incremental coaching improvement." in review_rendered
    assert "Raw-only checkpoint strength." not in review_rendered
    assert "Raw-only checkpoint improvement." not in review_rendered
    assert "Reasoning progress" in review_rendered
    assert "Areas for improvement" in review_rendered

    workspace_tabs = next(radio for radio in app.radio if radio.label == "Notebook content")
    workspace_tabs.set_value("Sources").run()
    next(
        button for button in app.button
        if button.key == "professor_path_progression_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.journey_calls == 1
    assert _AnalyticsClient.review_calls == 1
    assert next(radio for radio in app.radio if radio.label == "Notebook content").value == "Sources"


def test_professor_workbench_mobile_view_and_appearance(monkeypatch):
    """The compact mobile view selector routes one surface at a time."""
    _professor_auth(monkeypatch)
    from ui import settings as settings_module

    class _PreferenceSink:
        def update_user_preferences(self, patch):
            _AnalyticsClient.preference_updates.append(dict(patch))

    monkeypatch.setattr(settings_module, "store", _PreferenceSink())
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation").set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    ).click().run()

    assert not any(selectbox.label == "Screen" for selectbox in app.selectbox)
    view = next(selectbox for selectbox in app.selectbox if selectbox.label == "View")
    assert view.value == "Chat"
    assert tuple(view.options) == ("Roster", "Chat", "Sources", "Thinking Path")
    view.set_value("Sources").run()
    assert _AnalyticsClient.sources_calls == 1
    assert next(radio for radio in app.radio if radio.label == "Notebook content").value == "Sources"
    view = next(selectbox for selectbox in app.selectbox if selectbox.label == "View")
    view.set_value("Thinking Path").run()
    assert not app.exception
    assert _AnalyticsClient.journey_calls == 1
    mobile_review = next(
        button for button in app.button
        if button.key == "professor_path_review_student-1_notebook-1_mobile"
    )
    mobile_review.click().run()
    assert not app.exception
    assert _AnalyticsClient.review_calls == 1

    appearance = next(selectbox for selectbox in app.selectbox if selectbox.label == "Appearance")
    appearance.set_value("Light").run()
    assert app.session_state["appearance"] == "Light"
    assert _AnalyticsClient.preference_updates[-1] == {"appearance": "Light"}


def test_professor_journey_does_not_infer_completion(monkeypatch):
    """Journey display uses persisted completion, not stage index inference."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation")
    navigation.set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    ).click().run()
    next(
        button for button in app.button
        if button.key == "professor_path_progression_student-1_notebook-1"
    ).click().run()
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Problem Identification" in rendered
    assert "Not completed" in rendered
    assert "Current focus" in rendered


def test_professor_citation_display_prefers_friendly_safe_reference() -> None:
    """Transcript citation labels remain friendly without rendering raw HTML."""
    assert professor._citation_display({"id": "source-1", "label": "S1", "title": "Lecture source"}) == r"\[S1\] Lecture source"
    assert "<script>" not in professor._citation_display({"id": "source-1", "title": "<script>"})


def test_professor_chat_renders_markdown_without_html_escape() -> None:
    """Chat message bodies use Streamlit Markdown instead of escaped HTML blobs."""
    source = Path("ui/professor.py").read_text(encoding="utf-8")
    assert "professor-chat-body" not in source
    assert "st.markdown(content)" in source


def test_professor_refresh_refetches_cached_student_detail(monkeypatch):
    """Refresh invalidates only the selected student's cached detail."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation")
    navigation.set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    assert _AnalyticsClient.student_detail_calls == 1
    next(
        button for button in app.button
        if button.key == "professor_refresh_student_student-1"
    ).click().run()
    assert _AnalyticsClient.student_detail_calls == 2


def test_professor_refresh_refetches_cached_chat(monkeypatch):
    """Refresh invalidates only the opened notebook chat cache."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Lecturer dashboard navigation")
    navigation.set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.messages_calls == 1
    next(
        button for button in app.button
        if button.key == "professor_workbench_refresh_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.messages_calls == 2


def test_professor_workspace_ui_is_read_only() -> None:
    """Professor workspace UI does not call student mutation client methods."""
    source = Path("ui/professor.py").read_text(encoding="utf-8")
    forbidden = (
        "send_message",
        "upload_sources",
        "upload_attachments",
        "delete_source",
        "rename_source",
        "select_sources",
        "confirm_stage",
        "start_deep_review",
        "revise_conversation",
    )
    assert not any(token in source for token in forbidden)


def test_professor_research_css_has_desktop_tablet_and_mobile_contracts() -> None:
    """Scoped CSS keeps the persistent rail and one-scroll mobile workbench."""
    component = Path("ui/assets/styles/70-professor.css").read_text(encoding="utf-8")
    responsive = Path("ui/assets/styles/90-responsive.css").read_text(encoding="utf-8")
    assert ".st-key-research_workspace" in component
    assert "html:has(.st-key-professor_shell)" in component
    assert ".st-key-professor_student_list_scroll" in component
    assert "st-key-professor_transcript_scroll" in component
    assert ".st-key-professor_shell" in component
    assert "professor-sidebar" in component
    assert "professor-timeline-step" in component
    assert "professor_mobile_header" in component
    assert "professor-workbench-context" in component
    assert "professor_mobile_workbench" in component
    assert '[class*="st-key-professor_notebook_card_"]' in component
    assert "border:1px solid var(--cd-border) !important" in component
    assert "height:clamp(30rem, calc(100dvh - 10rem), 52rem)" in component
    assert "overflow:visible !important" in component
    assert "scrollbar-gutter:stable" in component
    assert '[data-testid="stLayoutWrapper"]' in component
    assert "height:100dvh !important" not in component
    assert "max-height:18rem" not in component
    assert "max-height:56vh" not in component
    assert "professor_dashboard_topbar" not in component
    assert "professor-topbar-account" not in component
    assert "@media (max-width:800px)" in component
    assert "research-queue-marker" not in responsive
    assert "max-width:1100px" in responsive
    assert "max-width:520px" in responsive
