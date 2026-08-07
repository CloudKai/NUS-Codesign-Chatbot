"""Deterministic tests for storage providers and DSQL/S3 adapters (no AWS calls)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from backend.persistence.dsql_connection import (
    adapt_sqlite_sql,
    generate_dsql_admin_auth_token,
    generate_dsql_auth_token,
    is_retryable_db_error,
    run_dsql_transaction,
    strip_foreign_keys,
)
from backend.persistence.dsql_schema import (
    DSQL_SCHEMA,
    RUNTIME_ROLE_NAME,
    iter_dsql_ddl_statements,
)
from backend.persistence.dsql_student_store import DsqlStudentStore
from backend.persistence.factory import (
    create_file_storage,
    create_student_store,
    reset_file_storage_cache,
    validate_storage_configuration,
)
from backend.persistence.local_files import LocalFileStorage
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.object_keys import build_upload_object_key, sanitize_filename
from backend.persistence.s3_files import S3FileStorage, is_missing_object_error
from backend.student_store import StudentStore

_INIT_DSQL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "init_dsql.py"
_SPEC = importlib.util.spec_from_file_location("co_design_init_dsql", _INIT_DSQL_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_INIT_DSQL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_INIT_DSQL)
apply_dsql_schema = _INIT_DSQL.apply_dsql_schema
is_async_index_ddl = _INIT_DSQL.is_async_index_ddl


class _OccError(Exception):
    """Fake psycopg serialization failure."""

    sqlstate = "40001"


class _FakeDsqlConnection:
    """Minimal DSQL connection stand-in that records SQL and never talks to AWS."""

    def __init__(self, recorder: list[str] | None = None):
        self.recorder = recorder if recorder is not None else []
        self.closed = False
        self._rows: dict[str, Any] = {}

    def execute(self, sql: str, params: Any = None) -> Any:
        self.recorder.append(sql.strip())
        upper = sql.strip().upper()
        if upper.startswith("SELECT ID FROM USERS WHERE IDENTIFIER"):
            identifier = (params or [None])[0]
            owner = self._rows.get(("user", identifier))

            class _R:
                def fetchone(self_inner):
                    if owner is None:
                        return None
                    return {"id": owner}

            return _R()
        if upper.startswith("INSERT INTO USERS"):
            owner_id = (params or [None])[0]
            identifier = (params or [None, None])[1]
            self._rows[("user", identifier)] = owner_id

            class _R:
                rowcount = 1

                def fetchone(self_inner):
                    return None

                def fetchall(self_inner):
                    return []

            return _R()

        class _Empty:
            rowcount = 0

            def fetchone(self_inner):
                return None

            def fetchall(self_inner):
                return []

        return _Empty()

    def executescript(self, script: str) -> None:
        self.recorder.append(f"SCRIPT:{script[:40]}")

    def commit(self) -> None:
        self.recorder.append("COMMIT")

    def rollback(self) -> None:
        self.recorder.append("ROLLBACK")

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _FakeDsqlConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


def test_sanitize_and_object_key_never_trust_raw_path():
    assert ".." not in sanitize_filename("../etc/passwd")
    key = build_upload_object_key(
        user_id="user-1",
        thread_id="thread-1",
        filename="../../secret.pdf",
        object_id="oid",
    )
    assert key.startswith("users/user-1/thread-1/oid/")
    assert ".." not in key


def test_local_file_storage_round_trip(tmp_path: Path):
    storage = LocalFileStorage(tmp_path)
    storage.put_bytes(key="users/a/b/file.txt", data=b"hello", content_type="text/plain")
    assert storage.get_bytes("users/a/b/file.txt") == b"hello"
    assert storage.exists("users/a/b/file.txt")
    assert storage.delete_prefix("users/a/") == 1


def test_s3_missing_vs_access_denied():
    class _Client:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {"k": b"v"}

        def get_object(self, *, Bucket: str, Key: str):
            if Key == "missing":
                err = type("NoSuchKey", (Exception,), {})("NoSuchKey")
                raise err
            if Key == "denied":
                err = type("ClientError", (Exception,), {})("AccessDenied")
                err.response = {
                    "Error": {"Code": "AccessDenied"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                }
                raise err
            payload = self.objects[Key]

            class _Body:
                def read(self_inner):
                    return payload

            return {"Body": _Body()}

        def head_object(self, *, Bucket: str, Key: str):
            if Key == "missing":
                err = type("ClientError", (Exception,), {})("404")
                err.response = {
                    "Error": {"Code": "404"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                }
                raise err
            if Key == "denied":
                err = type("ClientError", (Exception,), {})("AccessDenied")
                err.response = {
                    "Error": {"Code": "AccessDenied"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                }
                raise err
            return {}

        def put_object(self, **kwargs):
            return None

        def delete_object(self, **kwargs):
            return None

        def get_paginator(self, _name: str):
            class _Pager:
                def paginate(self, **kwargs):
                    yield {"Contents": []}

            return _Pager()

    client = _Client()
    s3 = S3FileStorage(bucket="uploads-test", region="us-west-2", client=client)
    assert s3.get_bytes("k") == b"v"
    with pytest.raises(FileNotFoundError):
        s3.get_bytes("missing")
    with pytest.raises(Exception) as denied:
        s3.get_bytes("denied")
    assert "AccessDenied" in type(denied.value).__name__ or "AccessDenied" in str(
        denied.value
    )
    assert s3.exists("k") is True
    assert s3.exists("missing") is False
    with pytest.raises(Exception):
        s3.exists("denied")
    assert is_missing_object_error(type("NoSuchKey", (Exception,), {})()) is True


def test_create_file_storage_provider_selection(tmp_path: Path, monkeypatch):
    reset_file_storage_cache()
    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "local")
    monkeypatch.setattr("backend.persistence.factory.settings.files_dir", tmp_path)
    assert isinstance(create_file_storage(), LocalFileStorage)

    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "s3")
    monkeypatch.setattr("backend.persistence.factory.settings.user_uploads_bucket", "bucket")
    monkeypatch.setattr("backend.persistence.factory.settings.aws_region", "us-west-2")
    assert isinstance(create_file_storage(s3_client=object()), S3FileStorage)


def test_create_student_store_defaults_to_sqlite(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "sqlite")
    store = create_student_store(path=tmp_path / "t.sqlite3", identifier="t")
    assert isinstance(store, StudentStore)
    assert not isinstance(store, DsqlStudentStore)


def test_create_student_store_selects_dsql_without_path(monkeypatch):
    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "dsql")
    monkeypatch.setattr(
        "backend.persistence.factory.settings.dsql_endpoint",
        "example.dsql.amazonaws.com",
    )
    monkeypatch.setattr("backend.persistence.factory.settings.aws_region", "us-west-2")
    monkeypatch.setattr(
        "backend.persistence.factory.settings.dsql_user", RUNTIME_ROLE_NAME
    )

    shared: list[str] = []

    def factory() -> _FakeDsqlConnection:
        return _FakeDsqlConnection(shared)

    store = create_student_store(identifier="cognito:test", connection_factory=factory)
    assert isinstance(store, DsqlStudentStore)
    assert store._user == RUNTIME_ROLE_NAME
    joined = "\n".join(shared).upper()
    assert "CREATE TABLE" not in joined
    assert "ALTER TABLE" not in joined
    assert "CREATE INDEX" not in joined
    assert "CREATE UNIQUE INDEX" not in joined


def test_dsql_student_store_rejects_admin_runtime(monkeypatch):
    monkeypatch.setattr("backend.settings.settings.dsql_endpoint", "ep.example")
    monkeypatch.setattr("backend.settings.settings.aws_region", "us-west-2")
    with pytest.raises(ValueError, match="admin"):
        DsqlStudentStore(
            identifier="x",
            user="admin",
            connection_factory=lambda: _FakeDsqlConnection(),
        )


def test_validate_storage_configuration_requires_production_fields(monkeypatch):
    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "dsql")
    monkeypatch.setattr("backend.persistence.factory.settings.dsql_endpoint", "")
    monkeypatch.setattr("backend.persistence.factory.settings.aws_region", "us-west-2")
    monkeypatch.setattr(
        "backend.persistence.factory.settings.dsql_user", RUNTIME_ROLE_NAME
    )
    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "local")
    with pytest.raises(ValueError, match="DSQL_ENDPOINT"):
        validate_storage_configuration()

    monkeypatch.setattr(
        "backend.persistence.factory.settings.dsql_endpoint", "ep.example"
    )
    monkeypatch.setattr("backend.persistence.factory.settings.dsql_user", "admin")
    with pytest.raises(ValueError, match="admin"):
        validate_storage_configuration()

    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "sqlite")
    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "s3")
    monkeypatch.setattr("backend.persistence.factory.settings.user_uploads_bucket", "")
    with pytest.raises(ValueError, match="USER_UPLOADS_BUCKET"):
        validate_storage_configuration()


def test_adapt_sqlite_sql_and_strip_foreign_keys():
    adapted = adapt_sqlite_sql("INSERT OR IGNORE INTO users (id) VALUES (?)")
    assert "%s" in adapted
    assert "ON CONFLICT DO NOTHING" in adapted
    ddl = strip_foreign_keys(
        "CREATE TABLE t (id TEXT PRIMARY KEY, "
        "FOREIGN KEY (id) REFERENCES users(id) ON DELETE CASCADE)"
    )
    assert "FOREIGN KEY" not in ddl.upper()


def test_generate_dsql_auth_token_uses_db_connect_not_admin():
    class _Client:
        def __init__(self) -> None:
            self.called = None

        def generate_db_connect_auth_token(self, **kwargs):
            self.called = ("connect", kwargs)
            return "token-value"

        def generate_db_connect_admin_auth_token(self, **kwargs):  # pragma: no cover
            raise AssertionError("must not use DbConnectAdmin for runtime tokens")

    client = _Client()
    token = generate_dsql_auth_token(
        endpoint="ep.example",
        region="us-west-2",
        client=client,
    )
    assert token == "token-value"
    assert client.called[0] == "connect"
    assert client.called[1]["Hostname"] == "ep.example"


def test_generate_dsql_admin_auth_token_uses_db_connect_admin():
    class _Client:
        def __init__(self) -> None:
            self.called = None

        def generate_db_connect_auth_token(self, **kwargs):  # pragma: no cover
            raise AssertionError("admin bootstrap must not use DbConnect")

        def generate_db_connect_admin_auth_token(self, **kwargs):
            self.called = kwargs
            return "admin-token"

    client = _Client()
    token = generate_dsql_admin_auth_token(
        endpoint="ep.example",
        region="us-west-2",
        client=client,
    )
    assert token == "admin-token"
    assert client.called["Hostname"] == "ep.example"


def test_dsql_schema_has_no_partial_index_where_predicate():
    assert "WHERE cognitoSub" not in DSQL_SCHEMA
    assert "WHERE cognitosub" not in DSQL_SCHEMA.lower()
    assert "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_users_cognito_sub" in DSQL_SCHEMA
    for statement in iter_dsql_ddl_statements():
        upper = statement.upper()
        if "INDEX" in upper:
            assert " WHERE " not in upper
            assert "ASYNC" in upper


def test_run_dsql_transaction_retries_occ_then_succeeds():
    attempts = {"n": 0}

    def work():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _OccError("could not serialize access")
        return "ok"

    assert run_dsql_transaction(work, max_attempts=5, sleep=lambda _s: None) == "ok"
    assert attempts["n"] == 3
    assert is_retryable_db_error(_OccError("x"))


def test_run_dsql_transaction_does_not_retry_non_occ():
    def work():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_dsql_transaction(work, max_attempts=5, sleep=lambda _s: None)


def test_init_dsql_commits_each_ddl_separately_and_waits_for_async_index():
    commits: list[str] = []
    waited: list[str] = []
    job_counter = {"n": 0}

    def connect_fn(**kwargs):
        assert kwargs["user"] == "admin"

        class _Raw:
            def cursor(self):
                class _Cur:
                    description = None
                    rowcount = 0
                    _rows: list = []

                    def execute(self, sql, params=None):
                        commits.append(sql)
                        upper = sql.upper()
                        if "CREATE" in upper and "INDEX ASYNC" in upper:
                            job_counter["n"] += 1
                            self.description = [
                                type("Col", (), {"name": "job_id"})()
                            ]
                            self._rows = [(f"job-{job_counter['n']}",)]
                        elif "WAIT_FOR_JOB" in upper:
                            self.description = [
                                type("Col", (), {"name": "wait_for_job"})()
                            ]
                            self._rows = [(True,)]
                        else:
                            self.description = None
                            self._rows = []

                    def fetchall(self):
                        rows = self._rows
                        self._rows = []
                        return rows

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return None

                return _Cur()

            def commit(self):
                commits.append("COMMIT")

            def rollback(self):
                commits.append("ROLLBACK")

            def close(self):
                return None

        return _Raw()

    def wait_for_job(**kwargs):
        waited.append(kwargs["job_id"])

    statements = [
        "CREATE TABLE IF NOT EXISTS t1 (id TEXT PRIMARY KEY)",
        "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_t1 ON t1(id)",
        "CREATE TABLE IF NOT EXISTS t2 (id TEXT PRIMARY KEY)",
    ]
    assert is_async_index_ddl(statements[1])
    assert not is_async_index_ddl(statements[0])

    # Default token_provider would call admin token; inject a static token.
    admin_tokens: list[str] = []

    def token_provider():
        admin_tokens.append("admin-tok")
        return "admin-tok"

    applied = apply_dsql_schema(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=token_provider,
        statements=statements,
        wait_for_job=wait_for_job,
    )
    assert applied == statements
    assert commits.count("COMMIT") == 3
    assert waited == ["job-1"]
    assert admin_tokens  # admin bootstrap minted tokens
    # Table DDL, then async index, then next table — wait happened between index and t2.
    index_pos = next(
        i for i, sql in enumerate(commits) if "INDEX ASYNC" in sql.upper()
    )
    commit_after_index = next(
        i for i in range(index_pos + 1, len(commits)) if commits[i] == "COMMIT"
    )
    t2_pos = next(i for i, sql in enumerate(commits) if "t2" in sql.lower())
    assert commit_after_index < t2_pos


def test_s3_nosuchbucket_propagates():
    class _Client:
        def get_object(self, *, Bucket: str, Key: str):
            err = type("ClientError", (Exception,), {})("NoSuchBucket")
            err.response = {
                "Error": {"Code": "NoSuchBucket"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            }
            raise err

        def head_object(self, *, Bucket: str, Key: str):
            err = type("ClientError", (Exception,), {})("NoSuchBucket")
            err.response = {
                "Error": {"Code": "NoSuchBucket"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            }
            raise err

    s3 = S3FileStorage(bucket="missing-bucket", region="us-west-2", client=_Client())
    with pytest.raises(Exception) as raised:
        s3.get_bytes("users/a/b.txt")
    assert not isinstance(raised.value, FileNotFoundError)
    assert "NoSuchBucket" in str(raised.value) or getattr(
        raised.value, "response", {}
    ).get("Error", {}).get("Code") == "NoSuchBucket"
    # HTTP 404 alone is not enough when Code is NoSuchBucket.
    assert is_missing_object_error(raised.value) is False
    with pytest.raises(Exception) as head_raised:
        s3.exists("users/a/b.txt")
    assert not isinstance(head_raised.value, FileNotFoundError)


def test_save_uploads_and_workspace_read_via_object_storage(tmp_path: Path, monkeypatch):
    from backend import file_processing
    from backend.persistence.memory_files import MemoryFileStorage
    from backend.source_library import add_file_sources
    from backend.workspace_service import WorkspaceService

    memory = MemoryFileStorage()
    monkeypatch.setattr(file_processing.settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )
    monkeypatch.setattr(
        "backend.source_library.get_file_storage",
        lambda: memory,
        raising=False,
    )
    store = StudentStore(tmp_path / "ws.sqlite3", identifier="owner-1")
    thread_id = store.create_thread(name="n", model_id="m", support_mode="guided")
    created = add_file_sources(
        store,
        thread_id,
        [("note.txt", b"hello-s3-bytes", "text/plain")],
    )
    assert len(created) == 1
    source = created[0]
    assert (source.get("metadata") or {}).get("storage_provider") == "memory"
    assert source["path"] in memory._objects or memory.exists(str(source["path"]))

    service = WorkspaceService(store)
    content = service.read_source_content(thread_id, source["id"])
    assert content.data == b"hello-s3-bytes"
    assert content.filename
