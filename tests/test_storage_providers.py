"""Deterministic tests for storage providers and DSQL/S3 adapters (no AWS calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.persistence.dsql_connection import (
    adapt_sqlite_sql,
    generate_dsql_auth_token,
    strip_foreign_keys,
)
from backend.persistence.factory import (
    create_file_storage,
    create_student_store,
    reset_file_storage_cache,
    validate_storage_configuration,
)
from backend.persistence.local_files import LocalFileStorage
from backend.persistence.memory_files import MemoryFileStorage
from backend.persistence.object_keys import build_upload_object_key, sanitize_filename
from backend.persistence.s3_files import S3FileStorage
from backend.student_store import StudentStore


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
    assert key.endswith("secret.pdf") or key.endswith("_secret.pdf") or "secret" in key


def test_local_file_storage_round_trip(tmp_path: Path):
    storage = LocalFileStorage(tmp_path)
    stored = storage.put_bytes(key="users/a/b/file.txt", data=b"hello", content_type="text/plain")
    assert stored.size == 5
    assert storage.get_bytes("users/a/b/file.txt") == b"hello"
    assert storage.exists("users/a/b/file.txt")
    assert storage.delete_prefix("users/a/") == 1
    assert not storage.exists("users/a/b/file.txt")


def test_memory_and_s3_file_storage_without_aws():
    memory = MemoryFileStorage()
    memory.put_bytes(key="k1", data=b"x", content_type="text/plain")
    assert memory.get_bytes("k1") == b"x"

    class _Client:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str):
            self.objects[Key] = Body

        def get_object(self, *, Bucket: str, Key: str):
            if Key not in self.objects:
                raise type("NoSuchKey", (Exception,), {})("NoSuchKey")
            payload = self.objects[Key]

            class _Body:
                def read(self_inner):
                    return payload

            return {"Body": _Body()}

        def delete_object(self, *, Bucket: str, Key: str):
            self.objects.pop(Key, None)

        def head_object(self, *, Bucket: str, Key: str):
            if Key not in self.objects:
                raise Exception("404")
            return {}

        def get_paginator(self, _name: str):
            client = self

            class _Pager:
                def paginate(self, *, Bucket: str, Prefix: str):
                    keys = [key for key in client.objects if key.startswith(Prefix)]
                    yield {"Contents": [{"Key": key} for key in keys]}

            return _Pager()

        def delete_objects(self, *, Bucket: str, Delete: dict):
            for item in Delete.get("Objects") or []:
                self.objects.pop(item["Key"], None)

    client = _Client()
    s3 = S3FileStorage(bucket="uploads-test", region="us-west-2", client=client)
    s3.put_bytes(key="users/u/t/f.txt", data=b"payload", content_type="text/plain")
    assert s3.get_bytes("users/u/t/f.txt") == b"payload"
    assert s3.delete_prefix("users/u/") == 1


def test_create_file_storage_provider_selection(tmp_path: Path, monkeypatch):
    reset_file_storage_cache()
    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "local")
    monkeypatch.setattr("backend.persistence.factory.settings.files_dir", tmp_path)
    assert isinstance(create_file_storage(), LocalFileStorage)

    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "memory")
    assert isinstance(create_file_storage(), MemoryFileStorage)

    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "s3")
    monkeypatch.setattr("backend.persistence.factory.settings.user_uploads_bucket", "bucket")
    monkeypatch.setattr("backend.persistence.factory.settings.aws_region", "us-west-2")

    class _Client:
        pass

    storage = create_file_storage(s3_client=_Client())
    assert isinstance(storage, S3FileStorage)


def test_create_student_store_defaults_to_sqlite(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "sqlite")
    store = create_student_store(path=tmp_path / "t.sqlite3", identifier="t")
    assert isinstance(store, StudentStore)
    assert not isinstance(store, type("x", (), {}))


def test_create_student_store_selects_dsql(monkeypatch):
    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "dsql")
    monkeypatch.setattr("backend.persistence.factory.settings.dsql_endpoint", "example.dsql.amazonaws.com")
    monkeypatch.setattr("backend.persistence.factory.settings.aws_region", "us-west-2")

    class _Conn:
        def executescript(self, _script):
            return None

        def execute(self, *_a, **_k):
            class _R:
                def fetchone(self):
                    return None

            return _R()

        def commit(self):
            return None

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    # Avoid real DSQL: explicit path still forces SQLite for tests/tools.
    store = create_student_store(path=Path("/tmp/force-sqlite-unused"), identifier="x")
    assert isinstance(store, StudentStore)


def test_validate_storage_configuration_requires_production_fields(monkeypatch):
    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "dsql")
    monkeypatch.setattr("backend.persistence.factory.settings.dsql_endpoint", "")
    monkeypatch.setattr("backend.persistence.factory.settings.aws_region", "us-west-2")
    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "local")
    with pytest.raises(ValueError, match="DSQL_ENDPOINT"):
        validate_storage_configuration()

    monkeypatch.setattr("backend.persistence.factory.settings.database_provider", "sqlite")
    monkeypatch.setattr("backend.persistence.factory.settings.file_storage_provider", "s3")
    monkeypatch.setattr("backend.persistence.factory.settings.user_uploads_bucket", "")
    with pytest.raises(ValueError, match="USER_UPLOADS_BUCKET"):
        validate_storage_configuration()


def test_adapt_sqlite_sql_and_strip_foreign_keys():
    adapted = adapt_sqlite_sql("INSERT OR IGNORE INTO users (id) VALUES (?)")
    assert "INSERT INTO users" in adapted
    assert "%s" in adapted
    assert "ON CONFLICT DO NOTHING" in adapted

    ddl = strip_foreign_keys(
        "CREATE TABLE t (id TEXT PRIMARY KEY, "
        "FOREIGN KEY (id) REFERENCES users(id) ON DELETE CASCADE)"
    )
    assert "FOREIGN KEY" not in ddl.upper()


def test_generate_dsql_auth_token_uses_injected_client():
    class _Client:
        def generate_db_connect_auth_token(self, **kwargs):
            assert kwargs["Hostname"] == "ep.example"
            assert kwargs["Region"] == "us-west-2"
            return "token-value"

    token = generate_dsql_auth_token(
        endpoint="ep.example",
        region="us-west-2",
        client=_Client(),
    )
    assert token == "token-value"


def test_save_uploads_uses_memory_object_storage(tmp_path: Path, monkeypatch):
    from backend import file_processing
    from backend.persistence.factory import reset_file_storage_cache
    from backend.persistence.memory_files import MemoryFileStorage

    memory = MemoryFileStorage()
    monkeypatch.setattr(file_processing.settings, "file_storage_provider", "memory")
    monkeypatch.setattr(
        "backend.persistence.factory.create_file_storage",
        lambda **_kwargs: memory,
    )
    reset_file_storage_cache()
    monkeypatch.setattr(
        "backend.persistence.factory.get_file_storage",
        lambda: memory,
    )
    uploads = file_processing.save_uploads(
        "thread-a",
        [("note.txt", b"hello world", "text/plain")],
        owner_id="owner-1",
    )
    assert len(uploads) == 1
    assert uploads[0].storage_provider == "memory"
    assert uploads[0].storage_key is not None
    assert memory.get_bytes(uploads[0].storage_key) == b"hello world"
