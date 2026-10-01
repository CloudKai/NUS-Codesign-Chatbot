"""Offline verification of course Knowledge Base sidecar identity.

Default mode never calls AWS. It compares local course files against canonical
``course_material_id`` values and optional sibling ``.metadata.json`` files.
Live Retrieve inspection requires ``--i-approve-live-bedrock`` and is not used
by pytest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from backend.settings import settings
from backend.sources.kb_metadata import (
    expected_sidecar_material_id,
    local_sidecar_path,
    sidecar_json_bytes,
    sidecar_material_id_from_payload,
    sidecar_object_key,
)


def _course_pairs(root: Path, prefix: str) -> list[tuple[Path, str]]:
    """Return local course files mapped onto shared object keys."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "sync_course_materials.py"
    spec = importlib.util.spec_from_file_location(
        "co_design_sync_course_materials_verify", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load sync_course_materials.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.course_object_pairs(root, prefix)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the sidecar verification CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify course_material_id sidecars without mutating S3. "
            "Live Retrieve inspection is opt-in."
        )
    )
    parser.add_argument(
        "--i-approve-live-bedrock",
        action="store_true",
        help="Required to call live Knowledge Base Retrieve.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Local sidecar preflight only (default). Never calls AWS.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def local_sidecar_report(root: Path, prefix: str) -> list[dict[str, Any]]:
    """Return secret-safe sidecar status rows for local course files.

    Args:
        root: Local lecture_notes directory.
        prefix: Shared course prefix.

    Returns:
        One row per course document with keys, expected id, and sidecar match.
    """
    rows: list[dict[str, Any]] = []
    for path, object_key in _course_pairs(root, prefix):
        expected = expected_sidecar_material_id(object_key)
        sidecar_path = local_sidecar_path(path)
        present = sidecar_path.is_file()
        actual = ""
        matches = False
        if present:
            try:
                payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = None
            actual = sidecar_material_id_from_payload(payload)
            matches = actual == expected and actual != ""
        rows.append(
            {
                "object_key": object_key,
                "sidecar_key": sidecar_object_key(object_key),
                "expected_course_material_id": expected,
                "sidecar_present": present,
                "sidecar_matches": matches,
                "canonical_bytes_match": (
                    present and sidecar_path.read_bytes() == sidecar_json_bytes(object_key)
                ),
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    """Print local sidecar verification JSON. Refuse live AWS by default."""
    args = parse_args(argv)
    if args.i_approve_live_bedrock:
        print(
            "refusing: live Retrieve and ingestion inspection are not executed "
            "by this command. Use scripts/diagnostics/check_knowledge_base_retrieve.py "
            "--i-approve-live-bedrock after sidecars are ingested.",
            file=sys.stderr,
        )
        return 2
    prefix = settings.normalized_course_materials_prefix or "course/"
    rows = local_sidecar_report(settings.lecture_notes_dir, prefix)
    missing = [row for row in rows if not row["sidecar_present"]]
    mismatches = [row for row in rows if not row["sidecar_matches"]]
    filter_mode = str(settings.normalized_knowledge_base_metadata_filter_mode)
    report = {
        "files": rows,
        "count": len(rows),
        "sidecar_missing_count": len(missing),
        "sidecar_mismatch_count": len(mismatches),
        "local_sidecar_ok": bool(rows) and not missing and not mismatches,
        "canonical_id_function": "backend.retrieval.course_material_id_from_object_key",
        "kb_ingestion": {
            "status": "not_executed",
            "requires": (
                "live AWS after sidecar upload: StartIngestionJob then "
                "GetIngestionJob COMPLETE. See docs/KB_REQUIRED_MODE_RUNBOOK.md"
            ),
        },
        "filtered_retrieve": {
            "status": "not_executed",
            "requires": (
                "scripts/diagnostics/check_knowledge_base_retrieve.py "
                "--i-approve-live-bedrock"
            ),
            "metadata_filter_mode": filter_mode,
        },
        "dry_run": True,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not rows:
        return 1
    return 1 if missing or mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
