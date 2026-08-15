"""Inventory and reset CDE2300 learning data without deleting user accounts.

The command is deliberately dry-run first. An apply run requires both the
previously written manifest and the exact confirmation phrase. SQLite is
backed up and managed files are moved to a quarantine directory. Aurora DSQL
uses the admin IAM connection only; application runtime remains on
``co_design_app`` and never executes destructive administration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.object_keys import notebook_prefix  # noqa: E402
from backend.workflow_contract import (  # noqa: E402
    WORKFLOW_CONTRACT_KEY as WORKFLOW_METADATA_KEY,
    workflow_contract_payload,
)
from backend.settings import settings  # noqa: E402

CONFIRMATION_PHRASE = "RESET-CDE2300-LEARNING-DATA"
WORKFLOW_METADATA_VALUE = workflow_contract_payload()

_LEARNING_TABLES = (
    "research_adjudications",
    "research_reviews",
    "research_observations",
    "research_access_events",
    "sources",
    "messages",
    "notebooks",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _manifest_digest(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "sha256"}
    return hashlib.sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest()


def _finalize_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["sha256"] = _manifest_digest(result)
    return result


def _verify_manifest(payload: dict[str, Any]) -> None:
    expected = str(payload.get("sha256") or "")
    if not expected or expected != _manifest_digest(payload):
        raise ValueError("Reset manifest checksum is missing or invalid")


def _safe_prefix(user_id: str, notebook_id: str) -> str:
    prefix = notebook_prefix(user_id=user_id, notebook_id=notebook_id)
    expected = f"users/{user_id}/notebooks/{notebook_id}/"
    # UUID identifiers need no sanitisation. Refuse rather than broadening a
    # destructive target if a legacy identifier would be transformed.
    if prefix != expected or not prefix.startswith("users/") or "/notebooks/" not in prefix:
        raise ValueError("Unsafe managed notebook prefix")
    return prefix


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _count(connection: Any, table: str, available: set[str]) -> int:
    if table not in available:
        return 0
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0] if row is not None else 0)


def _local_object_count(files_root: Path, prefix: str) -> int:
    target = (files_root / prefix).resolve()
    root = files_root.resolve()
    if root not in target.parents:
        raise ValueError("Managed file prefix escaped the configured files root")
    if not target.exists():
        return 0
    return sum(1 for path in target.rglob("*") if path.is_file())


def inventory_sqlite(database: Path, files_root: Path) -> dict[str, Any]:
    """Return a non-mutating manifest for one local SQLite learning reset."""
    resolved_database = database.expanduser().resolve()
    resolved_files = files_root.expanduser().resolve()
    if not resolved_database.is_file():
        raise FileNotFoundError(resolved_database)
    connection = sqlite3.connect(f"file:{resolved_database}?mode=ro", uri=True)
    try:
        available = _sqlite_tables(connection)
        if not {"users", "notebooks", "messages", "sources"}.issubset(available):
            raise ValueError("Database is not a compatible CDE2300 database")
        users = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN role IN ('lecturer','admin') THEN 1 ELSE 0 END) FROM users"
        ).fetchone()
        notebooks = [
            {
                "notebook_id": str(row[0]),
                "user_id": str(row[1]),
                "object_prefix": _safe_prefix(str(row[1]), str(row[0])),
            }
            for row in connection.execute(
                "SELECT id, user_id FROM notebooks ORDER BY id"
            ).fetchall()
        ]
        for notebook in notebooks:
            notebook["local_object_count"] = _local_object_count(
                resolved_files, str(notebook["object_prefix"])
            )
        counts = {table: _count(connection, table, available) for table in _LEARNING_TABLES}
    finally:
        connection.close()
    return _finalize_manifest(
        {
            "manifest_version": 1,
            "reset_id": str(uuid.uuid4()),
            "created_at": _utc_now(),
            "provider": "sqlite",
            "target": {
                "database": str(resolved_database),
                "files_root": str(resolved_files),
            },
            "preserved": {
                "users": int(users[0] or 0),
                "staff_roles": int(users[1] or 0),
            },
            "delete_counts": counts,
            "notebooks": notebooks,
        }
    )


def _quarantine_local_files(manifest: dict[str, Any]) -> tuple[Path, list[tuple[Path, Path]]]:
    target = manifest["target"]
    root = Path(str(target["files_root"])).resolve()
    database = Path(str(target["database"])).resolve()
    quarantine = database.parent / "reset-quarantine" / str(manifest["reset_id"])
    moved: list[tuple[Path, Path]] = []
    for notebook in manifest.get("notebooks") or []:
        prefix = _safe_prefix(
            str(notebook["user_id"]), str(notebook["notebook_id"])
        )
        source = (root / prefix).resolve()
        if root not in source.parents:
            raise ValueError("Managed file prefix escaped the configured files root")
        if not source.exists():
            continue
        destination = (quarantine / prefix).resolve()
        if quarantine.resolve() not in destination.parents:
            raise ValueError("Quarantine path escaped its reset directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved.append((source, destination))
    return quarantine, moved


def _restore_quarantine(moved: Iterable[tuple[Path, Path]]) -> None:
    for source, destination in reversed(list(moved)):
        if not destination.exists() or source.exists():
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))


def apply_sqlite_reset(manifest: dict[str, Any]) -> dict[str, Any]:
    """Apply a verified SQLite manifest, preserving users and a DB backup."""
    _verify_manifest(manifest)
    if manifest.get("provider") != "sqlite":
        raise ValueError("Manifest is not for SQLite")
    database = Path(str(manifest["target"]["database"])).resolve()
    fresh = inventory_sqlite(database, Path(str(manifest["target"]["files_root"])))
    if fresh["delete_counts"] != manifest.get("delete_counts") or fresh["notebooks"] != manifest.get("notebooks"):
        raise RuntimeError("Learning data changed after inventory; create a new manifest")

    backup_dir = database.parent / "reset-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{database.name}.{manifest['reset_id']}.bak"
    # SQLite's online backup API captures committed WAL content into one
    # recoverable database file. A raw filesystem copy can miss WAL pages.
    source_connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    backup_connection = sqlite3.connect(backup)
    try:
        source_connection.backup(backup_connection)
    finally:
        backup_connection.close()
        source_connection.close()
    quarantine, moved = _quarantine_local_files(manifest)
    connection = sqlite3.connect(database)
    try:
        available = _sqlite_tables(connection)
        connection.execute("BEGIN IMMEDIATE")
        for table in _LEARNING_TABLES:
            if table in available:
                connection.execute(f"DELETE FROM {table}")
        # The explicit reset also supports a pre-research SQLite database that
        # does not yet contain the additive readiness table. Normal startup
        # will create all other additive tables after the learning rows are gone.
        connection.execute(
            """CREATE TABLE IF NOT EXISTS system_metadata (
                key TEXT PRIMARY KEY,
                value_text TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """
            INSERT INTO system_metadata (key, value_text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value_text=excluded.value_text, updated_at=excluded.updated_at
            """,
            (
                WORKFLOW_METADATA_KEY,
                _canonical_json(WORKFLOW_METADATA_VALUE),
                _utc_now(),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        _restore_quarantine(moved)
        raise
    finally:
        connection.close()
    return {
        "status": "completed",
        "provider": "sqlite",
        "reset_id": manifest["reset_id"],
        "backup": str(backup),
        "quarantine": str(quarantine),
        "preserved": manifest["preserved"],
        "deleted": manifest["delete_counts"],
    }


@dataclass(frozen=True)
class DsqlAdminOptions:
    endpoint: str
    region: str
    database: str = "postgres"
    admin_user: str = "admin"


def _dsql_connect(options: DsqlAdminOptions):
    from scripts.init_dsql import _connect_admin

    return _connect_admin(
        endpoint=options.endpoint,
        region=options.region,
        database=options.database,
        admin_user=options.admin_user,
    )


def _mapping_value(row: Any, key: str, position: int = 0) -> Any:
    if row is None:
        return None
    if hasattr(row, "get"):
        return row.get(key)
    return row[position]


def _dsql_table_names(connection: Any) -> set[str]:
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ).fetchall()
    return {str(_mapping_value(row, "table_name")) for row in rows}


def inventory_dsql(options: DsqlAdminOptions, *, bucket: str) -> dict[str, Any]:
    """Return a non-mutating DSQL/S3 reset manifest using admin IAM auth."""
    if not options.endpoint.strip() or not options.region.strip() or not bucket.strip():
        raise ValueError("DSQL endpoint, AWS region, and uploads bucket are required")
    connection = _dsql_connect(options)
    try:
        tables = _dsql_table_names(connection)
        required = {"users", "system_metadata", *_LEARNING_TABLES}
        if not required.issubset(tables):
            raise ValueError("DSQL schema is incomplete; run scripts/init_dsql.py first")
        users = connection.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN role IN ('lecturer','admin') THEN 1 ELSE 0 END) AS staff FROM users"
        ).fetchone()
        notebooks = [
            {
                "notebook_id": str(_mapping_value(row, "id", 0)),
                "user_id": str(_mapping_value(row, "user_id", 1)),
            }
            for row in connection.execute(
                "SELECT id, user_id FROM notebooks ORDER BY id"
            ).fetchall()
        ]
        for notebook in notebooks:
            notebook["object_prefix"] = _safe_prefix(
                notebook["user_id"], notebook["notebook_id"]
            )
        counts: dict[str, int] = {}
        for table in _LEARNING_TABLES:
            if table not in tables:
                counts[table] = 0
                continue
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            counts[table] = int(_mapping_value(row, "count") or 0)
        connection.commit()
    finally:
        connection.close()
    return _finalize_manifest(
        {
            "manifest_version": 1,
            "reset_id": str(uuid.uuid4()),
            "created_at": _utc_now(),
            "provider": "dsql",
            "target": {
                "endpoint": options.endpoint,
                "region": options.region,
                "database": options.database,
                "admin_user": options.admin_user,
                "bucket": bucket,
            },
            "preserved": {
                "users": int(_mapping_value(users, "total", 0) or 0),
                "staff_roles": int(_mapping_value(users, "staff", 1) or 0),
            },
            "delete_counts": counts,
            "notebooks": notebooks,
        }
    )


def _delete_owned_notebook_dsql(connection: Any, notebook_id: str) -> None:
    # Child-first ordering is required because Aurora DSQL has no foreign keys.
    for table in ("research_adjudications", "research_reviews"):
        connection.execute(
            f"DELETE FROM {table} WHERE observation_id IN (SELECT id FROM research_observations WHERE notebook_id=?)",
            (notebook_id,),
        )
    connection.execute(
        "DELETE FROM research_observations WHERE notebook_id=?", (notebook_id,)
    )
    for table in ("sources", "messages"):
        connection.execute(f"DELETE FROM {table} WHERE notebook_id=?", (notebook_id,))
    connection.execute("DELETE FROM notebooks WHERE id=?", (notebook_id,))


def apply_dsql_reset(
    manifest: dict[str, Any],
    *,
    storage_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Apply an exact DSQL manifest and remove only its managed S3 prefixes."""
    _verify_manifest(manifest)
    if manifest.get("provider") != "dsql":
        raise ValueError("Manifest is not for DSQL")
    target = manifest["target"]
    options = DsqlAdminOptions(
        endpoint=str(target["endpoint"]),
        region=str(target["region"]),
        database=str(target["database"]),
        admin_user=str(target["admin_user"]),
    )
    fresh = inventory_dsql(options, bucket=str(target["bucket"]))
    if fresh["delete_counts"] != manifest.get("delete_counts") or fresh["notebooks"] != manifest.get("notebooks"):
        raise RuntimeError("Learning data changed after inventory; create a new manifest")

    for notebook in manifest.get("notebooks") or []:
        connection = _dsql_connect(options)
        try:
            _delete_owned_notebook_dsql(connection, str(notebook["notebook_id"]))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    connection = _dsql_connect(options)
    try:
        for table in ("research_access_events",):
            connection.execute(f"DELETE FROM {table}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if storage_factory is None:
        from backend.persistence.s3_files import S3FileStorage

        def storage_factory() -> S3FileStorage:
            return S3FileStorage(
                bucket=str(target["bucket"]), region=options.region
            )
    storage = storage_factory()
    deleted_objects = 0
    for notebook in manifest.get("notebooks") or []:
        prefix = _safe_prefix(str(notebook["user_id"]), str(notebook["notebook_id"]))
        deleted_objects += int(storage.delete_prefix(prefix))

    connection = _dsql_connect(options)
    try:
        connection.execute(
            """
            INSERT INTO system_metadata (key, value_text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value_text=excluded.value_text, updated_at=excluded.updated_at
            """,
            (WORKFLOW_METADATA_KEY, _canonical_json(WORKFLOW_METADATA_VALUE), _utc_now()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "status": "completed",
        "provider": "dsql",
        "reset_id": manifest["reset_id"],
        "deleted_objects": deleted_objects,
        "preserved": manifest["preserved"],
        "deleted": manifest["delete_counts"],
    }


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Reset manifest must contain one JSON object")
    _verify_manifest(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory or reset learning data while preserving users and roles."
    )
    parser.add_argument("--provider", choices=("sqlite", "dsql"), default=settings.database_provider)
    parser.add_argument("--database", type=Path, default=settings.database_path)
    parser.add_argument("--files-root", type=Path, default=settings.files_dir)
    parser.add_argument("--endpoint", default=settings.dsql_endpoint)
    parser.add_argument("--region", default=settings.aws_region)
    parser.add_argument("--dsql-database", default=settings.dsql_database)
    parser.add_argument("--admin-user", default=os.getenv("DSQL_ADMIN_USER", "admin"))
    parser.add_argument("--bucket", default=settings.user_uploads_bucket)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirmation", default="")
    args = parser.parse_args(argv)

    if not args.apply:
        if args.provider == "sqlite":
            manifest = inventory_sqlite(args.database, args.files_root)
        else:
            manifest = inventory_dsql(
                DsqlAdminOptions(
                    endpoint=args.endpoint,
                    region=args.region,
                    database=args.dsql_database,
                    admin_user=args.admin_user,
                ),
                bucket=args.bucket,
            )
        _write_manifest(args.manifest, manifest)
        print(json.dumps(manifest, indent=2))
        print(f"Dry run only. Review {args.manifest.resolve()} before applying.")
        return 0

    if args.confirmation != CONFIRMATION_PHRASE:
        raise SystemExit(
            f"Refusing destructive reset without --confirmation {CONFIRMATION_PHRASE}"
        )
    manifest = _load_manifest(args.manifest)
    if manifest.get("provider") != args.provider:
        raise SystemExit("--provider does not match the saved manifest")
    result = (
        apply_sqlite_reset(manifest)
        if args.provider == "sqlite"
        else apply_dsql_reset(manifest)
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
