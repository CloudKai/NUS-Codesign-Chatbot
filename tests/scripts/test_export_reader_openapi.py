"""Offline browser-contract projection, isolation, determinism and drift guards."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from backend.api import create_app
from backend.student_store import StudentStore
from scripts.export_reader_openapi import APPROVED_OPERATIONS, reader_schema

ROOT = Path(__file__).resolve().parents[2]


def test_reader_contract_excludes_internal_routes_and_schemas(tmp_path: Path) -> None:
    """Only reviewed GET operations and reachable public models enter codegen."""
    app = create_app(StudentStore(tmp_path / "contract.sqlite3"))
    schema = reader_schema(app)
    operations = {(path, method.upper()): op["operationId"]
                  for path, methods in schema["paths"].items() for method, op in methods.items()}
    assert operations == APPROVED_OPERATIONS
    assert set(schema["components"]["schemas"]) == {
        "ReaderSession", "ReaderNotebooks", "ReaderNotebook", "ReaderChatSummary",
        "ReaderPage", "ReaderMessage", "CitationReference", "ReaderError",
        "ReaderBootstrap", "ReaderPreferences",
        "HTTPValidationError", "ValidationError",
    }
    assert app.openapi_url is None
    assert app.docs_url is None


def test_reader_contract_refuses_missing_or_untyped_operations(tmp_path: Path) -> None:
    """Changes to the reviewed inventory must be explicit rather than silently omitted."""
    with pytest.raises(ValueError, match="missing"):
        reader_schema(FastAPI())
    app = create_app(StudentStore(tmp_path / "contract.sqlite3"))
    route = next(route for route in app.routes if isinstance(route, APIRoute)
                 and route.operation_id == "readerSession")
    route.response_model = None
    with pytest.raises(ValueError, match="typed stable operation"):
        reader_schema(app)


def test_export_is_deterministic_and_ignores_live_storage_configuration(tmp_path: Path) -> None:
    """The real CLI overrides production-shaped inputs before importing app/settings."""
    output = tmp_path / "reader.json"
    env = {**os.environ, "APP_ENV": "production", "MODEL_PROVIDER": "agentcore",
           "DATABASE_PROVIDER": "dsql", "FILE_STORAGE_PROVIDER": "s3",
           "APP_DATABASE_PATH": str(tmp_path / "must-not-exist.sqlite3")}
    command = [sys.executable, str(ROOT / "scripts/export_reader_openapi.py"), "--output", str(output)]
    subprocess.run(command, cwd=tmp_path, env=env, check=True, capture_output=True)
    first = output.read_bytes()
    subprocess.run(command, cwd=tmp_path, env=env, check=True, capture_output=True)
    assert output.read_bytes() == first
    assert not (tmp_path / "must-not-exist.sqlite3").exists()
    assert json.loads(first)["info"]["title"] == "Co-design browser reader"
    assert subprocess.run(command + ["--check"], env=env, capture_output=True).returncode == 0
    output.write_text("{}", encoding="utf-8")
    assert subprocess.run(command + ["--check"], env=env, capture_output=True).returncode == 1
    assert output.read_text(encoding="utf-8") == "{}"
