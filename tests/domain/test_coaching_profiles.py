"""Domain regression contracts for student-facing Quick and Strict profiles."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from backend.application import CoachApplicationService
from backend.domain import CoachRequest, StageDecision
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.settings import settings
from backend.student_journey import default_journey, learning_review, normalize_journey
from backend.student_store import CoachingStyleConflictError, StudentStore
from backend.workflow import CoachWorkflow
from ui.components import facione_scores_table_html
from ui.profile import COACHING_STYLE_LABELS, COACHING_STYLE_VALUES


def _legacy_assessed_messages() -> list[dict]:
    """Return untagged assessments written before profile-aware scoring."""
    return [
        {
            "role": "assistant",
            "content": "Earlier assessment.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Earlier progress.",
                    "facione_scores": {"analysis": 3, "evaluation": 1},
                }
            },
        },
        {
            "role": "assistant",
            "content": "Later assessment.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Later progress.",
                    "facione_scores": {"analysis": 1, "evaluation": 2},
                }
            },
        },
    ]


def test_profile_labels_preserve_existing_short_long_storage_contract() -> None:
    """Quick/Strict are presentation labels, not new persisted enum values."""
    assert COACHING_STYLE_LABELS == {"short": "Quick", "long": "Strict"}
    assert COACHING_STYLE_VALUES == {"Quick": "short", "Strict": "long"}
    assert normalize_journey({})["response_detail"] == "short"
    assert normalize_journey({"response_detail": "long"})["response_detail"] == "long"
    assert normalize_journey({"response_detail": "legacy-invalid"})[
        "response_detail"
    ] == "short"


def test_profile_toggle_preserves_learning_and_conversation_state() -> None:
    """Selecting Strict snapshots scores without changing stage or history."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = app.session_state["thread_id"]
    store = StudentStore()
    before_thread = store.get_thread(thread_id)
    assert before_thread is not None
    before_messages = store.get_messages(thread_id)
    before_revision = int(before_thread.get("conversation_revision") or 0)
    before_journey = normalize_journey(before_thread["metadata"]["learning_journey"])

    control = next(
        item
        for item in app.segmented_control
        if item.label == "Coaching style"
    )
    assert control.options == ["Quick", "Strict"]
    assert control.value == "Quick"
    control.set_value("Strict").run()

    after_thread = store.get_thread(thread_id)
    assert after_thread is not None
    after_journey = normalize_journey(after_thread["metadata"]["learning_journey"])
    assert after_journey["response_detail"] == "long"
    assert after_journey["strict_facione_baseline"] == {
        "scores": {
            "analysis": 0,
            "interpretation": 0,
            "inference": 0,
            "evaluation": 0,
            "explanation": 0,
            "self_regulation": 0,
        },
        "captured_through": None,
    }
    assert after_journey["current_stage"] == before_journey["current_stage"]
    assert after_journey["completed_stages"] == before_journey["completed_stages"]
    assert int(after_thread.get("conversation_revision") or 0) == before_revision
    assert store.get_messages(thread_id) == before_messages


def test_legacy_facione_evidence_seeds_both_profiles() -> None:
    """Untagged historical assessments remain visible in Quick and Strict."""
    messages = _legacy_assessed_messages()
    journey = default_journey()

    quick = learning_review(messages, journey, detail="short")
    strict = learning_review(messages, journey, detail="long")
    assert quick["facione_scores"] == strict["facione_scores"] == {
        "analysis": 3,
        "interpretation": 0,
        "inference": 0,
        "evaluation": 2,
        "explanation": 0,
        "self_regulation": 0,
    }

    quick_html = facione_scores_table_html(
        quick["facione_scores"], coaching_style="short"
    )
    strict_html = facione_scores_table_html(
        strict["facione_scores"], coaching_style="long"
    )
    quick_table = quick_html.split('<p class="facione-note">', 1)[0]
    strict_table = strict_html.split('<p class="facione-note">', 1)[0]
    assert quick_table == strict_table
    assert "under the Quick profile" in quick_html
    assert "Existing progress is retained" in strict_html
    assert "higher Strict threshold" in strict_html


def test_tagged_scores_are_isolated_with_legacy_flat_strict_baseline() -> None:
    """The legacy flat baseline remains compatible while profiles stay isolated."""
    messages = [
        {
            "role": "assistant",
            "content": "Legacy evidence.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 2, "evaluation": 1},
                }
            },
        },
        {
            "role": "assistant",
            "content": "Later Quick evidence.",
            "metadata": {
                "coaching_profile": "quick",
                "assessment": {
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 4, "evaluation": 3},
                },
            },
        },
        {
            "role": "assistant",
            "content": "Strict evidence.",
            "metadata": {
                "coaching_profile": "strict",
                "assessment": {
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 1, "inference": 3},
                },
            },
        },
    ]
    journey = {
        **default_journey(),
        "strict_facione_baseline": {
            "analysis": 2,
            "interpretation": 0,
            "inference": 0,
            "evaluation": 1,
            "explanation": 0,
            "self_regulation": 0,
        },
    }

    quick = learning_review(messages, journey, detail="short")["facione_scores"]
    strict = learning_review(messages, journey, detail="long")["facione_scores"]

    assert quick["analysis"] == 4
    assert quick["evaluation"] == 3
    assert quick["inference"] == 0
    assert strict["analysis"] == 2
    assert strict["evaluation"] == 1
    assert strict["inference"] == 3


def test_inflight_quick_turn_cannot_commit_after_strict_switch(
    tmp_path, monkeypatch
) -> None:
    """A stale Quick result cannot recreate Next after Strict rejects pending work."""
    monkeypatch.setattr(settings, "student_stage_selection", False)
    store = StudentStore(tmp_path / "profile-race.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")

    class SwitchToStrictProvider:
        """Switch profile while one deterministic Quick turn is in flight."""

        def assess(self, request):
            store.update_thread(thread_id, metadata={"response_detail": "long"})
            return DeterministicCoachProvider(StageDecision.ADVANCE).assess(request)

    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(SwitchToStrictProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=False,
    )

    with pytest.raises(CoachingStyleConflictError, match="coaching style changed"):
        service.submit(
            CoachRequest(
                thread_id=thread_id,
                student_message="A clear Quick-mode focus.",
                current_stage="focus",
                response_detail="short",
            )
        )

    thread = store.get_thread(thread_id)
    assert thread is not None
    assert thread["metadata"]["learning_journey"]["response_detail"] == "long"
    assert store.get_messages(thread_id) == []
    assert store.get_pending_phase_transition(thread_id) is None


def test_superseded_quick_evidence_is_removed_from_strict_inheritance(tmp_path) -> None:
    """Editing away baseline evidence removes it from active Strict Review."""
    store = StudentStore(tmp_path / "profile-revision.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    user_id = store.add_message(thread_id, "user", "Original claim")
    assistant_id = store.add_message(
        thread_id,
        "assistant",
        "Quick assessment",
        metadata={
            "coaching_profile": "quick",
            "assessment": {
                "recommendation": "stay",
                "facione_scores": {"analysis": 4},
            },
        },
    )
    store.update_thread(thread_id, metadata={"response_detail": "long"})
    before = store.get_thread(thread_id)
    assert before is not None
    assert learning_review(
        store.get_messages(thread_id),
        before["metadata"]["learning_journey"],
        detail="long",
    )["facione_scores"]["analysis"] == 4

    store.revise_user_message(
        thread_id,
        user_id,
        "Replacement claim",
        model_id="mock",
        metadata={},
    )

    after = store.get_thread(thread_id)
    assert after is not None
    assert learning_review(
        store.get_messages(thread_id),
        after["metadata"]["learning_journey"],
        detail="long",
    )["facione_scores"]["analysis"] == 0
    assert any(
        message["id"] == assistant_id
        for message in store.get_messages_at_revision(thread_id, 0)
    )
