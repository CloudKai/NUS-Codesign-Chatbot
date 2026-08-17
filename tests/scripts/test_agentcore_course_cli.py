"""Deterministic tests for operator course-sync and AgentCore smoke CLIs."""

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


_SMOKE = _load("co_design_agentcore_smoke", "agentcore_smoke.py")
_SYNC = _load("co_design_sync_course_materials", "sync_course_materials.py")
_EVAL = _load("co_design_evaluate_live_coach", "evals/evaluate_live_coach.py")
_COURSE_RETRIEVE = _load(
    "co_design_test_course_retrieval",
    "diagnostics/test_course_retrieval.py",
)
_KB_CHECK = _load(
    "co_design_check_knowledge_base_retrieve",
    "diagnostics/check_knowledge_base_retrieve.py",
)


def test_course_object_pairs_use_course_prefix_not_users(tmp_path: Path):
    root = tmp_path / "lecture_notes"
    (root / "lectureNotes").mkdir(parents=True)
    (root / "readings").mkdir()
    (root / "lectureNotes" / "week-01.txt").write_text("lecture", encoding="utf-8")
    (root / "readings" / "reading-01.txt").write_text("reading", encoding="utf-8")
    (root / "README.txt").write_text("skip", encoding="utf-8")
    pairs = _SYNC.course_object_pairs(root, "course/")
    keys = [key for _path, key in pairs]
    assert keys == [
        "course/lectureNotes/week-01.txt",
        "course/readings/reading-01.txt",
    ]
    assert all(not key.startswith("users/") for key in keys)


def test_sync_course_materials_requires_confirm():
    args = _SYNC.parse_args([])
    assert args.confirm is False


def test_agentcore_smoke_refuses_without_approval():
    args = _SMOKE.parse_args([])
    assert (
        _SMOKE.refuse_reason(args)
        == "live AgentCore smoke requires --i-approve-live-agentcore"
    )
    assert _SMOKE.main([]) == 2
    approved = _SMOKE.parse_args(
        ["--i-approve-live-agentcore", "--cost-cap", "1.00", "--max-requests", "2"]
    )
    assert "max-requests" in (_SMOKE.refuse_reason(approved) or "")


def test_live_luna_eval_refuses_without_approval():
    args = _EVAL.parse_args([])
    assert "i-approve-live-luna" in (_EVAL.refuse_reason(args) or "")
    assert _EVAL.main([]) == 2
    capped = _EVAL.parse_args(["--i-approve-live-luna", "--max-calls", "151"])
    assert "150" in (_EVAL.refuse_reason(capped) or "")


def test_course_retrieval_diagnostic_refuses_without_approval():
    args = _COURSE_RETRIEVE.parse_args([])
    assert (
        _COURSE_RETRIEVE.refuse_reason(args)
        == "live course retrieval requires --i-approve-live-bedrock"
    )
    assert _COURSE_RETRIEVE.main([]) == 2
    approved = _COURSE_RETRIEVE.parse_args(
        [
            "--i-approve-live-bedrock",
            "--query",
            "what are the week 1 contents talking about?",
            "--source",
            "Week 1 Introduction to innovation v3.pdf",
            "--dry-run",
        ]
    )
    assert _COURSE_RETRIEVE.refuse_reason(approved) is None
    assert (
        _COURSE_RETRIEVE.resolve_course_object_key(
            "Week 1 Introduction to innovation v3.pdf"
        )
        == "course/lectureNotes/Week 1 Introduction to innovation v3.pdf"
    )


def test_knowledge_base_retrieve_diagnostic_refuses_without_approval():
    args = _KB_CHECK.parse_args([])
    assert (
        _KB_CHECK.refuse_reason(args)
        == "live knowledge base retrieve requires --i-approve-live-bedrock"
    )
    assert _KB_CHECK.main([]) == 2
    dry = _KB_CHECK.parse_args(["--dry-run"])
    assert _KB_CHECK.refuse_reason(dry) is None
    approved = _KB_CHECK.parse_args(
        [
            "--i-approve-live-bedrock",
            "--max-requests",
            "1",
            "--query",
            "week 1 introduction innovation",
        ]
    )
    assert _KB_CHECK.refuse_reason(approved) is None
    too_many = _KB_CHECK.parse_args(
        ["--i-approve-live-bedrock", "--max-requests", "3"]
    )
    assert "max-requests" in (_KB_CHECK.refuse_reason(too_many) or "")
    assert (
        _KB_CHECK.resolve_course_object_key(
            "Week 1 Introduction to innovation v3.pdf"
        )
        == "course/lectureNotes/Week 1 Introduction to innovation v3.pdf"
    )


def test_knowledge_base_retrieve_diagnostic_dry_run_skips_aws(capsys):
    code = _KB_CHECK.main(["--dry-run"])
    captured = capsys.readouterr()
    assert code == 2
    assert "dry_run" in captured.out
    assert "kb_configured" in captured.out
    assert "metadata_filter_mode" in captured.out
    assert "filter_preview" in captured.out
    assert "production-equivalent" in captured.err
    assert "AKIA" not in captured.out
    assert "aws_secret" not in captured.out.casefold()


def test_course_retrieval_dry_run_does_not_require_live_approval(capsys):
    args = _COURSE_RETRIEVE.parse_args(["--dry-run"])
    assert _COURSE_RETRIEVE.refuse_reason(args) is None
    code = _COURSE_RETRIEVE.main(["--dry-run"])
    captured = capsys.readouterr()
    assert code == 2
    assert "dry_run" in captured.out
    assert "metadata_filter_mode" in captured.out
    assert "production-equivalent" in captured.err


def test_retrieve_diagnostics_do_not_construct_deprecated_strict_boolean():
    kb_text = (
        _ROOT / "scripts" / "diagnostics" / "check_knowledge_base_retrieve.py"
    ).read_text(encoding="utf-8")
    course_text = (
        _ROOT / "scripts" / "diagnostics" / "test_course_retrieval.py"
    ).read_text(encoding="utf-8")
    assert "strict_metadata_filter=" not in kb_text
    assert "strict_metadata_filter=" not in course_text
    assert "metadata_filter_mode=" in kb_text
    assert "metadata_filter_mode=" in course_text


def test_knowledge_base_retrieve_dry_run_in_filter_preview(capsys):
    code = _KB_CHECK.main(
        [
            "--dry-run",
            "--source",
            "Week 1 Introduction to innovation v3.pdf",
            "--second-source",
            "readings/week1.pdf",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    payload = json.loads(captured.out)
    assert payload["filter_preview"]["kind"] == "in"
    assert len(payload["course_material_ids"]) == 2
