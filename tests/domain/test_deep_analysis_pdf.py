"""Unit tests for Sonnet Deep Analysis PDF export."""

from __future__ import annotations

import fitz

from backend.learning.deep_analysis_pdf import (
    build_deep_analysis_pdf,
    deep_analysis_pdf_filename,
)
from backend.learning.stages import THINKING_STAGES
from backend.specialists.review_orchestration import deep_review_snapshot_payload
from backend.student_store import StudentStore
from backend.workspace_service import WorkspaceService


def test_deep_analysis_pdf_filename_sanitizes_title() -> None:
    assert deep_analysis_pdf_filename("My Notebook!") == "My_Notebook-deep-analysis.pdf"


def test_build_deep_analysis_pdf_includes_snapshot_sections() -> None:
    snapshot = deep_review_snapshot_payload(
        conversation_revision=2,
        created_at="2026-08-28T00:00:00+00:00",
        synthesis="Students framed the night-crossing risk clearly.",
        summary="Students framed the night-crossing risk clearly.",
        strengths=["Named the primary users."],
        areas_to_develop=["Make the timing constraint explicit."],
        facione_scores={"analysis": 3, "interpretation": 2},
        working_conclusion="Night crossings remain the core risk.",
        readiness_candidate=False,
        readiness_evidence=[],
        missing_requirements=[],
        model_id="global.anthropic.claude-sonnet-4-6",
        reviewed_stage_id="reflection",
    )
    export = build_deep_analysis_pdf(
        title="Crossing Studio",
        snapshot=snapshot,
        journey={
            "completed_stages": [stage.id for stage in THINKING_STAGES],
        },
    )
    assert export.filename == "Crossing_Studio-deep-analysis.pdf"
    assert export.mime == "application/pdf"
    assert export.data.startswith(b"%PDF")
    with fitz.open(stream=export.data, filetype="pdf") as doc:
        text = "\n".join(page.get_text() for page in doc)
    assert "Deep Analysis" in text
    assert "Crossing Studio" in text
    assert "Night crossings remain the core risk." in text
    assert "Named the primary users." in text
    assert "Make the timing constraint explicit." in text
    assert "Analysis: 3/4" in text


def test_workspace_export_deep_analysis_pdf_requires_snapshot(tmp_path) -> None:
    store = StudentStore(tmp_path / "deep-analysis-pdf.sqlite3")
    service = WorkspaceService(store)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    try:
        service.export_deep_analysis_pdf(thread_id)
        raise AssertionError("expected missing snapshot to fail")
    except ValueError as error:
        assert "not ready" in str(error).casefold()

    store.update_thread(
        thread_id,
        metadata={
            "deep_review_snapshot": deep_review_snapshot_payload(
                conversation_revision=1,
                created_at="2026-08-28T00:00:00+00:00",
                synthesis="Summary body.",
                summary="Summary body.",
                strengths=["Clear problem framing."],
                areas_to_develop=["Sharpen the outcome."],
                facione_scores={"analysis": 2},
                working_conclusion="Keep the night focus.",
                readiness_candidate=False,
                readiness_evidence=[],
                missing_requirements=[],
                model_id="sonnet",
                reviewed_stage_id="reflection",
            )
        },
    )
    export = service.export_deep_analysis_pdf(thread_id)
    assert export.data.startswith(b"%PDF")
