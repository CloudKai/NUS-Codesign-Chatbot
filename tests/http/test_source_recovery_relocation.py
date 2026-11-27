"""Local source bytes must survive the documented fresh-location restore.

The documented stopped-server backup procedure (SQLite backup API plus the
files tree, as in ``scripts/init_db.py`` conventions and the classroom probe)
restores data into a fresh disposable location after the original stores become
unavailable. Locally stored uploads keep the existing
``files_dir/threads/<thread>/uploads`` layout, so the restored read must
re-anchor the stored path under the configured ``files_dir`` instead of the
stale absolute location written at upload time.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import shutil
import sqlite3

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import settings
from backend.student_store import StudentStore


def test_local_source_bytes_reopen_after_fresh_location_restore(
    tmp_path: Path, monkeypatch: __import__("pytest").MonkeyPatch,
) -> None:
    """A restored source reads its original bytes from the new files root."""
    source_bytes = b"Analogy transfers relationships between designs."
    active = tmp_path / "active"
    database = active / "workspace.sqlite3"
    monkeypatch.setattr(settings, "files_dir", active / "files")
    store = StudentStore(database)
    thread = store.create_thread(model_id="mock", support_mode="critical-thinking")
    with TestClient(create_app(store)) as client:
        created = client.post(
            f"/api/v1/threads/{thread}/sources",
            files={"files": ("analogy.txt", source_bytes, "text/plain")},
        )
        assert created.status_code == 200, created.text
        source_id = created.json()[0]["id"]
        assert client.get(
            f"/api/v1/threads/{thread}/sources/{source_id}/content"
        ).content == source_bytes

    # Every writer is stopped. The backup is independent of the original
    # stores, which then become unavailable; recovery uses only the copy in a
    # fresh location, exactly like the disposable rehearsal.
    backup = tmp_path / "backup"
    backup.mkdir()
    with closing(sqlite3.connect(database)) as original, \
            closing(sqlite3.connect(backup / database.name)) as target:
        original.backup(target)
    shutil.copytree(active / "files", backup / "files")
    recovered = tmp_path / "recovered"
    shutil.copytree(backup, recovered)
    (active / "files").rename(active / "files.unavailable")

    monkeypatch.setattr(settings, "files_dir", recovered / "files")
    with TestClient(create_app(StudentStore(recovered / database.name))) as restored:
        response = restored.get(
            f"/api/v1/threads/{thread}/sources/{source_id}/content"
        )
        assert response.status_code == 200, response.text
        assert response.content == source_bytes
