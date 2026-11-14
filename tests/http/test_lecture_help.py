"""Lecture intent contracts through the existing authenticated student API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from backend.domain import (
    CoachRequest,
    EducationalAssessment,
    ProviderAssessmentResult,
    StageDecision,
)
from backend.mock_provider import DeterministicCoachProvider


def test_lecture_help_without_evidence_preserves_project_progress(tmp_path: Path) -> None:
    """An explicit lecture question cannot become coaching or invent evidence."""
    store = StudentStore(tmp_path / "lecture.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = TestClient(create_app(store, auto_advance_stages=True))
    path = f"/api/v1/threads/{thread_id}"
    before = client.get(f"{path}/learning-state").json()
    reply = client.post("/api/v1/coach/turn", json={
        "thread_id": thread_id,
        "student_message": "I think this concept is confusing. Help me understand.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "interaction_intent": "lecture_help",
        "idempotency_key": "lecture-gap",
    })
    assert reply.status_code == 200
    turn = reply.json()
    assert turn["assessment"]["response_mode"] == "qa"
    assert turn["assessment"]["recommendation"] is None
    assert turn["assessment"]["citations"] == []
    assert "couldn't find" in turn["response_text"]
    assert turn["pending_transition"] is None
    assert client.get(f"{path}/phase-transitions/pending").json() is None
    after = client.get(f"{path}/learning-state").json()
    for key in before:
        assert after[key] == before[key]
    assert after["coaching_turns_since_deep_review"] == 0


def test_lecture_evidence_and_project_application_share_notebook(tmp_path: Path) -> None:
    """A grounded lecture reply cites the selected source and can lead to coaching."""
    store = StudentStore(tmp_path / "grounded.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(store, thread_id, "Analogy notes", "Analogy transfers a relationship from a familiar setting to a new design problem.")
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f"/api/v1/threads/{thread_id}"
    request = {
        "thread_id": thread_id,
        "student_message": "I think analogy is confusing. Help me understand analogy.",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "interaction_intent": "lecture_help",
        "idempotency_key": "analogy-lecture",
    }
    reply = client.post("/api/v1/coach/turn", json=request)
    assert reply.status_code == 200
    turn = reply.json()
    assert turn["assessment"]["response_mode"] == "qa"
    assert turn["assessment"]["recommendation"] is None
    assert "Analogy transfers" in turn["response_text"]
    citation = turn["assessment"]["citations"][0]
    assert citation["source_id"] == source["id"]
    evidence = client.get(f"{path}/sources/{citation['source_id']}")
    assert evidence.status_code == 200
    assert "Analogy transfers" in str(evidence.json())
    applied = client.post("/api/v1/coach/turn", json={
        **request,
        "student_message": "I want to use analogy in my project to help older people cross roads safely.",
        "interaction_intent": "project_coaching",
        "idempotency_key": "analogy-application",
    })
    assert applied.status_code == 200
    assert applied.json()["assessment"]["response_mode"] == "coaching"
    history = client.get(f"{path}/messages").json()
    assert len(history) == 4
    assert history[0]["content"] == request["student_message"]
    assert history[1]["metadata"]["interaction_intent"] == "lecture_help"


@pytest.mark.parametrize("message", ["confirm", "move me to concept generation", "Can I move on?", "What stage am I in?"])
def test_lecture_help_cannot_navigate_or_award_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, message: str,
) -> None:
    """Lecture intent wins over commands and an incorrectly coaching provider."""
    class IncorrectModeProvider(DeterministicCoachProvider):
        """Simulate a model ignoring the trusted Q&A instruction."""

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            """Return unsolicited project awards to exercise application guards."""
            return ProviderAssessmentResult(
                response_text="Analogy transfers relationships [S1].",
                qualifying_coaching_turn=True,
                deep_review_succeeded=True,
                assessment=EducationalAssessment(
                    current_stage=request.current_stage,
                    response_mode="coaching",
                    recommendation=StageDecision.ADVANCE,
                    learning_summary="Unsolicited lecture progress",
                    working_conclusion="Unsolicited conclusion",
                    hmw_scaffold_ready=True,
                ),
            )

    import backend.owner_context as owners

    monkeypatch.setattr(owners, "configured_coach_provider", lambda: IncorrectModeProvider())
    database = tmp_path / "navigation.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={"learning_summary": "Saved project work"})
    add_text_source(store, thread_id, "Analogy", "Analogy transfers relationships between designs.")
    client = TestClient(create_app(store, auto_advance_stages=False))
    path = f"/api/v1/threads/{thread_id}"
    request = {
        "thread_id": thread_id,
        "student_message": "How might we help older people cross roads so they can travel safely?",
        "current_stage": "problem_identification",
        "response_detail": "short",
        "idempotency_key": "initial-project",
    }
    project = client.post("/api/v1/coach/turn", json=request)
    assert project.status_code == 200
    pending = client.get(f"{path}/phase-transitions/pending").json()
    assert pending is not None
    store.update_thread(thread_id, metadata={"coaching_turns_since_deep_review": 2})
    before = client.get(f"{path}/learning-state").json()
    reply = client.post("/api/v1/coach/turn", json={
        **request, "student_message": message,
        "interaction_intent": "lecture_help", "idempotency_key": "lecture-command",
    })
    assert reply.status_code == 200
    turn = reply.json()
    assert turn["assessment"]["response_mode"] == "qa"
    assert turn["assessment"]["recommendation"] is None
    assert turn["pending_transition"] is None
    assert turn["auto_advanced_to"] is None
    after = client.get(f"{path}/learning-state").json()
    for key in ("learning_journey", "learning_summary", "working_conclusion", "coaching_turns_since_deep_review"):
        assert after.get(key) == before.get(key)
    assert client.get(f"{path}/phase-transitions/pending").json() == pending
    restarted = TestClient(create_app(StudentStore(database)))
    assert restarted.get(f"{path}/coach-turn", params={"idempotency_key": "lecture-command"}).json() == turn


def test_lecture_intent_is_validated_and_deselected_sources_stay_private(tmp_path: Path) -> None:
    """An intent cannot inject privileged routing or retrieve deselected evidence."""
    store = StudentStore(tmp_path / "selection.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(store, thread_id, "Private note", "SECRET_EVIDENCE_791")
    client = TestClient(create_app(store))
    path = f"/api/v1/threads/{thread_id}"
    assert client.patch(f"{path}/sources/{source['id']}", json={"selected": False}).status_code == 200
    request = {
        "thread_id": thread_id, "student_message": "Explain this concept",
        "current_stage": "problem_identification", "response_detail": "short",
        "interaction_intent": "lecture_help",
    }
    reply = client.post("/api/v1/coach/turn", json=request)
    assert reply.status_code == 200
    assert "SECRET_EVIDENCE_791" not in str(reply.json())
    assert reply.json()["assessment"]["citations"] == []
    assert client.post("/api/v1/coach/turn", json={**request, "interaction_intent": "review"}).status_code == 422


def test_shared_lecture_catalog_is_available_without_personal_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lecture entry retrieves shared notes and opens the exact cited PDF."""
    import fitz
    from backend.settings import settings
    from backend.source_library import sync_lecture_notes_folder

    folder = tmp_path / "course" / "lectureNotes"
    folder.mkdir(parents=True)
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Analogy transfers a familiar relationship to a new design problem.")
    document.save(folder / "Analogy.pdf")
    document.close()
    monkeypatch.setattr(settings, "lecture_notes_dir", folder.parent)
    monkeypatch.setattr(settings, "course_material_sync_enabled", True)
    monkeypatch.setattr(settings, "course_materials_bucket", "")
    store = StudentStore(tmp_path / "catalog.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    sync_lecture_notes_folder(store, thread_id)
    client = TestClient(create_app(store))
    path = f"/api/v1/threads/{thread_id}"
    assert client.get(f"{path}/sources", params={"selected_only": True}).json() == []
    reply = client.post("/api/v1/coach/turn", json={
        "thread_id": thread_id, "student_message": "Explain analogy",
        "current_stage": "problem_identification", "response_detail": "short",
        "interaction_intent": "lecture_help",
    })
    assert reply.status_code == 200
    turn = reply.json()
    assert "Analogy transfers" in turn["response_text"]
    citation = turn["assessment"]["citations"][0]
    source = client.get(f"{path}/sources/{citation['source_id']}")
    assert source.status_code == 200
    assert source.json()["title"] == "Analogy.pdf"
    assert "Analogy transfers" in source.json()["extractedText"]
    content = client.get(f"{path}/sources/{citation['source_id']}/content")
    assert content.status_code == 200
    assert content.content == (folder / "Analogy.pdf").read_bytes()


def test_revising_a_lecture_question_keeps_lecture_intent(tmp_path: Path) -> None:
    """Editing lecture history cannot silently turn it into project assessment."""
    store = StudentStore(tmp_path / "revise.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, thread_id, "Analogy", "Analogy transfers relationships between designs.")
    client = TestClient(create_app(store))
    path = f"/api/v1/threads/{thread_id}"
    original = client.post("/api/v1/coach/turn", json={
        "thread_id": thread_id, "student_message": "Explain analogy",
        "current_stage": "problem_identification", "response_detail": "short",
        "interaction_intent": "lecture_help", "idempotency_key": "original-lecture",
    })
    assert original.status_code == 200
    user = client.get(f"{path}/messages").json()[0]
    reply = client.post(f"{path}/messages/{user['id']}/revise", json={
        "content": "I think analogy is confusing. Help me understand analogy.",
        "idempotency_key": "edited-lecture",
    })
    assert reply.status_code == 200
    assert reply.json()["assessment"]["response_mode"] == "qa"
    assert reply.json()["assessment"]["recommendation"] is None
    assert client.get(f"{path}/phase-transitions/pending").json() is None
