"""Regression tests for additive research persistence and audit records."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.persistence.dsql_student_store import _OCC_WRITE_METHODS
from backend.research.models import (
    ResearchAccessEventCreate,
    ResearchAdjudicationCreate,
    ResearchEvidenceSpan,
    ResearchObservationCreate,
    ResearchReviewCreate,
)
from backend.research.repository import StudentStoreResearchRepository
from backend.student_store import (
    RESEARCH_WORKFLOW_CONTRACT_KEY,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    StudentStore,
)
from backend.student_journey import DEFAULT_STAGE


def _observation(stage: str) -> ResearchObservationCreate:
    return ResearchObservationCreate(
        coding_status="coded",
        coding_version="research-coding-v1",
        prompt_version="prompt-v1",
        provider="mock",
        model_id="mock-research",
        coaching_profile="quick",
        phase_id=stage,
        dominant_clear="concise",
        facione_behaviors=["interpretation"],
        ethics_concepts=["responsibility"],
        evidence=[
            ResearchEvidenceSpan(
                start_offset=0,
                end_offset=8,
                rationale="The opening claim supplies the coded evidence.",
                confidence=0.8,
            )
        ],
        holistic_candidate={
            "score": 2,
            "rationale": "The response revisits its initial framing.",
            "evidence_spans": [{"start_offset": 0, "end_offset": 8}],
        },
    )


def _persist_observed_turn(store: StudentStore, thread_id: str) -> tuple[str, str]:
    thread = store.get_thread(thread_id) or {}
    stage = str((thread.get("metadata") or {}).get("thinking_stage"))
    return store.persist_coach_turn(
        thread_id,
        expected_stage=stage,
        expected_conversation_revision=0,
        user_content="Evidence from the crossing study supports this claim.",
        user_metadata={"thinking_stage": stage},
        assistant_content="Consider how representative that study is.",
        assistant_metadata={},
        summary_metadata={},
        research_observation=_observation(stage),
    )


def test_atomic_observation_is_attributed_offset_only_and_revision_aware(tmp_path):
    database = tmp_path / "research.sqlite3"
    store = StudentStore(database, identifier="student-research")
    with store._connect() as connection:
        connection.execute(
            "UPDATE users SET display_name=?, email=? WHERE id=?",
            ("Research Student", "student@example.edu", store.owner_id),
        )
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    user_id, assistant_id = _persist_observed_turn(store, thread_id)

    repository = StudentStoreResearchRepository(store)
    observations = repository.list_observations()
    assert len(observations) == 1
    observation = observations[0]
    assert observation.student_user_id == store.owner_id
    assert observation.student_display_name == "Research Student"
    assert observation.student_email == "student@example.edu"
    assert observation.user_message_id == user_id
    assert observation.assistant_message_id == assistant_id
    assert observation.evidence[0].start_offset == 0
    assert not hasattr(observation.evidence[0], "quote")

    assistant = store.get_messages(thread_id)[1]
    embedded = assistant["metadata"]["research_coding"]
    assert embedded["dominant_clear"] == "concise"
    assert "quote" not in json.dumps(embedded).lower()

    restarted = StudentStore(database, identifier="student-research")
    assert len(StudentStoreResearchRepository(restarted).list_observations()) == 1
    restarted.revise_conversation_from_user_message(
        thread_id,
        user_id,
        "Revised claim without the old evidence.",
        model_id="mock",
    )
    restarted_repository = StudentStoreResearchRepository(restarted)
    assert restarted_repository.list_observations(active_only=True) == []
    assert len(restarted_repository.list_observations(active_only=False)) == 1
    assert restarted_repository.get_observation(observation.id) is None
    assert restarted_repository.get_observation(
        observation.id, active_only=False
    ) is not None


def test_observation_rolls_back_with_the_coach_turn(tmp_path, monkeypatch):
    store = StudentStore(tmp_path / "atomic.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")

    def fail_summary(_metadata):
        raise RuntimeError("injected summary failure")

    monkeypatch.setattr(store, "_split_notebook_metadata", fail_summary)
    with pytest.raises(RuntimeError, match="injected"):
        _persist_observed_turn(store, thread_id)

    with store._connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE notebook_id=?", (thread_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM research_observations WHERE notebook_id=?",
            (thread_id,),
        ).fetchone()[0] == 0


def test_append_only_review_adjudication_audit_and_notebook_delete(tmp_path):
    store = StudentStore(tmp_path / "decisions.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    _persist_observed_turn(store, thread_id)
    repository = StudentStoreResearchRepository(store)
    observation = repository.list_observations()[0]

    first_review = repository.append_review(
        ResearchReviewCreate(
            observation_id=observation.id,
            reviewer_user_id=store.owner_id,
            status="reviewed",
            dominant_clear="logical",
        )
    )
    second_review = repository.append_review(
        ResearchReviewCreate(
            observation_id=observation.id,
            reviewer_user_id=store.owner_id,
            status="corrected",
            ethics_concepts=["fairness"],
            supersedes_review_id=first_review.id,
        )
    )
    adjudication = repository.append_adjudication(
        ResearchAdjudicationCreate(
            observation_id=observation.id,
            adjudicator_user_id=store.owner_id,
            decision="accepted",
            referenced_review_ids=[first_review.id, second_review.id],
        )
    )
    event = repository.record_access_event(
        ResearchAccessEventCreate(
            actor_user_id=store.owner_id,
            action="read",
            scope="notebook_detail",
            request_id="request-1",
            target_user_id=store.owner_id,
            target_count=1,
            notebook_id=thread_id,
            observation_id=observation.id,
            filters={"active_only": True},
        )
    )

    assert [item.id for item in repository.list_reviews(observation.id)] == [
        first_review.id,
        second_review.id,
    ]
    assert repository.list_adjudications(observation.id)[0].id == adjudication.id
    assert event.request_id == "request-1"
    with pytest.raises(ValueError, match="actor not found"):
        repository.record_access_event(
            ResearchAccessEventCreate(
                actor_user_id="missing-user",
                action="read",
                scope="queue",
                request_id="request-missing-actor",
            )
        )

    store.delete_thread(thread_id)
    with store._connect() as connection:
        for table in (
            "research_adjudications",
            "research_reviews",
            "research_access_events",
            "research_observations",
            "messages",
            "sources",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_research_json_rejects_transcript_copies_and_unbounded_audit_metadata():
    with pytest.raises(ValidationError, match="offsets, not quotes"):
        ResearchObservationCreate(
            **{
                **_observation("problem_identification").model_dump(),
                "holistic_candidate": {"evidence_quotes": ["private answer"]},
            }
        )
    with pytest.raises(ValidationError, match="exceeds"):
        ResearchAccessEventCreate(
            actor_user_id="actor",
            action="export",
            scope="csv",
            request_id="request",
            metadata={"oversized": "x" * 9_000},
        )


def test_workflow_contract_marker_is_safe_for_existing_nonempty_databases(tmp_path):
    database = tmp_path / "contract.sqlite3"
    store = StudentStore(database)
    assert store.research_workflow_contract_ready()
    store.ping()
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    with store._connect() as connection:
        connection.execute(
            "DELETE FROM system_metadata WHERE key=?",
            (RESEARCH_WORKFLOW_CONTRACT_KEY,),
        )

    reopened = StudentStore(database)
    assert reopened.get_thread(thread_id) is not None
    assert not reopened.research_workflow_contract_ready()
    with pytest.raises(RuntimeError, match="workflow contract"):
        reopened.ping()

    reopened.set_system_metadata(
        RESEARCH_WORKFLOW_CONTRACT_KEY,
        {"version": RESEARCH_WORKFLOW_CONTRACT_VERSION},
    )
    assert reopened.research_workflow_contract_ready()
    reopened.ping()


def test_fresh_notebook_and_bootstrap_schema_use_five_phase_default(tmp_path):
    store = StudentStore(tmp_path / "fresh-stage.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="guided")
    assert (store.get_thread(thread_id) or {})["metadata"][
        "thinking_stage"
    ] == DEFAULT_STAGE
    with store._connect() as connection:
        default = next(
            row["dflt_value"]
            for row in connection.execute("PRAGMA table_info(notebooks)").fetchall()
            if row["name"] == "current_stage"
        )
    assert default == "'problem_identification'"


def test_research_dsql_occ_inventory_covers_every_append_write():
    assert {
        "persist_coach_turn",
        "append_research_review",
        "append_research_adjudication",
        "record_research_access_event",
        "set_system_metadata",
    }.issubset(set(_OCC_WRITE_METHODS))
