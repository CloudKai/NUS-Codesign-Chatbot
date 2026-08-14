"""Deterministic tests for operator course-sync and AgentCore smoke CLIs."""

from __future__ import annotations

import importlib.util
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
