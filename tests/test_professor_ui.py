"""Streamlit smoke coverage for the professor-only dashboard shell."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from ui import auth_gate, professor


class _AnalyticsClient:
    """Deterministic FastAPI-client stand-in; the UI never reaches a store."""

    def professor_overview(self):
        return {
            "generated_at": "2026-08-11T09:00:00+00:00", "students": 2,
            "active_students_week": 1, "total_conversations": 1,
            "median_facione": {"value": None, "sample_size": 0},
            "median_stage": "Evidence", "median_active_days": 2,
            "stage_distribution": [{"stage": "Focus", "count": 1, "percentage": 50}, {"stage": "Evidence", "count": 1, "percentage": 50}],
            "facione_profile": {"Analysis": {"value": 3, "sample_size": 1}, "Evaluation": {"value": None, "sample_size": 0}},
            "weekly_activity": [], "attention_students": [],
            "summary": "Most students are currently working between Evidence and Assumptions.",
        }

    def professor_students(self, **_filters):
        return {"total": 1, "students": [{"id": "student-1", "name": "Student One", "email": None, "current_stage": "Evidence", "stage_progress": 1, "facione_overall": None, "student_messages": 4, "active_days": 2, "last_active": None, "needs_attention": []}]}

    def professor_student_detail(self, _student_id):
        return {"student": self.professor_students()["students"][0], "completed_stages": ["Focus"], "facione_profile": {"Analysis": 3, "Evaluation": None}, "facione_trend": [], "engagement": {"active_days": 2, "sessions": 1, "student_messages": 4, "assistant_messages": 4, "estimated_active_minutes": 5, "definition": "Session definition."}, "notebooks": [], "conversations": []}

    def professor_critical_thinking(self):
        return {"dimensions": {}, "distribution": [], "stage_comparison": [], "trend": []}

    def professor_engagement(self):
        return {"weekly_active_students": [], "weekly_messages": [], "active_day_distribution": [], "estimated_active_time_distribution": [], "inactive_students": [], "definition": "Session definition."}


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
