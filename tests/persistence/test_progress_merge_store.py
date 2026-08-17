"""Store-level confirmation merge must keep progress when the patch omits it."""

from __future__ import annotations

from backend.student_store import StudentStore

_PRIOR = {
    "learning_summary": "previous summary",
    "working_conclusion": "previous conclusion",
    "understanding_change": "previous change",
    "critical_understanding": "Developing",
}


def test_structural_only_transition_patch_preserves_progress(tmp_path) -> None:
    """An ADVANCE patch with only journey keys must not blank stored progress.

    ``apply_phase_transition_decision`` merges the patch over current metadata.
    LearningProgressService omits empty progress fields, so a structural-only
    patch is the store-level shape of a slim Fast Chat confirmation.
    """
    store = StudentStore(tmp_path / "transition-progress.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.update_thread(thread_id, metadata=dict(_PRIOR))
    created = store.create_phase_transition(
        {
            "thread_id": thread_id,
            "from_stage": "problem_identification",
            "to_stage": "concept_generation",
            "assessment": {
                "current_stage": "problem_identification",
                "recommendation": "advance",
                "learning_summary": "",
                "working_conclusion": "",
                "understanding_change": "",
                "critical_understanding_level": "",
            },
        }
    )

    store.apply_phase_transition_decision(
        thread_id,
        created["id"],
        accepted=True,
        metadata_patch={
            "learning_journey": {
                "current_stage": "concept_generation",
                "completed_stages": ["problem_identification"],
                "stage_notes": {"problem_identification": "Done"},
                "response_detail": "short",
            },
            "thinking_stage": "concept_generation",
        },
        expected_from_stage="problem_identification",
    )

    metadata = dict((store.get_thread(thread_id) or {}).get("metadata") or {})
    assert metadata["thinking_stage"] == "concept_generation"
    assert metadata["learning_summary"] == _PRIOR["learning_summary"]
    assert metadata["working_conclusion"] == _PRIOR["working_conclusion"]
    assert metadata["understanding_change"] == _PRIOR["understanding_change"]
    assert metadata["critical_understanding"] == _PRIOR["critical_understanding"]
