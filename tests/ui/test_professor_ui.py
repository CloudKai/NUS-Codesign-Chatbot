"""Streamlit smoke coverage for the professor-only dashboard shell."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import auth_gate, professor


class _AnalyticsClient:
    """Deterministic FastAPI-client stand-in; the UI never reaches a store."""

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
        return {"student": self.professor_students()["students"][0], "completed_stages": ["Problem Identification"], "facione_profile": {"Analysis": 3, "Evaluation": None}, "facione_trend": [], "engagement": {"active_days": 2, "sessions": 1, "student_messages": 4, "assistant_messages": 4, "estimated_active_minutes": 5, "definition": "Session definition."}, "notebooks": [], "conversations": []}

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
    """Roster UI keeps unassessed students distinct from a zero score."""
    _professor_auth(monkeypatch)
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    navigation = next(radio for radio in app.radio if radio.label == "Professor dashboard navigation")
    navigation.set_value("Students").run()
    assert not app.exception
    assert any(input.label == "Search students" for input in app.text_input)
    assert app.dataframe
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
    assert "Research coding review" in rendered
    assert "Validation queue" in rendered
    assert "Student transcript" in rendered
    assert "Automated coding" in rendered
    assert "Human validation" in rendered
    captions = "\n".join(caption.value or "" for caption in app.caption)
    assert "not a grade" in captions
    assert any(
        radio.label == "Research workflow step" and radio.options == [
            "Queue", "Transcript", "Validate"
        ]
        for radio in app.radio
    )
    assert not app.chat_input


def test_professor_research_css_has_desktop_tablet_and_mobile_contracts() -> None:
    """Scoped CSS keeps a three-pane desktop and single-step 390 px flow."""
    component = Path("ui/assets/styles/70-professor.css").read_text(encoding="utf-8")
    responsive = Path("ui/assets/styles/90-responsive.css").read_text(encoding="utf-8")
    assert ".st-key-research_workspace" in component
    assert ".research-queue-marker" in responsive
    assert ".research-transcript-marker" in responsive
    assert ".research-validation-marker" in responsive
    assert "max-width:1100px" in responsive
    assert "max-width:520px" in responsive
    assert ".st-key-research_mobile_step" in responsive
