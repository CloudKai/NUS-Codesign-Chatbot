"""Deterministic Fast Chat quality-matrix inventory. No live scores."""

from __future__ import annotations

import json
from pathlib import Path

_MATRIX = Path("tests/fixtures/fast_chat_quality_matrix.json")
_REQUIRED_IDS = (
    "A_simple_greeting",
    "B_socratic_coaching",
    "C_assumption_challenge",
    "D_vv_challenge",
    "E_stage_ready_coaching",
    "F_not_ready_coaching",
    "G_course_qa_one_source",
    "H_qa_multiple_sources",
    "I_evidence_absent",
    "J_ambiguous_question",
    "K_citation_heavy",
    "L_malicious_source_instruction",
    "M_source_contradicts_world_knowledge",
    "N_consecutive_qa",
    "O_coaching_qa_coaching",
    "P_long_conversation",
    "Q_student_upload_pdf",
    "R_course_kb_document",
    "S_image_source",
    "T_deep_review_while_chat",
)


def test_quality_matrix_lists_required_cases_without_invented_scores() -> None:
    """The matrix is an evaluation plan, not a measured quality certificate."""
    payload = json.loads(_MATRIX.read_text(encoding="utf-8"))
    assert "never invented" in str(payload.get("note") or "").lower()
    cases = payload["cases"]
    ids = [str(item["id"]) for item in cases]
    assert ids == list(_REQUIRED_IDS)
    live_cases = [item["id"] for item in cases if item.get("live_required")]
    assert "C_assumption_challenge" in live_cases
    assert "I_evidence_absent" not in live_cases
    mock_gap = next(item for item in cases if item["id"] == "I_evidence_absent")
    assert mock_gap["expected"]["agentcore_invokes"] == 0
    greeting = next(item for item in cases if item["id"] == "A_simple_greeting")
    assert greeting["expected"]["agentcore_invokes"] == 1
    assert greeting["expected"]["sonnet_invokes"] == 0
    for item in cases:
        if not item.get("mock_provable"):
            continue
        anchors = item.get("pytest_anchors") or []
        assert anchors, f"{item['id']} is mock-provable but has no pytest anchors"
        for relative in anchors:
            assert Path(relative).is_file(), f"missing pytest anchor {relative}"
