"""Streamlit smoke coverage for the professor-only dashboard shell."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import auth_gate, professor


class _AnalyticsClient:
    """Deterministic FastAPI-client stand-in; the UI never reaches a store."""

    student_detail_calls = 0
    transcript_calls = 0
    attachment_calls = 0

    def professor_overview(self):
        return {
            "generated_at": "2026-08-11T09:00:00+00:00", "students": 2,
            "active_students_week": 1, "total_conversations": 1,
            "median_facione": {"value": None, "sample_size": 0},
            "median_stage": "Concept Generation", "median_active_days": 2,
            "stage_distribution": [{"stage": "Problem Identification", "count": 1, "percentage": 50}, {"stage": "Concept Generation", "count": 1, "percentage": 50}],
            "facione_profile": {"Analysis": {"value": 3, "sample_size": 1}, "Evaluation": {"value": None, "sample_size": 0}},
            "weekly_activity": [], "attention_students": [],
            "summary": "Most students are currently working between Problem Identification and Concept Generation.",
        }

    def professor_students(self, **_filters):
        return {"total": 1, "students": [{"id": "student-1", "name": "Student One", "email": None, "current_stage": "Concept Generation", "stage_progress": 1, "facione_overall": None, "student_messages": 4, "active_days": 2, "last_active": None, "needs_attention": []}]}

    def professor_student_detail(self, _student_id):
        type(self).student_detail_calls += 1
        return {"student": self.professor_students()["students"][0], "completed_stages": ["Problem Identification"], "facione_profile": {"Analysis": 3, "Evaluation": None}, "class_facione_profile": {"Analysis": {"value": 2.5, "sample_size": 2}, "Evaluation": {"value": None, "sample_size": 0}}, "facione_trend": [{"at": "2026-08-01T00:00:00+00:00", "overall": 2.0}, {"at": "2026-08-08T00:00:00+00:00", "overall": 3.0}], "engagement": {"active_days": 2, "sessions": 1, "student_messages": 4, "assistant_messages": 4, "estimated_active_minutes": 5, "definition": "Session definition."}, "notebooks": [{"id": "notebook-1", "title": "Notebook", "stage": "Concept Generation", "messages": 7, "student_messages": 4, "last_active": None}], "conversations": []}

    def professor_conversation_transcript(self, _student_id, _notebook_id):
        type(self).transcript_calls += 1
        return {
            "notebook_id": "notebook-1",
            "title": "Notebook",
            "messages": [{
                "id": "message-1",
                "role": "assistant",
                "content": "What evidence supports this design?",
                "attachments": [{"id": "attachment-1", "title": "lecture.pdf"}],
                "citations": [{"id": "source-1", "label": "S1", "title": "Lecture source"}],
            }],
        }

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
                {
                    "role": "assistant",
                    "content": "What evidence would show that outcome?",
                    "created_at": "2026-08-14T01:00:00+00:00",
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
                    "evidence": [
                        {
                            "start_offset": 0,
                            "end_offset": 10,
                            "rationale": "The constraint is explicit.",
                            "confidence": 0.8,
                        }
                    ],
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
    _AnalyticsClient.student_detail_calls = 0
    _AnalyticsClient.transcript_calls = 0
    _AnalyticsClient.attachment_calls = 0


def test_professor_overview_uses_dashboard_shell_not_student_workspace(monkeypatch):
    """A lecturer sees neutral analytics and no notebook/composer initialization."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "CDE2300 · Product Design and Innovation" in rendered
    assert "Not assessed" in rendered
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
    assert not app.dataframe
    assert any("Select a student to view their learning progress" in (info.value or "") for info in app.info)
    assert _AnalyticsClient.student_detail_calls == 0
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
    navigation.set_value("Research Review").run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Research Review" in rendered
    assert "Validation queue" in rendered
    assert "Student transcript" in rendered
    assert "Automated coding" in rendered
    assert "Human validation" in rendered
    captions = "\n".join(caption.value or "" for caption in app.caption)
    assert "not a grade" in captions
    assert not any(radio.label == "Research workflow step" for radio in app.radio)
    assert not app.chat_input


def test_professor_student_and_transcript_calls_are_progressive(monkeypatch):
    """Student detail and transcript requests wait for their explicit selections."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
    navigation.set_value("Students").run()
    assert _AnalyticsClient.student_detail_calls == 0
    assert _AnalyticsClient.attachment_calls == 0
    selected = next(radio for radio in app.radio if radio.key == "professor_selected_student")
    selected.set_value("student-1").run()
    assert _AnalyticsClient.student_detail_calls == 1
    assert _AnalyticsClient.transcript_calls == 0
    assert _AnalyticsClient.attachment_calls == 0
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    captions = "\n".join(caption.value or "" for caption in app.caption)
    assert "class 2.5 (n=2)" in rendered
    assert "Critical-thinking trend" in rendered
    assert "Assessment trend is descriptive only" in captions
    assert "Active days" in rendered and "Sessions" in rendered
    assert "Estimated active time" in rendered
    assert professor._notebook_label({
        "title": "Notebook", "stage": "Concept Generation", "messages": 7,
        "student_messages": 4, "last_active": None,
    }) == "Notebook · Concept Generation · 7 total messages · 4 student messages · No activity"
    next(button for button in app.button if button.label == "View active transcript").click().run()
    assert _AnalyticsClient.transcript_calls == 1
    assert _AnalyticsClient.attachment_calls == 0
    assert any(button.label == "Open attachment" for button in app.button)
    assert any(r"\[S1\] Lecture source" in (caption.value or "") for caption in app.caption)


def test_professor_citation_display_prefers_friendly_safe_reference() -> None:
    """Transcript citation labels remain friendly without rendering raw HTML."""
    assert professor._citation_display({"id": "source-1", "label": "S1", "title": "Lecture source"}) == r"\[S1\] Lecture source"
    assert "<script>" not in professor._citation_display({"id": "source-1", "title": "<script>"})


def test_professor_research_css_has_desktop_tablet_and_mobile_contracts() -> None:
    """Scoped CSS keeps a two-column desktop and stacked 390 px flow."""
    component = Path("ui/assets/styles/70-professor.css").read_text(encoding="utf-8")
    responsive = Path("ui/assets/styles/90-responsive.css").read_text(encoding="utf-8")
    assert ".st-key-research_workspace" in component
    assert "research-queue-marker" not in responsive
    assert "research-transcript-marker" not in responsive
    assert "research-validation-marker" not in responsive
    assert "max-width:1100px" in responsive
    assert "max-width:520px" in responsive
    assert "grid-template-columns:minmax(15rem,.8fr) minmax(0,1.2fr)" in responsive
    assert ":has(.research-validation-marker)" not in responsive
