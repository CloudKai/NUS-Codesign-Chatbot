"""Deterministic tests for storage providers and DSQL/S3 adapters (no AWS calls)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from backend.persistence.dsql_connection import (
    adapt_sqlite_sql,
    connect_dsql,
    generate_dsql_admin_auth_token,
    generate_dsql_auth_token,
    is_retryable_db_error,
    run_dsql_transaction,
    strip_foreign_keys,
)
from backend.persistence.dsql_schema import (
    DSQL_SCHEMA,
    RUNTIME_GRANT_SQL,
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
from backend.persistence.object_keys import (
    build_extracted_text_object_key,
    build_upload_object_key,
    notebook_prefix,
    sanitize_filename,
)
from backend.persistence.s3_files import (
    S3DeleteObjectsError,
    S3FileStorage,
    is_missing_object_error,
)
from backend.settings import settings
from backend.student_store import StudentStore

_INIT_DSQL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "init_dsql.py"
_SPEC = importlib.util.spec_from_file_location("co_design_init_dsql", _INIT_DSQL_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_INIT_DSQL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_INIT_DSQL)
apply_dsql_schema = _INIT_DSQL.apply_dsql_schema
is_async_index_ddl = _INIT_DSQL.is_async_index_ddl
_job_id_from_result = _INIT_DSQL._job_id_from_result
wait_for_async_index_job = _INIT_DSQL.wait_for_async_index_job


class _OccError(Exception):
    """Fake psycopg serialization failure."""

    sqlstate = "40001"


class _FakeDsqlConnection:
    """Minimal DSQL connection stand-in that records SQL and never talks to AWS."""

    def __init__(
        self, recorder: list[str] | None = None, *, research_ready: bool = True
    ):
        self.recorder = recorder if recorder is not None else []
        self.closed = False
        self._rows: dict[str, Any] = {}
        self.research_ready = research_ready

    def execute(self, sql: str, params: Any = None) -> Any:
        self.recorder.append(sql.strip())
        upper = sql.strip().upper()
        if upper.startswith("SELECT VALUE_TEXT FROM SYSTEM_METADATA WHERE KEY"):
            payload = (
                '{"version":"cde2300-five-phase-v1"}'
                if self.research_ready
                else None
            )

            class _R:
                def fetchone(self_inner):
                    return {"value_text": payload} if payload else None

            return _R()
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
        notebook_id="notebook-1",
        source_id="../../oid",
        filename="../../secret.pdf",
    )
    assert key == "users/user-1/notebooks/notebook-1/sources/oid/raw/secret.pdf"
    assert ".." not in key
    assert notebook_prefix(
        user_id="user-1", notebook_id="../notebook-1"
    ) == "users/user-1/notebooks/notebook-1/"
    assert build_extracted_text_object_key(
        user_id="user-1",
        notebook_id="notebook-1",
        source_id="source-1",
    ) == "users/user-1/notebooks/notebook-1/sources/source-1/derived/extracted.txt"


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


def test_s3_delete_prefix_raises_on_returned_object_errors():
    class _Paginator:
        def paginate(self, **_kwargs):
            yield {"Contents": [{"Key": "users/u/n/a"}, {"Key": "users/u/n/b"}]}

    class _Client:
        def __init__(self, *, fail: bool):
            self.fail = fail

        def get_paginator(self, name: str):
            assert name == "list_objects_v2"
            return _Paginator()

        def delete_objects(self, **_kwargs):
            if self.fail:
                return {
                    "Errors": [
                        {
                            "Key": "users/u/n/b",
                            "Code": "AccessDenied",
                            "Message": "denied",
                        }
                    ]
                }
            return {}

    failing = S3FileStorage(
        bucket="uploads-test",
        region="us-west-2",
        client=_Client(fail=True),
    )
    with pytest.raises(S3DeleteObjectsError, match="AccessDenied") as raised:
        failing.delete_prefix("users/u/n/")
    assert raised.value.errors[0]["Key"] == "users/u/n/b"

    successful = S3FileStorage(
        bucket="uploads-test",
        region="us-west-2",
        client=_Client(fail=False),
    )
    assert successful.delete_prefix("users/u/n/") == 2


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


def test_dsql_readiness_checks_all_runtime_tables_and_contract_marker():
    recorder: list[str] = []
    store = DsqlStudentStore(
        identifier="__readiness__",
        ensure_owner=False,
        connection_factory=lambda: _FakeDsqlConnection(recorder),
    )

    store.ping()

    joined = "\n".join(recorder).lower()
    for table in (
        "users",
        "oauth_login_states",
        "notebooks",
        "messages",
        "sources",
        "research_observations",
        "research_reviews",
        "research_adjudications",
        "research_access_events",
        "system_metadata",
    ):
        assert f"select * from {table} limit 0" in joined
    assert "select value_text from system_metadata where key" in joined


def test_dsql_readiness_fails_without_explicit_workflow_contract_marker():
    store = DsqlStudentStore(
        identifier="__readiness__",
        ensure_owner=False,
        connection_factory=lambda: _FakeDsqlConnection(research_ready=False),
    )

    with pytest.raises(RuntimeError, match="workflow contract"):
        store.ping()


def test_dsql_notebook_delete_uses_observation_joins_for_research_children(
    monkeypatch,
):
    recorder: list[str] = []
    store = DsqlStudentStore(
        identifier="__delete__",
        ensure_owner=False,
        connection_factory=lambda: _FakeDsqlConnection(recorder),
    )
    store.owner_id = "owner-1"
    monkeypatch.setattr(store, "get_thread", lambda _thread_id: {"id": "notebook-1"})
    monkeypatch.setattr(store, "_cleanup_notebook_files", lambda _thread_id: None)

    store.delete_thread("notebook-1")

    deletes = [sql.lower() for sql in recorder if sql.upper().startswith("DELETE")]
    assert "delete from research_adjudications where observation_id in" in deletes[0]
    assert "delete from research_reviews where observation_id in" in deletes[1]
    assert "from research_observations where notebook_id = ?" in deletes[0]
    assert "from research_observations where notebook_id = ?" in deletes[1]
    assert deletes[2].startswith(
        "delete from research_access_events where notebook_id = ?"
    )
    assert deletes[3].startswith(
        "delete from research_observations where notebook_id = ?"
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
    explicit_upsert = adapt_sqlite_sql(
        "INSERT INTO oauth_login_states "
        "(state, code_verifier, created_at, expires_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (state) DO UPDATE SET "
        "code_verifier=excluded.code_verifier"
    )
    assert "ON CONFLICT (state)" in explicit_upsert
    assert explicit_upsert.count("%s") == 4
    with pytest.raises(ValueError, match="explicit ON CONFLICT"):
        adapt_sqlite_sql(
            "INSERT OR REPLACE INTO oauth_login_states "
            "(state, code_verifier) VALUES (?, ?)"
        )
    ddl = strip_foreign_keys(
        "CREATE TABLE t (id TEXT PRIMARY KEY, "
        "FOREIGN KEY (id) REFERENCES users(id) ON DELETE CASCADE)"
    )
    assert "FOREIGN KEY" not in ddl.upper()


def test_adapt_sqlite_sql_escapes_like_percent_literals_for_psycopg():
    """Notebook list filters use LIKE '%%...%%' literals that psycopg must not parse."""
    sql = (
        "SELECT n.id, COUNT(CASE WHEN m.metadata_text NOT LIKE "
        "'%\"_internal_type\": \"coach_idempotency\"%' THEN m.id END) AS c "
        "FROM notebooks n LEFT JOIN messages m ON m.notebook_id=n.id "
        "WHERE n.user_id = ?"
    )
    adapted = adapt_sqlite_sql(sql)
    assert adapted.count("%s") == 1
    assert '%%"_internal_type": "coach_idempotency"%%' in adapted
    # Unescaped single-% before the quote must not remain (psycopg rejects '%"').
    assert "%\"_internal_type\"" not in adapted.replace("%%", "")


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


def test_connect_dsql_uses_verify_full_system_ca():
    captured: dict[str, object] = {}

    def connect_fn(**kwargs):
        captured.update(kwargs)

        class _Raw:
            def close(self):
                return None

            def commit(self):
                return None

            def rollback(self):
                return None

            def cursor(self):
                raise AssertionError("connect_dsql should not query during open")

        return _Raw()

    proxy = connect_dsql(
        endpoint="example.dsql.amazonaws.com",
        region="us-west-2",
        user="co_design_app",
        token_provider=lambda: "tok",
        connect_fn=connect_fn,
    )
    assert captured["sslmode"] == "verify-full"
    assert captured["sslrootcert"] == "system"
    assert captured["user"] == "co_design_app"
    assert captured["password"] == "tok"
    proxy.close()


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
    assert "WHERE cognito_sub" not in DSQL_SCHEMA
    assert "WHERE cognitosub" not in DSQL_SCHEMA.lower()
    assert "identifier TEXT NOT NULL UNIQUE" not in DSQL_SCHEMA
    assert "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_users_identifier" in DSQL_SCHEMA
    assert "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_users_cognito_sub" in DSQL_SCHEMA
    assert "app_sessions" not in DSQL_SCHEMA
    assert "CREATE TABLE IF NOT EXISTS notebooks" in DSQL_SCHEMA
    assert "CREATE TABLE IF NOT EXISTS messages" in DSQL_SCHEMA
    assert "CREATE TABLE IF NOT EXISTS sources" in DSQL_SCHEMA
    assert "CREATE TABLE IF NOT EXISTS oauth_login_states" in DSQL_SCHEMA
    assert "current_stage TEXT NOT NULL DEFAULT 'problem_identification'" in DSQL_SCHEMA
    for research_table in (
        "research_observations",
        "research_reviews",
        "research_adjudications",
        "research_access_events",
        "system_metadata",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {research_table}" in DSQL_SCHEMA
    assert "FOREIGN KEY" not in DSQL_SCHEMA.upper()
    for legacy in (
        "threads",
        "steps",
        "folders",
        "feedbacks",
        "model_turns",
        "openai_thread_state",
        "notebook_sources",
        "phase_transitions",
        "app_sessions",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {legacy}" not in DSQL_SCHEMA
    for statement in iter_dsql_ddl_statements():
        upper = statement.upper()
        if "INDEX" in upper:
            assert " WHERE " not in upper
            assert "ASYNC" in upper


def test_dsql_non_primary_uniqueness_uses_async_indexes():
    """Keep DSQL secondary uniqueness explicit so bootstrap waits for each job."""
    table_statements = [
        statement
        for statement in iter_dsql_ddl_statements()
        if statement.lstrip().upper().startswith("CREATE TABLE")
    ]
    assert all(" UNIQUE" not in statement.upper() for statement in table_statements)


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
        assert kwargs["sslmode"] == "verify-full"
        assert kwargs["sslrootcert"] == "system"
        assert kwargs["autocommit"] is False

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
    assert admin_tokens
    index_pos = next(
        i for i, sql in enumerate(commits) if "INDEX ASYNC" in sql.upper()
    )
    commit_after_index = next(
        i for i in range(index_pos + 1, len(commits)) if commits[i] == "COMMIT"
    )
    t2_pos = next(i for i, sql in enumerate(commits) if "t2" in sql.lower())
    assert commit_after_index < t2_pos


def test_wait_for_async_index_job_calls_procedure_on_autocommit_connection():
    connections: list[dict[str, Any]] = []
    executed: list[tuple[str, tuple[Any, ...]]] = []
    closed: list[bool] = []

    def connect_fn(**kwargs):
        connections.append(kwargs)

        class _Raw:
            def cursor(self):
                class _Cur:
                    description = None
                    rowcount = 0

                    def execute(self, sql, params=None):
                        executed.append((sql, tuple(params or ())))

                    def fetchall(self):  # pragma: no cover - no CALL result set
                        raise AssertionError("CALL must not be treated as SELECT")

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return None

                return _Cur()

            def commit(self):  # pragma: no cover - autocommit CALL only
                raise AssertionError("wait procedure must not commit a transaction")

            def rollback(self):  # pragma: no cover - autocommit CALL only
                raise AssertionError("wait procedure must not roll back a transaction")

            def close(self):
                closed.append(True)

        return _Raw()

    wait_for_async_index_job(
        job_id="job-live-shape",
        endpoint="ep.example",
        region="us-west-2",
        database="postgres",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-token",
    )

    assert len(connections) == 1
    assert connections[0]["autocommit"] is True
    assert connections[0]["sslmode"] == "verify-full"
    assert connections[0]["sslrootcert"] == "system"
    assert executed == [("CALL sys.wait_for_job(%s)", ("job-live-shape",))]
    assert closed == [True]


def test_dsql_runtime_grant_excludes_public_schema_usage():
    normalized = " ".join(RUNTIME_GRANT_SQL.split())
    assert "GRANT USAGE ON SCHEMA public" not in RUNTIME_GRANT_SQL
    assert normalized == (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "TO co_design_app;"
    )


def test_init_dsql_skips_wait_when_async_index_already_exists():
    """IF NOT EXISTS with no job_id row must not wait or fail."""
    commits: list[str] = []
    waited: list[str] = []
    index_calls = {"n": 0}

    def connect_fn(**kwargs):
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
                            index_calls["n"] += 1
                            # First call submits a job; second finds existing index.
                            if index_calls["n"] == 1:
                                self.description = [
                                    type("Col", (), {"name": "job_id"})()
                                ]
                                self._rows = [("job-new",)]
                            else:
                                self.description = [
                                    type("Col", (), {"name": "job_id"})()
                                ]
                                self._rows = []
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
        "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_t1 ON t1(id)",
        "CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_t1 ON t1(id)",
        "CREATE TABLE IF NOT EXISTS t2 (id TEXT PRIMARY KEY)",
    ]
    applied = apply_dsql_schema(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "tok",
        statements=statements,
        wait_for_job=wait_for_job,
    )
    assert applied == statements
    assert waited == ["job-new"]
    assert commits.count("COMMIT") == 3
    assert any("t2" in sql.lower() for sql in commits)
    assert _job_id_from_result(None) is None

    class _Empty:
        def fetchone(self):
            return None

    assert _job_id_from_result(_Empty()) is None


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
    assert source["object_key"]
    assert f"/sources/{source['id']}/" in source["object_key"]
    assert "/notebooks/" in source["object_key"]
    assert source["extracted_text_key"]
    assert (
        f"/sources/{source['id']}/derived/extracted.txt"
        in source["extracted_text_key"]
    )
    assert memory.get_bytes(source["extracted_text_key"]) == b"hello-s3-bytes"
    database_bytes = (tmp_path / "ws.sqlite3").read_bytes()
    assert b"hello-s3-bytes" not in database_bytes

    service = WorkspaceService(store)
    content = service.read_source_content(thread_id, source["id"])
    assert content.data == b"hello-s3-bytes"
    assert content.filename
    store.delete_source(thread_id, source["id"])
    assert not memory.exists(source["object_key"])
    assert not memory.exists(source["extracted_text_key"])


def test_raw_extracted_txt_never_collides_with_derived_text(tmp_path: Path, monkeypatch):
    """Raw bytes remain byte-perfect when the filename is ``extracted.txt``."""
    from backend import file_processing
    from backend.source_library import add_file_sources

    memory = MemoryFileStorage()
    monkeypatch.setattr(file_processing.settings, "file_storage_provider", "memory")
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )
    store = StudentStore(tmp_path / "key-collision.sqlite3", identifier="owner-1")
    notebook_id = store.create_thread(model_id="mock", support_mode="guided")
    original = b"a" * 130_000

    source = add_file_sources(
        store,
        notebook_id,
        [("extracted.txt", original, "text/plain")],
        compress=False,
    )[0]

    assert source["object_key"] != source["extracted_text_key"]
    assert "/raw/extracted.txt" in source["object_key"]
    assert "/derived/extracted.txt" in source["extracted_text_key"]
    assert memory.get_bytes(source["object_key"]) == original


def test_object_upload_batch_is_prevalidated_and_cleans_failed_puts(
    tmp_path: Path, monkeypatch
):
    """A later invalid file or object-store error leaves no partial batch."""
    from backend import file_processing

    memory = MemoryFileStorage()
    monkeypatch.setattr(file_processing.settings, "file_storage_provider", "memory")
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )

    with pytest.raises(ValueError, match="exceeds"):
        file_processing.save_uploads(
            "notebook-1",
            [
                ("first.txt", b"ok", "text/plain"),
                ("too-large.txt", b"x" * (1024 * 1024 + 1), "text/plain"),
            ],
            max_file_size_mb=1,
            compress=False,
            owner_id="owner-1",
            source_ids=["source-1", "source-2"],
        )
    assert memory._objects == {}

    class FailSecondPutStorage(MemoryFileStorage):
        def __init__(self) -> None:
            super().__init__()
            self.put_count = 0

        def put_bytes(self, **kwargs):
            self.put_count += 1
            if self.put_count == 2:
                raise PermissionError("AccessDenied")
            return super().put_bytes(**kwargs)

    failing = FailSecondPutStorage()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: failing,
    )
    with pytest.raises(PermissionError, match="AccessDenied"):
        file_processing.save_uploads(
            "notebook-1",
            [
                ("first.txt", b"one", "text/plain"),
                ("second.txt", b"two", "text/plain"),
            ],
            compress=False,
            owner_id="owner-1",
            source_ids=["source-1", "source-2"],
        )
    assert failing._objects == {}


def test_source_delete_propagates_storage_failures(tmp_path: Path, monkeypatch):
    class _FailingDeleteStorage(MemoryFileStorage):
        def delete_prefix(self, prefix: str) -> int:
            raise PermissionError(f"AccessDenied: {prefix}")

    storage = _FailingDeleteStorage()
    monkeypatch.setattr(settings, "file_storage_provider", "memory")
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: storage,
    )
    store = StudentStore(tmp_path / "delete-failure.sqlite3", identifier="owner-1")
    notebook_id = store.create_thread(name="n", model_id="m", support_mode="guided")
    source_id = store.add_source(
        notebook_id,
        kind="file",
        title="raw.txt",
        path="users/placeholder",
        metadata={"storage_provider": "memory"},
    )
    prefix = (
        f"users/{sanitize_filename(store.owner_id)}/notebooks/"
        f"{sanitize_filename(notebook_id)}/sources/{sanitize_filename(source_id)}/"
    )
    storage.put_bytes(key=f"{prefix}raw.txt", data=b"raw")

    with pytest.raises(PermissionError, match="AccessDenied"):
        store.delete_source(notebook_id, source_id)
    assert store.get_source(notebook_id, source_id) is None
    assert storage.exists(f"{prefix}raw.txt")
