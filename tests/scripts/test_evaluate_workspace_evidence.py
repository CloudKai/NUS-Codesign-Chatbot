"""Workspace-evidence retrieval evaluation: corpus validity and metric contracts.

Offline only. Reads the new labelled corpus, the materials manifest and the
lecture PDFs in the repo. No Bedrock, Knowledge Base or paid calls; the
retriever is the local lexical stand-in.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "scripts" / "evals" / "datasets"
CORPUS_PATH = DATA_DIR / "workspace_evidence.synthetic.jsonl"
MATERIALS_PATH = DATA_DIR / "course_materials.json"

SCOPE_VOCABULARY = {"course", "student_upload", "both", "none"}
DECISION_VOCABULARY = {"retrieve", "skip"}
EVIDENCE_SOURCE_VOCABULARY = {"course", "student_upload", "workspace_context", "both", "none"}
CATEGORIES = {
    "explicit_lecture_question",
    "implicit_lecture_question",
    "selected_material_question",
    "project_coaching",
    "ambiguous_followup",
    "selected_upload",
    "canvas_artifact",
}
REQUIRED_CATEGORIES = CATEGORIES


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text)
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", value).strip().casefold()


def _rows() -> list[dict]:
    return [
        json.loads(line)
        for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _materials() -> dict[str, dict]:
    items = json.loads(MATERIALS_PATH.read_text(encoding="utf-8"))
    return {item["material_id"]: item for item in items}


def test_corpus_covers_all_extended_categories() -> None:
    rows = _rows()
    assert len(rows) >= 20
    assert {row["category"] for row in rows} == REQUIRED_CATEGORIES
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        assert row["synthetic"] is True, row["id"]
        assert row["expected_decision"] in DECISION_VOCABULARY, row["id"]
        assert row["expected_scope"] in SCOPE_VOCABULARY, row["id"]
        assert row["evidence_source"] in EVIDENCE_SOURCE_VOCABULARY, row["id"]
        assert row["certainty"] in {"clear", "borderline"}, row["id"]
        assert row["category"] in CATEGORIES, row["id"]
        # Labels are coherent with each other.
        if row["expected_decision"] == "skip":
            assert row["expected_scope"] == "none", row["id"]
        if row["evidence_source"] in {"course", "both"}:
            assert row["expected_material"] and row["expected_pages"], row["id"]
        else:
            assert row["expected_material"] is None and not row["evidence"], row["id"]


def test_evidence_text_is_on_the_tagged_pages() -> None:
    """Every course-evidence location must contain its verbatim snippet."""
    fitz = pytest.importorskip("fitz")
    materials = _materials()
    for row in _rows():
        if row["evidence_source"] != "course":
            continue
        expected = _normalize(row["evidence"])
        assert expected, row["id"]
        locations = [(row["expected_material"], row["expected_pages"])] + [
            (alt["material"], alt["pages"]) for alt in row["alt_expected"]
        ]
        for material_id, pages in locations:
            assert material_id in materials, (row["id"], material_id)
            total = materials[material_id]["pdf_pages"]
            assert all(1 <= page <= total for page in pages), row["id"]
            document = fitz.open(ROOT / materials[material_id]["local_path"])
            try:
                page_texts = {
                    index + 1: _normalize(document[index].get_text())
                    for index in range(len(document))
                }
            finally:
                document.close()
            assert any(expected in page_texts[page] for page in pages), row["id"]


def test_report_measures_precision_recall_mrr_and_filters() -> None:
    report = bench_report()
    retrieval = report["retrieval"]
    for key in (
        "precision_at_4",
        "recall_at_4",
        "mrr",
        "citation_correct_rate",
        "filter_correct_rate",
        "latency_ms",
    ):
        assert key in retrieval
    assert retrieval["recall_at_4"]["hits"] >= 0
    assert 0.0 <= retrieval["mrr"]["value"] <= 1.0
    # Authorization: no hit may fall outside the row's authorized materials.
    assert retrieval["unauthorized_hit_rows"] == []


def test_gate_agreement_is_reported_with_and_without_borderline_rows() -> None:
    report = bench_report()
    gate = report["gate"]
    assert gate["total"] >= 20
    assert set(gate) >= {"agreement", "agreement_clear_only", "disagreements"}
    assert gate["agreement_clear_only"]["total"] <= gate["total"]


def test_evidence_gaps_are_recorded_honestly() -> None:
    report = bench_report()
    gaps = report["evidence_gaps"]
    # Upload questions have no course corpus evidence offline; the harness must
    # record the gap, not credit a course hit.
    assert gaps["student_upload_expected_gap_rows"] >= 1
    assert set(gaps) >= {"student_upload_expected_gap_rows", "course_miss_rows"}


def test_authorized_rows_keep_hits_inside_the_selected_set() -> None:
    report = bench_report()
    authorized = report["retrieval"]["authorized_rows"]
    assert len(authorized) >= 2
    for row in authorized:
        assert row["hits_within_authorized"] is True
        assert row["authorized_materials"]


def test_no_bedrock_or_kb_call_is_possible(monkeypatch) -> None:
    def _fail(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("Bedrock client built during offline evaluation")

    monkeypatch.setattr("boto3.client", _fail, raising=False)
    monkeypatch.setattr("boto3.Session", _fail, raising=False)
    bench_report()


def bench_report() -> dict:
    from scripts.evals import evaluate_workspace_evidence as bench

    return bench.build_report()


def test_cli_refuses_live_and_writes_json(tmp_path) -> None:
    from scripts.evals import evaluate_workspace_evidence as bench

    assert bench.main(["--i-approve-live-aws"]) == 2
    output = tmp_path / "report.json"
    assert bench.main(["--json-output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run"]["generated_at_utc"].endswith("Z")
    assert payload["measurement_kind"] == "offline-simulation"
