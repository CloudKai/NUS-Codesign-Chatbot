"""Upload local lecture notes and readings to the shared course/ S3 prefix.

Does not write under ``users/`` and does not delete existing course objects.
Requires ``--confirm`` so a missing flag cannot mutate S3.
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path
from typing import Sequence

from backend.file_processing import SUPPORTED_SUFFIXES
from backend.settings import settings

_FOLDERS = ("lectureNotes", "readings")


def course_object_pairs(root: Path, prefix: str) -> list[tuple[Path, str]]:
    """Map local lecture-note files onto shared ``course/`` object keys.

    Args:
        root: Local ``lecture_notes`` directory.
        prefix: Normalized course prefix such as ``course/``.

    Returns:
        ``(local path, object key)`` pairs. README and hidden files are omitted.
    """
    pairs: list[tuple[Path, str]] = []
    normalized = str(prefix or "course/").strip().strip("/") + "/"
    for folder in _FOLDERS:
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if path.name.startswith(".") or path.name == "README.txt":
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            pairs.append((path, f"{normalized}{relative}"))
    return pairs


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the operator upload CLI."""
    parser = argparse.ArgumentParser(
        description="Copy lectureNotes/ and readings/ to s3://bucket/course/ without deleting."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required. Without this flag the script lists keys and exits.",
    )
    parser.add_argument(
        "--bucket",
        default="",
        help="Override COURSE_MATERIALS_BUCKET.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    """List or upload shared course objects. Never deletes and never uses users/."""
    args = parse_args(argv)
    bucket = (args.bucket or settings.resolved_course_materials_bucket).strip()
    prefix = settings.normalized_course_materials_prefix or "course/"
    pairs = course_object_pairs(settings.lecture_notes_dir, prefix)
    if any(key.startswith("users/") for _path, key in pairs):
        print("refusing: course keys must not use the users/ namespace", file=sys.stderr)
        return 2
    if not args.confirm:
        for _path, key in pairs:
            print(key)
        print("refusing: upload requires --confirm", file=sys.stderr)
        return 2
    if not bucket:
        print("refusing: COURSE_MATERIALS_BUCKET is not configured", file=sys.stderr)
        return 2
    try:
        import boto3
    except ImportError:
        print("refusing: boto3 is required to upload course materials", file=sys.stderr)
        return 2
    client = boto3.client("s3", region_name=settings.aws_region)
    for path, key in pairs:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=path.read_bytes(),
            ContentType=content_type,
        )
        print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
