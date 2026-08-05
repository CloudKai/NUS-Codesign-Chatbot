"""Tests for explicit, non-destructive database initialization."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_INIT_DB_PATH = Path(__file__).resolve().parents[1] / "scripts" / "init_db.py"
_SPEC = importlib.util.spec_from_file_location("co_design_init_db", _INIT_DB_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_INIT_DB = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_INIT_DB)
main = _INIT_DB.main
resolve_database_path = _INIT_DB.resolve_database_path


def test_resolve_refuses_existing_database_without_force(tmp_path: Path) -> None:
    """An existing file must not be opened unless ``--force`` is set."""
    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"")
    with pytest.raises(SystemExit, match="Refusing to initialize existing database"):
        resolve_database_path(database, force=False)


def test_resolve_allows_existing_database_with_force(tmp_path: Path) -> None:
    """``--force`` may ensure schema on an existing file after explicit consent."""
    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"")
    assert resolve_database_path(database, force=True) == database.resolve()


def test_main_creates_new_database(tmp_path: Path) -> None:
    """A new ``--database`` path initializes without requiring ``--force``."""
    database = tmp_path / "fresh.sqlite3"
    assert main(["--database", str(database)]) == 0
    assert database.exists()


def test_main_refuses_existing_without_force(tmp_path: Path) -> None:
    """CLI exit is non-zero when the target already exists and force is omitted."""
    database = tmp_path / "existing.sqlite3"
    database.write_bytes(b"")
    with pytest.raises(SystemExit, match="Refusing to initialize existing database"):
        main(["--database", str(database)])
