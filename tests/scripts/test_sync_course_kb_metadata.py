"""Dry-run sidecar generator and local verification tests. No AWS."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    """Load a scripts/*.py module without requiring a scripts package."""
    path = _ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SYNC = _load("co_design_sync_course_kb_metadata", "sync_course_kb_metadata.py")
_CHECK = _load(
    "co_design_check_course_kb_metadata",
    "diagnostics/check_course_kb_metadata.py",
)


def _lecture_tree(tmp_path: Path) -> Path:
    """Create one approved lecture PDF and an ignored sidecar sibling."""
    root = tmp_path / "lecture_notes"
    folder = root / "lectureNotes"
    folder.mkdir(parents=True)
    source = folder / "Week 1 Introduction to innovation v3.pdf"
    source.write_bytes(b"%PDF-1.4 test")
    (folder / "Week 1 Introduction to innovation v3.pdf.metadata.json").write_text(
        "{}",
        encoding="utf-8",
    )
    (folder / "README.txt").write_text("skip", encoding="utf-8")
    return root


def test_planned_sidecars_ignore_metadata_files_and_are_idempotent(tmp_path: Path) -> None:
    root = _lecture_tree(tmp_path)
    first = _SYNC.planned_sidecars(root, "course/")
    second = _SYNC.planned_sidecars(root, "course/")
    assert first == second
    assert len(first) == 1
    _path, object_key, sidecar_key = first[0]
    assert object_key.endswith(".pdf")
    assert sidecar_key.endswith(".pdf.metadata.json")
    assert not object_key.endswith(".metadata.json")


def test_write_local_sidecar_bytes_are_idempotent(tmp_path: Path) -> None:
    root = _lecture_tree(tmp_path)
    from backend.sources.kb_metadata import sidecar_json_bytes

    planned = _SYNC.planned_sidecars(root, "course/")
    path, object_key, _sidecar_key = planned[0]
    sidecar = Path(f"{path}.metadata.json")
    sidecar.write_bytes(sidecar_json_bytes(object_key))
    first = sidecar.read_bytes()
    sidecar.write_bytes(sidecar_json_bytes(object_key))
    assert sidecar.read_bytes() == first
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["metadataAttributes"]["course_material_id"]["includeForEmbedding"] is False


def test_dry_run_without_confirm_refuses_upload(tmp_path: Path, monkeypatch) -> None:
    root = _lecture_tree(tmp_path)
    monkeypatch.setattr(_SYNC.settings, "lecture_notes_dir", root)
    assert _SYNC.main([]) == 2


def test_local_sidecar_report_detects_mismatch(tmp_path: Path) -> None:
    root = _lecture_tree(tmp_path)
    rows = _CHECK.local_sidecar_report(root, "course/")
    assert len(rows) == 1
    assert rows[0]["sidecar_present"] is True
    assert rows[0]["sidecar_matches"] is False
    from backend.sources.kb_metadata import sidecar_json_bytes

    path, object_key, _sidecar = _SYNC.planned_sidecars(root, "course/")[0]
    Path(f"{path}.metadata.json").write_bytes(sidecar_json_bytes(object_key))
    matched = _CHECK.local_sidecar_report(root, "course/")
    assert matched[0]["sidecar_matches"] is True
    assert matched[0]["canonical_bytes_match"] is True


def test_check_course_kb_metadata_dry_run_answers_local_questions(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = _lecture_tree(tmp_path)
    monkeypatch.setattr(_CHECK.settings, "lecture_notes_dir", root)
    code = _CHECK.main(["--dry-run"])
    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["count"] == 1
    assert payload["sidecar_missing_count"] == 0
    assert payload["sidecar_mismatch_count"] == 1
    assert payload["local_sidecar_ok"] is False
    assert payload["kb_ingestion"]["status"] == "not_executed"
    assert payload["filtered_retrieve"]["status"] == "not_executed"
    assert "metadata_filter_mode" in payload["filtered_retrieve"]
    assert payload["canonical_id_function"] == (
        "backend.retrieval.course_material_id_from_object_key"
    )
    assert "AKIA" not in captured.out


def test_live_bedrock_flag_is_refused_without_operator_tooling() -> None:
    assert _CHECK.main(["--i-approve-live-bedrock"]) == 2
