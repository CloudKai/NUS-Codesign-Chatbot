"""Deterministic mocked tests for admin DSQL schema bootstrap (no AWS)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

from backend.persistence.dsql_schema import DSQL_SCHEMA, iter_dsql_ddl_statements

_INIT_DSQL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "init_dsql.py"
_SPEC = importlib.util.spec_from_file_location("co_design_init_dsql_tests", _INIT_DSQL_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_INIT_DSQL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_INIT_DSQL)

apply_dsql_schema = _INIT_DSQL.apply_dsql_schema
apply_missing_revision_columns = _INIT_DSQL.apply_missing_revision_columns
plan_missing_message_revision_statements = _INIT_DSQL.plan_missing_message_revision_statements
plan_missing_notebooks_conversation_revision_statements = (
    _INIT_DSQL.plan_missing_notebooks_conversation_revision_statements
)


def _messages_create_sql() -> str:
    """Return the CREATE TABLE statement for messages from the DSQL schema."""
    for statement in iter_dsql_ddl_statements():
        if statement.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS MESSAGES"):
            return statement
    raise AssertionError("messages CREATE TABLE missing from DSQL schema")


def test_fresh_messages_schema_includes_revision_columns_only():
    """Fresh messages DDL carries revision columns and no user-identity fields."""
    messages_sql = _messages_create_sql()
    assert "conversation_revision INTEGER NOT NULL DEFAULT 0" in messages_sql
    assert "previous_message_id TEXT NULL" in messages_sql
    assert "superseded_at_revision INTEGER NULL" in messages_sql
    for forbidden in ("user_id", "cognito_sub", "email", "display_name"):
        assert forbidden not in messages_sql

    notebooks_sql = next(
        statement
        for statement in iter_dsql_ddl_statements()
        if statement.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS NOTEBOOKS")
    )
    assert "conversation_revision INTEGER NOT NULL DEFAULT 0" in notebooks_sql
    assert "conversation_revision INTEGER NOT NULL DEFAULT 0" in DSQL_SCHEMA


def test_plan_missing_notebooks_conversation_revision_additive_and_idempotent():
    """Notebooks planner emits ADD/DEFAULT/backfill only when the CAS column is absent."""
    empty = plan_missing_notebooks_conversation_revision_statements(set())
    assert empty == [
        "ALTER TABLE notebooks ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0",
        "UPDATE notebooks SET conversation_revision = 0 "
        "WHERE conversation_revision IS NULL",
    ]
    assert plan_missing_notebooks_conversation_revision_statements(
        {"id", "user_id", "conversation_revision"}
    ) == []


def test_plan_missing_message_revision_statements_additive_and_idempotent():
    """Message planner emits one statement per missing column follow-up; no-ops when present."""
    empty = plan_missing_message_revision_statements(set())
    assert empty == [
        "ALTER TABLE messages ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE messages ALTER COLUMN conversation_revision SET DEFAULT 0",
        "UPDATE messages SET conversation_revision = 0 "
        "WHERE conversation_revision IS NULL",
        "ALTER TABLE messages ADD COLUMN previous_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER",
    ]
    assert all(
        not statement.upper().startswith("ALTER TABLE NOTEBOOKS") for statement in empty
    )

    partial = plan_missing_message_revision_statements({"conversation_revision"})
    assert partial == [
        "ALTER TABLE messages ADD COLUMN previous_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER",
    ]

    complete = plan_missing_message_revision_statements(
        {
            "conversation_revision",
            "previous_message_id",
            "superseded_at_revision",
            "id",
            "notebook_id",
        }
    )
    assert complete == []


class _CatalogAwareRaw:
    """Minimal admin connection stand-in with mutable table column catalogs."""

    def __init__(self, catalog: dict[str, set[str]], recorder: list[str]):
        self._catalog = catalog
        self._recorder = recorder

    def cursor(self):
        catalog = self._catalog
        recorder = self._recorder

        class _Cur:
            description = None
            rowcount = 0
            _rows: list[tuple[Any, ...]] = []

            def execute(self, sql, params=None):
                recorder.append(sql)
                upper = " ".join(sql.upper().split())
                if "INFORMATION_SCHEMA.COLUMNS" in upper:
                    table = (params or (None,))[0]
                    columns = sorted(catalog.get(str(table), set()))
                    self.description = [type("Col", (), {"name": "column_name"})()]
                    self._rows = [(name,) for name in columns]
                    return
                add_match = re.search(
                    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)\s+",
                    sql,
                    flags=re.IGNORECASE,
                )
                if add_match:
                    table_name = add_match.group(1).lower()
                    column_name = add_match.group(2)
                    catalog.setdefault(table_name, set()).add(column_name)
                self.description = None
                self._rows = []

            def fetchall(self):
                rows = self._rows
                self._rows = []
                return rows

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

        return _Cur()

    def commit(self):
        self._recorder.append("COMMIT")

    def rollback(self):
        self._recorder.append("ROLLBACK")

    def close(self):
        return None


_LEGACY_NOTEBOOKS = {
    "id",
    "user_id",
    "title",
    "current_stage",
    "progress_text",
    "settings_text",
    "created_at",
    "updated_at",
}

_LEGACY_MESSAGES = {
    "id",
    "notebook_id",
    "role",
    "content",
    "is_error",
    "assessment_text",
    "cited_source_ids_text",
    "proposed_stage",
    "decision_status",
    "decision_at",
    "metadata_text",
    "created_at",
}


def test_apply_missing_revision_columns_is_catalog_driven_and_idempotent():
    """Admin migration ALTERs notebooks CAS then message columns; second pass is empty."""
    catalog = {
        "notebooks": set(_LEGACY_NOTEBOOKS),
        "messages": set(_LEGACY_MESSAGES),
    }
    recorder: list[str] = []

    def connect_fn(**kwargs):
        assert kwargs["user"] == "admin"
        assert kwargs["autocommit"] is False
        return _CatalogAwareRaw(catalog, recorder)

    first = apply_missing_revision_columns(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
    )
    assert first == [
        "ALTER TABLE notebooks ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0",
        "UPDATE notebooks SET conversation_revision = 0 "
        "WHERE conversation_revision IS NULL",
        "ALTER TABLE messages ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE messages ALTER COLUMN conversation_revision SET DEFAULT 0",
        "UPDATE messages SET conversation_revision = 0 "
        "WHERE conversation_revision IS NULL",
        "ALTER TABLE messages ADD COLUMN previous_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER",
    ]
    # One catalog read commit + one commit per applied statement.
    assert recorder.count("COMMIT") == 1 + len(first)
    assert any("INFORMATION_SCHEMA.COLUMNS" in sql.upper() for sql in recorder)
    assert "conversation_revision" in catalog["notebooks"]
    assert {
        "conversation_revision",
        "previous_message_id",
        "superseded_at_revision",
    }.issubset(catalog["messages"])

    recorder.clear()
    second = apply_missing_revision_columns(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
    )
    assert second == []
    assert recorder.count("COMMIT") == 1
    assert not any("ADD COLUMN" in sql.upper() for sql in recorder)


def test_apply_dsql_schema_runs_revision_migration_only_on_full_bootstrap():
    """Custom statement lists skip catalog migration; opt-in bootstrap includes it."""
    catalog = {
        "notebooks": set(_LEGACY_NOTEBOOKS),
        "messages": set(_LEGACY_MESSAGES),
    }
    recorder: list[str] = []

    def connect_fn(**kwargs):
        return _CatalogAwareRaw(catalog, recorder)

    custom = apply_dsql_schema(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
        statements=["CREATE TABLE IF NOT EXISTS t1 (id TEXT PRIMARY KEY)"],
        wait_for_job=lambda **kwargs: None,
    )
    assert custom == ["CREATE TABLE IF NOT EXISTS t1 (id TEXT PRIMARY KEY)"]
    assert not any("ADD COLUMN" in sql.upper() for sql in recorder)

    recorder.clear()
    catalog["notebooks"] = set(_LEGACY_NOTEBOOKS)
    catalog["messages"] = set(_LEGACY_MESSAGES)

    create_only = [
        statement
        for statement in iter_dsql_ddl_statements()
        if statement.lstrip().upper().startswith("CREATE TABLE")
    ]
    applied = apply_dsql_schema(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
        statements=create_only,
        wait_for_job=lambda **kwargs: None,
        migrate_message_revisions=True,
    )
    assert any(
        "ALTER TABLE notebooks ADD COLUMN conversation_revision" in item
        for item in applied
    )
    assert any(
        "ALTER TABLE messages ADD COLUMN conversation_revision" in item
        for item in applied
    )
    assert any("ADD COLUMN previous_message_id" in item for item in applied)
    assert any("ADD COLUMN superseded_at_revision" in item for item in applied)
    assert applied[: len(create_only)] == create_only
    notebooks_pos = next(
        i
        for i, item in enumerate(applied)
        if "ALTER TABLE notebooks ADD COLUMN conversation_revision" in item
    )
    messages_pos = next(
        i
        for i, item in enumerate(applied)
        if "ALTER TABLE messages ADD COLUMN conversation_revision" in item
    )
    assert notebooks_pos < messages_pos
