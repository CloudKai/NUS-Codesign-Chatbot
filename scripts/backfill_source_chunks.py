"""Backfill disposable ``derived/chunks.v1.json`` artifacts for existing sources.

Offline maintenance only. The coaching runtime never depends on this script:
uploads write the artifact best-effort, and retrieval falls back to
``derived/extracted.txt`` when the artifact is missing or invalid.

Dry-run is the default. ``--confirm`` is required to write objects or update
source metadata. Do not run this against production without explicit
authorization.

The script reads one owner's sources from a SQLite database and uses the
configured file-storage provider (typically local). It does not perform schema
migrations and does not create users.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.factory import get_file_storage  # noqa: E402
from backend.persistence.object_keys import build_source_chunks_object_key  # noqa: E402
from backend.persistence.ports import FileStorage  # noqa: E402
from backend.persistence.store.contracts import dump_json, load_json, utc_now  # noqa: E402
from backend.sources.chunk_artifacts import (  # noqa: E402
    extracted_text_digest,
    write_chunk_artifact_best_effort,
)

_OWNED_SOURCES_SQL = """
SELECT
  u.id AS owner_id,
  n.id AS notebook_id,
  s.id AS source_id,
  s.extracted_text_key AS extracted_text_key,
  s.metadata_text AS metadata_text
FROM sources s
JOIN notebooks n ON n.id = s.notebook_id
JOIN users u ON u.id = n.user_id
WHERE u.identifier = ?
ORDER BY n.created_at ASC, s.created_at ASC, s.id ASC
"""


@dataclass(frozen=True)
class PlannedBackfill:
    """One source that needs a chunk artifact and/or a metadata digest."""

    owner_id: str
    notebook_id: str
    source_id: str
    text: str
    digest: str
    write_artifact: bool
    update_digest: bool


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the refuse-by-default backfill CLI.

    Args:
        argv: Optional argument vector; ``None`` reads ``sys.argv``.

    Returns:
        Parsed namespace with ``database``, ``identifier``, and ``confirm``.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Write missing derived/chunks.v1.json artifacts and extracted-text "
            "digests for one owner's SQLite sources. Dry-run unless --confirm."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        required=True,
        help="SQLite database to read. Required so the live default path is never implied.",
    )
    parser.add_argument(
        "--identifier",
        required=True,
        help="Existing users.identifier whose owned sources should be inspected.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to write chunk objects or update metadata. Without it, print counts.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _load_extracted_text(storage: FileStorage, extracted_text_key: str | None) -> str:
    """Return UTF-8 extracted text, or empty when the object is missing."""
    key = str(extracted_text_key or "").strip()
    if not key:
        return ""
    try:
        data = storage.get_bytes(key)
    except FileNotFoundError:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _connect(database: Path) -> sqlite3.Connection:
    """Open *database* with row access by column name."""
    connection = sqlite3.connect(str(database))
    connection.row_factory = sqlite3.Row
    return connection


def plan_backfill(
    connection: sqlite3.Connection,
    *,
    identifier: str,
    storage: FileStorage,
) -> tuple[int, list[PlannedBackfill]]:
    """Inspect owned sources and return planned writes.

    Args:
        connection: Open SQLite connection to the student database.
        identifier: ``users.identifier`` to select.
        storage: Configured object-storage adapter.

    Returns:
        ``(scanned_count, planned_actions)``.

    Raises:
        ValueError: when *identifier* does not match an existing user.
    """
    user = connection.execute(
        "SELECT id FROM users WHERE identifier = ?",
        (identifier,),
    ).fetchone()
    if user is None:
        raise ValueError("identifier not found")
    rows = connection.execute(_OWNED_SOURCES_SQL, (identifier,)).fetchall()
    planned: list[PlannedBackfill] = []
    for row in rows:
        text = _load_extracted_text(storage, row["extracted_text_key"])
        if not str(text or "").strip():
            continue
        digest = extracted_text_digest(text)
        metadata = load_json(row["metadata_text"], {})
        if not isinstance(metadata, dict):
            metadata = {}
        chunks_key = build_source_chunks_object_key(
            user_id=str(row["owner_id"]),
            notebook_id=str(row["notebook_id"]),
            source_id=str(row["source_id"]),
        )
        write_artifact = not storage.exists(chunks_key)
        stored_digest = str(metadata.get("extracted_text_sha256") or "")
        update_digest = stored_digest != digest
        if not write_artifact and not update_digest:
            continue
        planned.append(
            PlannedBackfill(
                owner_id=str(row["owner_id"]),
                notebook_id=str(row["notebook_id"]),
                source_id=str(row["source_id"]),
                text=text,
                digest=digest,
                write_artifact=write_artifact,
                update_digest=update_digest,
            )
        )
    return len(rows), planned


def apply_backfill(
    connection: sqlite3.Connection,
    planned: Sequence[PlannedBackfill],
    *,
    storage: FileStorage,
) -> tuple[int, int, int]:
    """Write missing artifacts and digests for *planned* sources.

    Args:
        connection: Open SQLite connection used for metadata updates.
        planned: Actions from :func:`plan_backfill`.
        storage: Configured object-storage adapter.

    Returns:
        ``(artifacts_written, digests_updated, failures)``.
    """
    written = 0
    updated = 0
    failures = 0
    for action in planned:
        if action.write_artifact:
            ok = write_chunk_artifact_best_effort(
                storage=storage,
                user_id=action.owner_id,
                notebook_id=action.notebook_id,
                source_id=action.source_id,
                text=action.text,
                digest=action.digest,
            )
            if ok:
                written += 1
            else:
                failures += 1
        if action.update_digest:
            try:
                _update_digest(
                    connection,
                    notebook_id=action.notebook_id,
                    source_id=action.source_id,
                    digest=action.digest,
                )
                updated += 1
            except Exception:  # noqa: BLE001 - continue remaining sources
                failures += 1
    connection.commit()
    return written, updated, failures


def _update_digest(
    connection: sqlite3.Connection,
    *,
    notebook_id: str,
    source_id: str,
    digest: str,
) -> None:
    """Merge ``extracted_text_sha256`` into source metadata without dropping keys."""
    row = connection.execute(
        """
        SELECT metadata_text FROM sources
        WHERE id = ? AND notebook_id = ?
        """,
        (source_id, notebook_id),
    ).fetchone()
    if row is None:
        raise ValueError("source not found")
    metadata = load_json(row["metadata_text"], {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["extracted_text_sha256"] = digest
    connection.execute(
        """
        UPDATE sources
        SET metadata_text = ?, updated_at = ?
        WHERE id = ? AND notebook_id = ?
        """,
        (dump_json(metadata), utc_now(), source_id, notebook_id),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """List or apply missing chunk-artifact backfill work.

    Args:
        argv: Optional argument vector.

    Returns:
        ``0`` on dry-run or successful apply; ``2`` when the request is refused.
    """
    args = parse_args(argv)
    database = args.database.expanduser()
    if not database.is_absolute():
        database = (Path.cwd() / database).resolve()
    else:
        database = database.resolve()
    if not database.is_file():
        print(f"refusing: database not found at {database}", file=sys.stderr)
        return 2
    identifier = str(args.identifier or "").strip()
    if not identifier:
        print("refusing: --identifier is required", file=sys.stderr)
        return 2
    storage = get_file_storage()
    connection = _connect(database)
    try:
        try:
            scanned, planned = plan_backfill(
                connection, identifier=identifier, storage=storage
            )
        except ValueError:
            print("refusing: identifier not found", file=sys.stderr)
            return 2
        artifact_count = sum(1 for item in planned if item.write_artifact)
        digest_count = sum(1 for item in planned if item.update_digest)
        print(
            f"scanned={scanned} planned={len(planned)} "
            f"write_artifact={artifact_count} update_digest={digest_count}"
        )
        if not args.confirm:
            print("refusing: write requires --confirm", file=sys.stderr)
            return 2
        written, updated, failures = apply_backfill(
            connection, planned, storage=storage
        )
        print(
            f"written={written} digest_updated={updated} failures={failures}"
        )
        return 0 if failures == 0 else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
