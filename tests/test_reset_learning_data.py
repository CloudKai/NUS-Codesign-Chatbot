"""Safety tests for the explicit learning-data reset command."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.persistence.local_files import LocalFileStorage
from backend.persistence.object_keys import notebook_prefix
from backend.student_store import (
    RESEARCH_WORKFLOW_CONTRACT_KEY,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    StudentStore,
)
from scripts.reset_learning_data import (
    CONFIRMATION_PHRASE,
    _verify_manifest,
    apply_sqlite_reset,
    inventory_sqlite,
    main,
)


def _seed_learning_data(database: Path, files_root: Path) -> tuple[StudentStore, str]:
    store = StudentStore(database)
    thread_id = store.create_thread(
        name="Reset safety notebook",
        model_id="gpt-5-mini",
        support_mode="Socratic",
    )
    store.add_message(thread_id, "user", "Private student contribution")
    storage = LocalFileStorage(files_root)
    storage.put_bytes(
        key=notebook_prefix(user_id=store.owner_id, notebook_id=thread_id)
        + "sources/example.txt",
        data=b"managed upload",
        content_type="text/plain",
    )
    return store, thread_id


def test_sqlite_reset_preserves_accounts_and_creates_recoverable_backup(
    tmp_path: Path,
) -> None:
    database = tmp_path / "learning.sqlite3"
    files_root = tmp_path / "files"
    store, thread_id = _seed_learning_data(database, files_root)
    original_user = store.get_user_by_id(store.owner_id)
    # A legacy pre-research SQLite DB may not have the additive readiness table.
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE system_metadata")

    manifest = inventory_sqlite(database, files_root)
    assert manifest["delete_counts"]["notebooks"] == 1
    assert manifest["delete_counts"]["messages"] == 1
    assert manifest["notebooks"][0]["local_object_count"] == 1

    result = apply_sqlite_reset(manifest)

    reset_store = StudentStore(database)
    assert reset_store.list_threads() == []
    preserved_user = reset_store.get_user_by_id(store.owner_id)
    assert preserved_user is not None
    assert preserved_user["id"] == original_user["id"]
    assert preserved_user["identifier"] == original_user["identifier"]
    assert preserved_user["role"] == original_user["role"]
    assert reset_store.get_system_metadata(RESEARCH_WORKFLOW_CONTRACT_KEY) == {
        "version": RESEARCH_WORKFLOW_CONTRACT_VERSION
    }
    assert not (files_root / notebook_prefix(
        user_id=store.owner_id, notebook_id=thread_id
    )).exists()

    backup = Path(result["backup"])
    assert backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT COUNT(*) FROM notebooks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def test_reset_manifest_rejects_tampering_and_stale_inventory(tmp_path: Path) -> None:
    database = tmp_path / "learning.sqlite3"
    files_root = tmp_path / "files"
    store, _thread_id = _seed_learning_data(database, files_root)
    manifest = inventory_sqlite(database, files_root)

    tampered = json.loads(json.dumps(manifest))
    tampered["delete_counts"]["messages"] = 999
    with pytest.raises(ValueError, match="checksum"):
        _verify_manifest(tampered)

    store.create_thread(
        name="Concurrent notebook",
        model_id="gpt-5-mini",
        support_mode="Socratic",
    )
    with pytest.raises(RuntimeError, match="changed after inventory"):
        apply_sqlite_reset(manifest)


def test_cli_apply_requires_exact_confirmation(tmp_path: Path) -> None:
    database = tmp_path / "learning.sqlite3"
    files_root = tmp_path / "files"
    manifest_path = tmp_path / "manifest.json"
    _seed_learning_data(database, files_root)
    assert main(
        [
            "--provider",
            "sqlite",
            "--database",
            str(database),
            "--files-root",
            str(files_root),
            "--manifest",
            str(manifest_path),
        ]
    ) == 0

    with pytest.raises(SystemExit, match=CONFIRMATION_PHRASE):
        main(
            [
                "--provider",
                "sqlite",
                "--manifest",
                str(manifest_path),
                "--apply",
                "--confirmation",
                "wrong",
            ]
        )
