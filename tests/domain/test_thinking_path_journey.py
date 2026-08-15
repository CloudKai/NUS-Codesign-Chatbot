"""Synthetic complete Thinking Path journey with the mock provider."""

from __future__ import annotations

from backend.application import CoachApplicationService
from backend.domain import CoachRequest
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.student_journey import THINKING_STAGES, current_stage, normalize_journey
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def _build(store: StudentStore) -> tuple[CoachApplicationService, LearningProgressService]:
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    progress = LearningProgressService(store, notebooks, transitions)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        progress,
        auto_advance_stages=False,
    )
    return service, progress


def _stage_id(store: StudentStore, thread_id: str) -> str:
    thread = store.get_thread(thread_id)
    journey = normalize_journey((thread or {}).get("metadata", {}).get("learning_journey"))
    return current_stage(journey).id


def test_complete_thinking_path_two_turns_per_stage(tmp_path) -> None:
    store = StudentStore(tmp_path / "journey.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata={"response_detail": "short"})
    service, progress = _build(store)
    contributions = {
        "problem_identification": [
            "Older pedestrians wait too long at Holland Road.",
            "They can be stranded mid-crossing at night if the signal is too short.",
        ],
        "concept_generation": [
            "A raised table or a longer pedestrian interval are two different concepts.",
            "I prefer a longer interval because it keeps the existing kerb geometry.",
        ],
        "design_specification": [
            "The design must give 8 extra seconds and remain usable in rain.",
            "Success is reaching the far kerb before the signal changes.",
        ],
        "deep_analysis": [
            "A longer interval may delay drivers but reduces stranded pedestrians.",
            "Privacy is not at issue; fairness to slower walkers is the main ethics concern.",
        ],
        "reflection": [
            "I changed from a raised table to timing because evidence pointed to signal length.",
            "If I started again I would observe the crossing at night before choosing.",
        ],
    }
    seen_stages: list[str] = []
    for stage in THINKING_STAGES:
        for turn_index, message in enumerate(contributions[stage.id]):
            assert _stage_id(store, thread_id) == stage.id
            turn = service.submit(
                CoachRequest(
                    thread_id=thread_id,
                    student_message=message,
                    current_stage=stage.id,
                    response_detail="short",
                )
            )
            assert turn.assessment.current_stage == stage.id
            if stage.id == "reflection":
                assert turn.assessment.recommendation.value == "stay"
                assert turn.pending_transition is None
            elif turn_index == 1:
                assert turn.pending_transition is not None
                progress.resolve(thread_id, turn.pending_transition.id, accepted=True)
        seen_stages.append(stage.id)
    assert seen_stages == [stage.id for stage in THINKING_STAGES]
    assert _stage_id(store, thread_id) == "reflection"
    messages = store.get_messages(thread_id)
    blob = " ".join(str(item.get("content") or "") for item in messages)
    assert "Holland Road" in blob
    assert "raised table" in blob or "longer interval" in blob
    observations = store.list_research_observations(notebook_id=thread_id)
    for item in observations:
        codes = str(item)
        assert "controls_coaching" not in codes


def test_client_specialist_hint_cannot_force_qa_on_project_work(tmp_path) -> None:
    store = StudentStore(tmp_path / "hint.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service, _progress = _build(store)
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="Our elderly users may become stranded halfway across the road",
            current_stage="problem_identification",
            response_detail="short",
            specialist="qa",
        )
    )
    assert "**Problem identification**" in turn.response_text
    assert turn.assessment.recommendation.value == "stay"
    store = StudentStore(tmp_path / "qa-journey.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    service, _progress = _build(store)
    turn = service.submit(
        CoachRequest(
            thread_id=thread_id,
            student_message="What is Week 1 about?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert turn.assessment.recommendation.value == "stay"
    assert turn.pending_transition is None
    assert _stage_id(store, thread_id) == "problem_identification"
    assert "**Problem Identification**" not in turn.response_text
    assert "**Problem identification**" not in turn.response_text
    assert "validated excerpt" in turn.response_text.lower() or "Week 1" in turn.response_text
