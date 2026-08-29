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

    def professor_overview(self):
        return {
            "generated_at": "2026-08-11T09:00:00+00:00", "students": 2,
            "active_students_week": 1, "total_conversations": 1,
            "median_facione": {"value": None, "sample_size": 0},
            "median_stage": "Concept Generation", "median_active_days": 2,
            "stage_distribution": [{"stage": "Problem Identification", "count": 1, "percentage": 50}, {"stage": "Concept Generation", "count": 1, "percentage": 50}],
            "facione_profile": {"Analysis": {"value": 3, "sample_size": 1}, "Evaluation": {"value": None, "sample_size": 0}},
            "weekly_activity": [], "attention_students": [],
            "attention_students_count": 0,
            "summary": "Most students are currently working between Problem Identification and Concept Generation.",
        }

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
            "strength_sections": [],
            "improvement_sections": [],
            "conclusion": "",
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


def test_professor_overview_uses_dashboard_shell_not_student_workspace(monkeypatch):
    """A lecturer sees neutral analytics and no notebook/composer initialization."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "CDE2300" in rendered
    assert "Course Analytics" in rendered
    assert len(app.chat_input) == 0
    assert any(radio.label == "Professor dashboard navigation" for radio in app.radio)


def test_professor_students_renders_missing_score_and_filters(monkeypatch):
    """Students opens with a lightweight roster and no selected detail fetch."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
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
        if radio.label == "Professor dashboard navigation"
    )
    navigation.set_value("Research").run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Research Review" in rendered
    assert "Validation queue" in rendered
    assert "Student transcript" in rendered
    assert "Automated coding" in rendered
    assert "Human validation" in rendered
    assert not app.chat_input


def test_professor_student_and_workspace_calls_are_progressive(monkeypatch):
    """Student detail waits for roster selection; tab endpoints wait for notebook open."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
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
    assert "#### Learning snapshot" in rendered
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
        radio for radio in app.radio if radio.label == "Notebook workspace"
    )
    assert workspace_tabs.value == "Chat"
    assert _AnalyticsClient.source_calls == 0
    workspace_rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Sources used" in workspace_rendered
    workspace_tabs.set_value("Sources").run()
    assert _AnalyticsClient.sources_calls == 1
    assert _AnalyticsClient.journey_calls == 0
    workspace_tabs.set_value("Progression").run()
    assert _AnalyticsClient.journey_calls == 1
    workspace_tabs.set_value("Review").run()
    assert _AnalyticsClient.review_calls == 1


def test_professor_journey_does_not_infer_completion(monkeypatch):
    """Journey display uses persisted completion, not stage index inference."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
    navigation.set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    ).click().run()
    next(radio for radio in app.radio if radio.label == "Notebook workspace").set_value("Progression").run()
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
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
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
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
    navigation.set_value("Students").run()
    next(button for button in app.button if button.key == "professor_open_student_student-1").click().run()
    next(
        button for button in app.button
        if button.key == "professor_open_notebook_btn_student-1_notebook-1"
    ).click().run()
    assert _AnalyticsClient.messages_calls == 1
    next(
        button for button in app.button
        if button.key == "professor_refresh_chat_student-1_notebook-1"
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
    """Scoped CSS keeps sidebar shell and stacked 390 px flow."""
    component = Path("ui/assets/styles/70-professor.css").read_text(encoding="utf-8")
    responsive = Path("ui/assets/styles/90-responsive.css").read_text(encoding="utf-8")
    assert ".st-key-research_workspace" in component
    assert "html:has(.st-key-professor_header)" in component
    assert ".st-key-professor_student_list_scroll" in component
    assert ".st-key-professor_transcript_scroll" in component
    assert ".st-key-professor_shell" in component
    assert "professor-sidebar" in component
    assert "professor-timeline-step" in component
    assert "@media (max-width:800px)" in component
    assert "research-queue-marker" not in responsive
    assert "max-width:1100px" in responsive
    assert "max-width:520px" in responsive
