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
apply_revision_null_backfills = _INIT_DSQL.apply_revision_null_backfills
build_revision_null_backfill_update = _INIT_DSQL.build_revision_null_backfill_update
column_default_is_zero = _INIT_DSQL.column_default_is_zero
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


def test_column_default_is_zero_recognizes_catalog_forms():
    assert column_default_is_zero("0") is True
    assert column_default_is_zero("0::integer") is True
    assert column_default_is_zero("(0)") is True
    assert column_default_is_zero(None) is False
    assert column_default_is_zero("") is False
    assert column_default_is_zero("1") is False


def test_plan_missing_notebooks_conversation_revision_additive_and_idempotent():
    """Notebooks planner emits ADD/DEFAULT; name-only presence is a no-op."""
    empty = plan_missing_notebooks_conversation_revision_statements(set())
    assert empty == [
        "ALTER TABLE notebooks ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0",
    ]
    assert plan_missing_notebooks_conversation_revision_statements(
        {"id", "user_id", "conversation_revision"}
    ) == []
    assert plan_missing_notebooks_conversation_revision_statements(
        {"conversation_revision"},
        default_is_zero=True,
    ) == []
    assert plan_missing_notebooks_conversation_revision_statements(
        {"conversation_revision"},
        default_is_zero=False,
    ) == [
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0",
    ]


def test_plan_missing_message_revision_statements_additive_and_idempotent():
    """Message planner emits ADD/DEFAULT repair without unbounded UPDATE."""
    empty = plan_missing_message_revision_statements(set())
    assert empty == [
        "ALTER TABLE messages ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE messages ALTER COLUMN conversation_revision SET DEFAULT 0",
        "ALTER TABLE messages ADD COLUMN previous_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER",
    ]
    assert all(
        not statement.upper().startswith("ALTER TABLE NOTEBOOKS") for statement in empty
    )
    assert all("UPDATE " not in statement.upper() for statement in empty)

    partial = plan_missing_message_revision_statements({"conversation_revision"})
    assert partial == [
        "ALTER TABLE messages ADD COLUMN previous_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER",
    ]
    assert plan_missing_message_revision_statements(
        {"conversation_revision"},
        revision_default_is_zero=False,
    ) == [
        "ALTER TABLE messages ADD COLUMN previous_message_id TEXT",
        "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER",
        "ALTER TABLE messages ALTER COLUMN conversation_revision SET DEFAULT 0",
    ]

    complete = plan_missing_message_revision_statements(
        {
            "conversation_revision",
            "previous_message_id",
            "superseded_at_revision",
            "id",
            "notebook_id",
        },
        revision_default_is_zero=True,
    )
    assert complete == []


def test_build_revision_null_backfill_update_batches_ids():
    assert build_revision_null_backfill_update("messages", []) is None
    statement = build_revision_null_backfill_update(
        "messages",
        ["m-1", "m-2"],
    )
    assert statement == (
        "UPDATE messages SET conversation_revision = 0 "
        "WHERE id IN ('m-1', 'm-2') AND conversation_revision IS NULL"
    )
    escaped = build_revision_null_backfill_update("notebooks", ["n'1"])
    assert escaped is not None
    assert "n''1" in escaped


class _CatalogAwareRaw:
    """Admin connection stand-in with catalog defaults and nullable revision rows."""

    def __init__(
        self,
        catalog: dict[str, dict[str, Any]],
        recorder: list[str],
        null_ids: dict[str, list[str]] | None = None,
    ):
        self._catalog = catalog
        self._recorder = recorder
        self._null_ids = null_ids if null_ids is not None else {
            "notebooks": [],
            "messages": [],
        }

    def cursor(self):
        catalog = self._catalog
        recorder = self._recorder
        null_ids = self._null_ids

        class _Cur:
            description = None
            rowcount = 0
            _rows: list[tuple[Any, ...]] = []

            def execute(self, sql, params=None):
                recorder.append(sql)
                upper = " ".join(sql.upper().split())
                if "INFORMATION_SCHEMA.COLUMNS" in upper:
                    table = (params or (None,))[0]
                    columns = catalog.get(str(table), {})
                    ordered = sorted(columns.items(), key=lambda item: item[0])
                    self.description = [
                        type("Col", (), {"name": "column_name"})(),
                        type("Col", (), {"name": "column_default"})(),
                        type("Col", (), {"name": "is_nullable"})(),
                    ]
                    self._rows = [
                        (
                            meta.get("name", name),
                            meta.get("column_default"),
                            meta.get("is_nullable", "YES"),
                        )
                        for name, meta in ordered
                    ]
                    return
                if "WHERE CONVERSATION_REVISION IS NULL" in upper and upper.startswith(
                    "SELECT ID"
                ):
                    table = "notebooks" if "FROM NOTEBOOKS" in upper else "messages"
                    limit = int((params or (0,))[0])
                    ids = list(null_ids.get(table, []))
                    self.description = [type("Col", (), {"name": "id"})()]
                    self._rows = [(item,) for item in ids[:limit]]
                    return
                if upper.startswith("SELECT COUNT(*)"):
                    table = "notebooks" if "FROM NOTEBOOKS" in upper else "messages"
                    self.description = [type("Col", (), {"name": "null_count"})()]
                    self._rows = [(len(null_ids.get(table, [])),)]
                    return
                add_match = re.search(
                    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)\s+",
                    sql,
                    flags=re.IGNORECASE,
                )
                if add_match:
                    table_name = add_match.group(1).lower()
                    column_name = add_match.group(2)
                    catalog.setdefault(table_name, {})[column_name.lower()] = {
                        "name": column_name,
                        "column_default": None,
                        "is_nullable": "YES",
                    }
                    # Newly added revision column leaves existing rows NULL.
                    if column_name.lower() == "conversation_revision":
                        null_ids.setdefault(table_name, [])
                    self.description = None
                    self._rows = []
                    return
                default_match = re.search(
                    r"ALTER\s+TABLE\s+(\w+)\s+ALTER\s+COLUMN\s+(\w+)\s+"
                    r"SET\s+DEFAULT\s+0",
                    sql,
                    flags=re.IGNORECASE,
                )
                if default_match:
                    table_name = default_match.group(1).lower()
                    column_name = default_match.group(2).lower()
                    meta = catalog.setdefault(table_name, {}).setdefault(
                        column_name,
                        {"name": column_name, "is_nullable": "YES"},
                    )
                    meta["column_default"] = "0"
                    self.description = None
                    self._rows = []
                    return
                update_match = re.search(
                    r"UPDATE\s+(\w+)\s+SET\s+CONVERSATION_REVISION\s*=\s*0\s+"
                    r"WHERE\s+ID\s+IN\s*\((.*)\)\s+AND\s+CONVERSATION_REVISION\s+IS\s+NULL",
                    sql,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if update_match:
                    table_name = update_match.group(1).lower()
                    raw_ids = update_match.group(2)
                    ids = [
                        item.strip().strip("'").replace("''", "'")
                        for item in raw_ids.split(",")
                        if item.strip()
                    ]
                    remaining = [
                        item
                        for item in null_ids.get(table_name, [])
                        if item not in ids
                    ]
                    null_ids[table_name] = remaining
                    self.rowcount = len(ids)
                    self.description = None
                    self._rows = []
                    return
                self.description = None
                self._rows = []

            def fetchall(self):
                rows = self._rows
                self._rows = []
                return rows

            def fetchone(self):
                rows = self._rows
                self._rows = []
                return rows[0] if rows else None

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


def _legacy_catalog() -> dict[str, dict[str, Any]]:
    notebooks = {
        name: {"name": name, "column_default": None, "is_nullable": "YES"}
        for name in (
            "id",
            "user_id",
            "title",
            "current_stage",
            "progress_text",
            "settings_text",
            "created_at",
            "updated_at",
        )
    }
    messages = {
        name: {"name": name, "column_default": None, "is_nullable": "YES"}
        for name in (
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
        )
    }
    return {"notebooks": notebooks, "messages": messages}


def test_apply_missing_revision_columns_is_catalog_driven_and_idempotent():
    """Admin migration ALTERs notebooks CAS then message columns; second pass empty."""
    catalog = _legacy_catalog()
    null_ids = {"notebooks": ["nb-1"], "messages": ["m-1", "m-2"]}
    recorder: list[str] = []

    def connect_fn(**kwargs):
        assert kwargs["user"] == "admin"
        assert kwargs["autocommit"] is False
        return _CatalogAwareRaw(catalog, recorder, null_ids)

    first = apply_missing_revision_columns(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
        batch_size=1000,
    )
    assert "ALTER TABLE notebooks ADD COLUMN conversation_revision INTEGER" in first
    assert (
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0"
        in first
    )
    assert "ALTER TABLE messages ADD COLUMN conversation_revision INTEGER" in first
    assert "ALTER TABLE messages ADD COLUMN previous_message_id TEXT" in first
    assert "ALTER TABLE messages ADD COLUMN superseded_at_revision INTEGER" in first
    assert any("UPDATE notebooks SET conversation_revision = 0" in item for item in first)
    assert any("UPDATE messages SET conversation_revision = 0" in item for item in first)
    assert null_ids["notebooks"] == []
    assert null_ids["messages"] == []
    assert catalog["notebooks"]["conversation_revision"]["column_default"] == "0"
    assert catalog["messages"]["conversation_revision"]["column_default"] == "0"

    recorder.clear()
    second = apply_missing_revision_columns(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
    )
    assert second == []
    assert not any("ADD COLUMN" in sql.upper() for sql in recorder)
    assert not any(sql.upper().startswith("UPDATE ") for sql in recorder)


def test_partial_migration_repairs_default_and_nulls_without_readding_column():
    """Column-exists-but-incomplete prior run still SET DEFAULT + backfills."""
    catalog = _legacy_catalog()
    catalog["notebooks"]["conversation_revision"] = {
        "name": "conversation_revision",
        "column_default": None,
        "is_nullable": "YES",
    }
    catalog["messages"]["conversation_revision"] = {
        "name": "conversation_revision",
        "column_default": None,
        "is_nullable": "YES",
    }
    catalog["messages"]["previous_message_id"] = {
        "name": "previous_message_id",
        "column_default": None,
        "is_nullable": "YES",
    }
    catalog["messages"]["superseded_at_revision"] = {
        "name": "superseded_at_revision",
        "column_default": None,
        "is_nullable": "YES",
    }
    null_ids = {
        "notebooks": ["nb-a"],
        "messages": [f"m-{index:04d}" for index in range(5)],
    }
    recorder: list[str] = []

    def connect_fn(**kwargs):
        return _CatalogAwareRaw(catalog, recorder, null_ids)

    applied = apply_missing_revision_columns(
        endpoint="ep.example",
        region="us-west-2",
        admin_user="admin",
        connect_fn=connect_fn,
        token_provider=lambda: "admin-tok",
        batch_size=2,
    )
    assert not any("ADD COLUMN conversation_revision" in item for item in applied)
    assert any(
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0"
        in item
        for item in applied
    )
    assert any(
        "ALTER TABLE messages ALTER COLUMN conversation_revision SET DEFAULT 0"
        in item
        for item in applied
    )
    message_updates = [
        item for item in applied if item.upper().startswith("UPDATE MESSAGES")
    ]
    assert len(message_updates) == 3  # 2 + 2 + 1 with batch_size=2
    assert null_ids["notebooks"] == []
    assert null_ids["messages"] == []


def test_revision_null_backfill_batch_boundaries():
    """0 / under / exact / over batch size remain deterministic and resumable."""
    catalog = _legacy_catalog()
    for table in ("notebooks", "messages"):
        catalog[table]["conversation_revision"] = {
            "name": "conversation_revision",
            "column_default": "0",
            "is_nullable": "YES",
        }

    def run(null_ids: dict[str, list[str]], batch_size: int) -> list[str]:
        recorder: list[str] = []

        def connect_fn(**kwargs):
            return _CatalogAwareRaw(catalog, recorder, null_ids)

        return apply_revision_null_backfills(
            endpoint="ep.example",
            region="us-west-2",
            admin_user="admin",
            connect_fn=connect_fn,
            token_provider=lambda: "admin-tok",
            batch_size=batch_size,
            tables=("messages",),
        )

    assert run({"notebooks": [], "messages": []}, batch_size=10) == []

    under = {"notebooks": [], "messages": ["a", "b"]}
    under_applied = run(under, batch_size=10)
    assert len(under_applied) == 1
    assert under["messages"] == []

    exact_ids = [f"e-{index}" for index in range(4)]
    exact = {"notebooks": [], "messages": list(exact_ids)}
    exact_applied = run(exact, batch_size=4)
    assert len(exact_applied) == 1
    assert exact["messages"] == []

    over_ids = [f"o-{index:03d}" for index in range(9)]
    over = {"notebooks": [], "messages": list(over_ids)}
    over_applied = run(over, batch_size=4)
    assert len(over_applied) == 3
    assert over["messages"] == []

    # Interrupted mid-backfill then resume with remaining NULLs.
    interrupted = {
        "notebooks": [],
        "messages": [f"i-{index:03d}" for index in range(7)],
    }
    first = run(interrupted, batch_size=3)
    # Force an interruption after the first batch by restoring leftover ids.
    assert len(first) >= 1
    leftover = [f"i-{index:03d}" for index in range(3, 7)]
    interrupted["messages"] = list(leftover)
    resumed = run(interrupted, batch_size=3)
    assert len(resumed) == 2
    assert interrupted["messages"] == []


def test_apply_dsql_schema_runs_revision_migration_only_on_full_bootstrap():
    """Custom statement lists skip catalog migration; opt-in bootstrap includes it."""
    catalog = _legacy_catalog()
    null_ids = {"notebooks": [], "messages": []}
    recorder: list[str] = []

    def connect_fn(**kwargs):
        return _CatalogAwareRaw(catalog, recorder, null_ids)

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
    catalog.clear()
    catalog.update(_legacy_catalog())
    null_ids["notebooks"] = []
    null_ids["messages"] = []

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
