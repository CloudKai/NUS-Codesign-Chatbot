from __future__ import annotations

import pytest

from backend.domain import CoachRequest, StageDecision, TransitionStatus
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.student_journey import THINKING_STAGES, normalize_journey, selectable_stage_ids
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def _learning_service(store: StudentStore) -> LearningProgressService:
    return LearningProgressService(
        store,
        SQLiteNotebookRepository(store),
        SQLitePhaseTransitionRepository(store),
    )


def test_confirmed_recommendation_is_the_only_way_to_advance(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    workflow = CoachWorkflow(DeterministicCoachProvider(StageDecision.ADVANCE), transitions)
    request = CoachRequest(
        thread_id=thread_id,
        student_message=(
            "How might we improve road crossings for older pedestrians so that "
            "they can cross safely without rushing?"
        ),
        current_stage="problem_identification",
        response_detail="short",
    )
    pending = workflow.run(request).pending_transition
    assert pending is not None
    pending = transitions.create(pending)

    service = LearningProgressService(store, notebooks, transitions)
    assert service.get_pending(thread_id) == pending
    resolved = service.resolve(thread_id, pending.id, accepted=True)

    assert resolved.status is TransitionStatus.CONFIRMED
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "concept_generation"
    assert thread["metadata"]["learning_journey"]["completed_stages"] == ["problem_identification"]


def test_rejected_recommendation_keeps_current_stage(tmp_path):
    store = StudentStore(tmp_path / "coach.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    pending = transitions.create(pending)

    resolved = LearningProgressService(store, notebooks, transitions).resolve(
        thread_id, pending.id, accepted=False
    )

    assert resolved.status is TransitionStatus.REJECTED
    thread = store.get_thread(thread_id) or {}
    assert (thread.get("metadata") or {}).get("thinking_stage", "problem_identification") == "problem_identification"
    journey = (thread.get("metadata") or {}).get("learning_journey") or {}
    assert journey.get("current_stage", "problem_identification") == "problem_identification"
    assert journey.get("completed_stages") in (None, [])


def test_accepted_transition_rolls_back_when_journey_write_fails(tmp_path, monkeypatch):
    import backend.student_store as student_store_module

    store = StudentStore(tmp_path / "atomic.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    pending = transitions.create(pending)

    real_dump = student_store_module._dump

    def flaky_dump(value):
        # Progress blob written on accepted transition contains completed_stages.
        if isinstance(value, dict) and "completed_stages" in value:
            raise RuntimeError("simulated journey write failure")
        return real_dump(value)

    monkeypatch.setattr(student_store_module, "_dump", flaky_dump)

    service = LearningProgressService(store, notebooks, transitions)
    try:
        service.resolve(thread_id, pending.id, accepted=True)
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    assert transitions.get_pending(thread_id) is not None
    thread = store.get_thread(thread_id) or {}
    journey = (thread.get("metadata") or {}).get("learning_journey") or {}
    assert journey.get("current_stage", "problem_identification") == "problem_identification"


def test_select_stage_requires_flag(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-off.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", False)
    service = _learning_service(store)

    with pytest.raises(ValueError, match="not enabled"):
        service.select_stage(thread_id, "concept_generation")


def test_select_stage_rejects_unknown_stage(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-bad.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _learning_service(store)

    with pytest.raises(ValueError, match="Unknown thinking stage"):
        service.select_stage(thread_id, "not-a-stage")


@pytest.mark.parametrize(
    "stage_id",
    (
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
        "reflection",
    ),
)
def test_select_stage_updates_journey_without_completing_skipped(
    tmp_path, monkeypatch, stage_id
):
    store = StudentStore(tmp_path / f"select-{stage_id}.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _learning_service(store)

    target_index = next(
        index for index, stage in enumerate(THINKING_STAGES) if stage.id == stage_id
    )
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata.get("learning_journey") or {})
    journey["completed_stages"] = [
        stage.id for stage in THINKING_STAGES[:target_index]
    ]
    metadata["learning_journey"] = journey
    metadata["thinking_stage"] = "problem_identification"
    store.update_thread(thread_id, metadata=metadata)
    metadata = service.select_stage(thread_id, stage_id)

    journey = metadata["learning_journey"]
    assert journey["current_stage"] == stage_id
    assert journey.get("completed_stages") == [
        stage.id for stage in THINKING_STAGES[:target_index]
    ]
    assert metadata["thinking_stage"] == stage_id
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == stage_id


def test_select_stage_rejects_pending_transition(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "select-pending.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE), transitions
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    transitions.create(pending)
    assert transitions.get_pending(thread_id) is not None

    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = LearningProgressService(store, notebooks, transitions)
    with pytest.raises(ValueError, match="locked"):
        service.select_stage(thread_id, "deep_analysis")

    assert transitions.get_pending(thread_id) is not None
    thread = store.get_thread(thread_id) or {}
    assert thread["metadata"]["thinking_stage"] == "problem_identification"
    assert thread["metadata"]["learning_journey"]["completed_stages"] == []


def test_revisit_keeps_completed_frontier_and_valid_selection_rejects_pending(
    tmp_path, monkeypatch
):
    """A completed-phase revisit survives reload and clears pending atomically."""
    store = StudentStore(tmp_path / "select-revisit.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    journey = dict(metadata["learning_journey"])
    journey["current_stage"] = "design_specification"
    journey["completed_stages"] = ["problem_identification", "concept_generation"]
    metadata["learning_journey"] = journey
    metadata["thinking_stage"] = "design_specification"
    store.update_thread(thread_id, metadata=metadata)
    monkeypatch.setattr(settings, "student_stage_selection", True)
    service = _learning_service(store)

    selected = service.select_stage(thread_id, "problem_identification")
    reloaded = store.get_thread(thread_id) or {}
    persisted = normalize_journey((reloaded["metadata"] or {})["learning_journey"])
    assert selected["learning_journey"]["current_stage"] == "problem_identification"
    assert persisted["current_stage"] == "problem_identification"
    assert persisted["completed_stages"] == [
        "problem_identification",
        "concept_generation",
    ]
    assert selectable_stage_ids(persisted) == (
        "problem_identification",
        "concept_generation",
        "design_specification",
    )

    pending = CoachWorkflow(
        DeterministicCoachProvider(StageDecision.ADVANCE),
        SQLitePhaseTransitionRepository(store),
    ).run(
        CoachRequest(
            thread_id=thread_id,
            student_message=(
                "How might we improve road crossings for older pedestrians so that "
                "they can cross safely without rushing?"
            ),
            current_stage="problem_identification",
            response_detail="short",
        )
    ).pending_transition
    assert pending is not None
    SQLitePhaseTransitionRepository(store).create(pending)
    service.select_stage(thread_id, "concept_generation")
    assert SQLitePhaseTransitionRepository(store).get_pending(thread_id) is None
