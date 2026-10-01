"""Generate Bedrock Knowledge Base sidecar JSON for shared course objects.

Dry-run is the default. Live S3 upload requires ``--confirm`` so a missing
flag cannot mutate the course bucket. Never writes under ``users/``.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Sequence

from backend.settings import settings
from backend.sources.kb_metadata import (
    expected_sidecar_material_id,
    sidecar_json_bytes,
    sidecar_object_key,
)


def _course_object_pairs(root: Path, prefix: str) -> list[tuple[Path, str]]:
    """Load the shared course-key mapper from the sibling uploader script."""
    path = Path(__file__).resolve().parent / "sync_course_materials.py"
    spec = importlib.util.spec_from_file_location(
        "co_design_sync_course_materials", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load sync_course_materials.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.course_object_pairs(root, prefix)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the sidecar generator CLI."""
    parser = argparse.ArgumentParser(
        description=(
            "Write course_material_id sidecar JSON next to lectureNotes/readings "
            "objects. Dry-run lists keys. --confirm uploads to S3."
        )
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to upload sidecar objects. Without it, print planned keys.",
    )
    parser.add_argument(
        "--bucket",
        default="",
        help="Override COURSE_MATERIALS_BUCKET.",
    )
    parser.add_argument(
        "--write-local",
        action="store_true",
        help="Write sidecar files next to local lecture_notes copies (no S3).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def planned_sidecars(root: Path, prefix: str) -> list[tuple[Path, str, str]]:
    """Return ``(source path, course object key, sidecar key)`` triples.

    Args:
        root: Local lecture_notes directory.
        prefix: Shared course prefix such as ``course/``.

    Returns:
        One triple per approved course document. Sidecar keys themselves are
        never treated as source documents.
    """
    planned: list[tuple[Path, str, str]] = []
    for path, object_key in _course_object_pairs(root, prefix):
        sidecar_key = sidecar_object_key(object_key)
        if not sidecar_key or sidecar_key == object_key:
            continue
        planned.append((path, object_key, sidecar_key))
    return planned


def main(argv: Sequence[str] | None = None) -> int:
    """List or write Bedrock metadata sidecars for shared course objects."""
    args = parse_args(argv)
    bucket = (args.bucket or settings.resolved_course_materials_bucket).strip()
    prefix = settings.normalized_course_materials_prefix or "course/"
    planned = planned_sidecars(settings.lecture_notes_dir, prefix)
    if any(
        object_key.startswith("users/") or sidecar_key.startswith("users/")
        for _path, object_key, sidecar_key in planned
    ):
        print("refusing: course keys must not use the users/ namespace", file=sys.stderr)
        return 2
    if not args.confirm and not args.write_local:
        for _path, object_key, sidecar_key in planned:
            material_id = expected_sidecar_material_id(object_key)
            print(f"{object_key}\t{sidecar_key}\t{material_id}")
        print("refusing: upload requires --confirm (or --write-local)", file=sys.stderr)
        return 2
    if args.write_local:
        for path, object_key, sidecar_key in planned:
            sidecar_path = Path(f"{path}.metadata.json")
            sidecar_path.write_bytes(sidecar_json_bytes(object_key))
            print(f"local\t{sidecar_key}\t{expected_sidecar_material_id(object_key)}")
        return 0
    if not bucket:
        print("refusing: COURSE_MATERIALS_BUCKET is not configured", file=sys.stderr)
        return 2
    try:
        import boto3
    except ImportError:
        print("refusing: boto3 is required to upload course metadata", file=sys.stderr)
        return 2
    client = boto3.client("s3", region_name=settings.aws_region)
    for _path, object_key, sidecar_key in planned:
        client.put_object(
            Bucket=bucket,
            Key=sidecar_key,
            Body=sidecar_json_bytes(object_key),
            ContentType="application/json",
        )
        print(f"upload\t{sidecar_key}\t{expected_sidecar_material_id(object_key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
