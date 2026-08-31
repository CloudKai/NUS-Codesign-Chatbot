"""Admin-only Aurora DSQL schema bootstrap (one DDL statement per transaction).

Aurora DSQL allows only one DDL statement per transaction. This script opens a
fresh admin connection for each CREATE TABLE / CREATE INDEX statement, commits,
and reconnects. Asynchronous index builds return a ``job_id``; after commit the
script calls the ``sys.wait_for_job`` procedure on a dedicated autocommit
connection before continuing. After CREATE/INDEX bootstrap it inspects
``information_schema`` and ALTERs only missing revision columns on
``notebooks`` and ``messages`` (additive, idempotent). It initializes the
five-phase workflow marker only when no notebooks exist; populated unmarked
data remains reset-gated. It never runs at application startup.

Admin auth uses ``generate_db_connect_admin_auth_token`` (DbConnectAdmin).
Runtime traffic must use ``DSQL_USER=co_design_app`` with DbConnect only.

Example:

```sh
DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \\
  .venv/bin/python scripts/init_dsql.py --admin-user admin
```

On AWS CloudShell (system CA / IPv6 flaky), set ``DSQL_SSLROOTCERT`` to Amazon
Root CA 1 and use a checkout that includes IPv4 ``hostaddr`` preference. Full
operator checklist: ``docs/deploy/AWS_STATELESS_EC2.md``
(section *CloudShell / laptop init_dsql checklist*).

After success, grant runtime privileges (map the EC2 IAM role to co_design_app
in IAM; do not commit account ARNs):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO co_design_app;
```
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.persistence.dsql_connection import (  # noqa: E402
    DsqlConnectionProxy,
    generate_dsql_admin_auth_token,
)
from backend.persistence.dsql_schema import (  # noqa: E402
    RUNTIME_GRANT_SQL,
    RUNTIME_ROLE_NAME,
    iter_dsql_ddl_statements,
)
from backend.workflow_contract import (  # noqa: E402
    WORKFLOW_CONTRACT_KEY,
    workflow_contract_is_ready,
    workflow_contract_payload,
)
from backend.settings import settings  # noqa: E402

# Append-only revision columns. Aurora DSQL ADD COLUMN accepts only a name and
# type (no NOT NULL / DEFAULT in the same statement). Defaults and NULL
# backfills are separate statements after ADD — see
# docs/deploy/AWS_STATELESS_EC2.md.
_MESSAGE_REVISION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("conversation_revision", "INTEGER"),
    ("previous_message_id", "TEXT"),
    ("superseded_at_revision", "INTEGER"),
)

# Stay well under Aurora DSQL per-transaction row-modification limits (~3k).
REVISION_NULL_BACKFILL_BATCH_SIZE = 1000
_REVISION_BACKFILL_TABLES = frozenset({"notebooks", "messages"})
_IAM_ROLE_ARN = re.compile(r"^arn:[^:]+:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,128}$")


def configure_runtime_iam_role(
    *, endpoint: str, region: str, database: str, admin_user: str, iam_role_arn: str
) -> None:
    """Idempotently create, map, and privilege the non-DDL application role.

    Args:
        endpoint: Aurora DSQL endpoint hostname.
        region: AWS Region that signs the admin token.
        database: DSQL database name.
        admin_user: DbConnectAdmin database principal.
        iam_role_arn: Exact module EC2 IAM role ARN to map to ``co_design_app``.

    Raises:
        ValueError: If the supplied ARN is not an IAM role ARN.
        Exception: When DSQL rejects a role, mapping, or privilege statement.
    """
    cleaned_arn = str(iam_role_arn or "").strip()
    if not _IAM_ROLE_ARN.fullmatch(cleaned_arn):
        raise ValueError("--runtime-iam-role-arn must be an exact IAM role ARN")
    statements = (
        f"CREATE ROLE {RUNTIME_ROLE_NAME} WITH LOGIN",
        f"AWS IAM GRANT {RUNTIME_ROLE_NAME} TO '{cleaned_arn}'",
        RUNTIME_GRANT_SQL,
    )
    for statement in statements:
        connection = _connect_admin(
            endpoint=endpoint, region=region, database=database, admin_user=admin_user
        )
        try:
            try:
                connection.execute(statement)
            except Exception as error:  # Aurora DSQL has no IF NOT EXISTS for roles.
                if statement.startswith("CREATE ROLE") and "already exists" in str(error).lower():
                    connection.rollback()
                    continue
                raise
            connection.commit()
        finally:
            connection.close()


def is_async_index_ddl(statement: str) -> bool:
    """Return True when *statement* is a CREATE [UNIQUE] INDEX ASYNC DDL."""
    upper = " ".join(statement.upper().split())
    return upper.startswith("CREATE") and " INDEX ASYNC " in f" {upper} "


def column_default_is_zero(column_default: Any) -> bool:
    """Return True when *column_default* is a numeric zero DEFAULT expression."""
    if column_default is None:
        return False
    text = str(column_default).strip().lower()
    if not text:
        return False
    return text == "0" or text == "(0)" or text.startswith("0::")


def plan_missing_notebooks_conversation_revision_statements(
    existing_columns: set[str] | frozenset[str],
    *,
    default_is_zero: bool | None = None,
) -> list[str]:
    """Return additive notebooks CAS DDL (ADD / SET DEFAULT) for repair.

    Presence of the column alone is not enough: when ``default_is_zero`` is
    ``False``, emit ``SET DEFAULT 0``. NULL backfills are batched separately so
    interrupted migrations remain resumable under DSQL row limits.

    Name-only callers (``default_is_zero=None``) stay backward-compatible: if
    the column already exists, return ``[]`` and let the richer apply path pass
    an explicit default flag / null count.

    Args:
        existing_columns: Lower/mixed-case column names already on ``notebooks``.
        default_is_zero: When the column exists, whether catalog DEFAULT is 0.

    Returns:
        Ordered ADD / SET DEFAULT statements (never unbounded UPDATE), or ``[]``.
    """
    present = {str(name).lower() for name in existing_columns}
    planned: list[str] = []
    if "conversation_revision" not in present:
        planned.append(
            "ALTER TABLE notebooks ADD COLUMN conversation_revision INTEGER"
        )
        planned.append(
            "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0"
        )
        return planned
    if default_is_zero is False:
        planned.append(
            "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0"
        )
    return planned


def plan_missing_message_revision_statements(
    existing_columns: set[str] | frozenset[str],
    *,
    revision_default_is_zero: bool | None = None,
) -> list[str]:
    """Return additive message-revision DDL for missing columns / defaults.

    Does not emit unbounded NULL backfills; those run through batched updates.
    When ``conversation_revision`` exists but ``revision_default_is_zero`` is
    false, emits ``SET DEFAULT 0``.

    Args:
        existing_columns: Lower/mixed-case column names already on ``messages``.
        revision_default_is_zero: Catalog default status for conversation_revision.

    Returns:
        Ordered ADD / SET DEFAULT statements.
    """
    present = {str(name).lower() for name in existing_columns}
    planned: list[str] = []
    for column_name, column_type in _MESSAGE_REVISION_COLUMNS:
        if column_name.lower() in present:
            continue
        planned.append(
            f"ALTER TABLE messages ADD COLUMN {column_name} {column_type}"
        )
        if column_name == "conversation_revision":
            planned.append(
                "ALTER TABLE messages ALTER COLUMN conversation_revision "
                "SET DEFAULT 0"
            )
    if (
        "conversation_revision" in present
        and revision_default_is_zero is False
    ):
        planned.append(
            "ALTER TABLE messages ALTER COLUMN conversation_revision "
            "SET DEFAULT 0"
        )
    return planned


def build_revision_null_backfill_update(
    table: str,
    row_ids: list[str] | tuple[str, ...],
) -> str | None:
    """Build one deterministic NULL→0 UPDATE for a known id batch.

    Args:
        table: ``notebooks`` or ``messages`` only.
        row_ids: Ordered primary-key ids to repair (already selected).

    Returns:
        A single UPDATE statement, or ``None`` when *row_ids* is empty.

    Raises:
        ValueError: When *table* is not a revision backfill target.
    """
    cleaned_table = str(table or "").strip().lower()
    if cleaned_table not in _REVISION_BACKFILL_TABLES:
        raise ValueError(f"Unsupported revision backfill table: {table!r}")
    cleaned_ids = [str(item).strip() for item in row_ids if str(item).strip()]
    if not cleaned_ids:
        return None
    # Literal ids are admin-migration only; values come from a prior SELECT on
    # the same table. Escape single quotes for safe SQL literals.
    rendered = ", ".join("'" + item.replace("'", "''") + "'" for item in cleaned_ids)
    return (
        f"UPDATE {cleaned_table} SET conversation_revision = 0 "
        f"WHERE id IN ({rendered}) AND conversation_revision IS NULL"
    )


def _row_value(row: Any, *names: str) -> Any:
    """Read a column from a mapping/tuple row by case-insensitive name."""
    if hasattr(row, "get"):
        for name in names:
            if name in row:
                return row.get(name)
        lowered = {str(key).lower(): row[key] for key in row}
        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None
    if isinstance(row, (tuple, list)) and row:
        return row[0]
    return row


def fetch_table_columns(connection: Any, table_name: str) -> set[str]:
    """Return column names for *table_name* from ``information_schema``.

    Args:
        connection: Admin ``DsqlConnectionProxy`` (or compatible execute API).
        table_name: Unqualified table name in the ``public`` schema.

    Returns:
        Set of column names as reported by the catalog (case preserved).
    """
    details = fetch_table_column_details(connection, table_name)
    return {meta["name"] for meta in details.values() if meta.get("name")}


def fetch_table_column_details(
    connection: Any,
    table_name: str,
) -> dict[str, dict[str, Any]]:
    """Return column metadata keyed by lower-case name.

    Each value includes ``name``, ``column_default``, and ``is_nullable``.
    """
    result = connection.execute(
        """
        SELECT column_name, column_default, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?
        """,
        (table_name,),
    )
    details: dict[str, dict[str, Any]] = {}
    for row in result.fetchall():
        name = str(_row_value(row, "column_name") or "").strip()
        if not name:
            continue
        details[name.lower()] = {
            "name": name,
            "column_default": _row_value(row, "column_default"),
            "is_nullable": _row_value(row, "is_nullable"),
        }
    return details


def count_null_conversation_revisions(connection: Any, table_name: str) -> int:
    """Return how many rows still have NULL ``conversation_revision``."""
    cleaned = str(table_name or "").strip().lower()
    if cleaned not in _REVISION_BACKFILL_TABLES:
        raise ValueError(f"Unsupported revision backfill table: {table_name!r}")
    result = connection.execute(
        f"SELECT COUNT(*) AS null_count FROM {cleaned} "
        "WHERE conversation_revision IS NULL"
    )
    row = result.fetchone()
    value = _row_value(row, "null_count", "count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def fetch_null_conversation_revision_ids(
    connection: Any,
    table_name: str,
    *,
    batch_size: int = REVISION_NULL_BACKFILL_BATCH_SIZE,
) -> list[str]:
    """Return up to *batch_size* ids with NULL ``conversation_revision``."""
    cleaned = str(table_name or "").strip().lower()
    if cleaned not in _REVISION_BACKFILL_TABLES:
        raise ValueError(f"Unsupported revision backfill table: {table_name!r}")
    limit = max(1, int(batch_size))
    result = connection.execute(
        f"""
        SELECT id
        FROM {cleaned}
        WHERE conversation_revision IS NULL
        ORDER BY id
        LIMIT ?
        """,
        (limit,),
    )
    ids: list[str] = []
    for row in result.fetchall():
        value = str(_row_value(row, "id") or "").strip()
        if value:
            ids.append(value)
    return ids


def _job_id_from_result(result: Any) -> str | None:
    """Extract the async index ``job_id`` from a CREATE INDEX ASYNC result.

    Returns:
        The job id string when a new index build was submitted, or ``None`` when
        ``CREATE INDEX ASYNC IF NOT EXISTS`` finds an existing index and returns
        no row (idempotent re-run).
    """
    row = result.fetchone() if result is not None else None
    if row is None:
        return None
    if hasattr(row, "get"):
        value = row.get("job_id")
        if value is None:
            # Case-insensitive mapping used by DsqlConnectionProxy rows.
            for key in row:
                if str(key).lower() == "job_id":
                    value = row[key]
                    break
    elif isinstance(row, (tuple, list)) and row:
        value = row[0]
    else:
        value = row
    job_id = str(value or "").strip()
    return job_id or None


def _prefer_ipv4_hostaddr(hostname: str) -> str | None:
    """Return an IPv4 address for *hostname* when DNS provides one.

    CloudShell often cannot open DSQL's IPv6 AAAA ("Cannot assign requested
    address"). Passing ``hostaddr`` keeps ``host`` for TLS verify-full SNI.
    """
    import socket

    cleaned = str(hostname or "").strip()
    if not cleaned:
        return None
    try:
        infos = socket.getaddrinfo(
            cleaned,
            5432,
            socket.AF_INET,
            socket.SOCK_STREAM,
        )
    except OSError:
        return None
    if not infos:
        return None
    address = infos[0][4][0]
    return str(address) if address else None


def _connect_admin(
    *,
    endpoint: str,
    region: str,
    database: str,
    admin_user: str,
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
    autocommit: bool = False,
) -> DsqlConnectionProxy:
    """Open one verify-full admin connection for a DDL or procedure call.

    Honors ``settings.dsql_sslrootcert`` (``DSQL_SSLROOTCERT``, default
    ``system``) so operators can point at Amazon Root CA 1 on CloudShell when
    the platform trust store fails DSQL certificate verification.
    """
    if not endpoint.strip():
        raise ValueError("DSQL_ENDPOINT is required")
    token = (
        token_provider
        or (
            lambda: generate_dsql_admin_auth_token(
                endpoint=endpoint, region=region
            )
        )
    )()
    active_connect = connect_fn
    if active_connect is None:
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("psycopg is required for DSQL admin bootstrap") from error

        def _connect(**kwargs: Any) -> Any:
            return psycopg.connect(**kwargs)

        active_connect = _connect
    connect_kwargs: dict[str, Any] = {
        "host": endpoint,
        "port": 5432,
        "dbname": database,
        "user": admin_user,
        "password": token,
        "sslmode": "verify-full",
        "sslrootcert": str(settings.dsql_sslrootcert or "system"),
        "autocommit": autocommit,
    }
    hostaddr = _prefer_ipv4_hostaddr(endpoint)
    if hostaddr:
        connect_kwargs["hostaddr"] = hostaddr
    raw = active_connect(**connect_kwargs)
    return DsqlConnectionProxy(raw)


def wait_for_async_index_job(
    *,
    job_id: str,
    endpoint: str,
    region: str,
    database: str,
    admin_user: str,
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
) -> None:
    """Block until a DSQL async index job completes; raise on failure.

    Opens a fresh autocommit admin connection, separate from the CREATE INDEX
    ASYNC transaction. Aurora DSQL exposes ``sys.wait_for_job`` as a procedure
    and rejects it inside a transaction block.
    """
    connection = _connect_admin(
        endpoint=endpoint,
        region=region,
        database=database,
        admin_user=admin_user,
        connect_fn=connect_fn,
        token_provider=token_provider,
        autocommit=True,
    )
    try:
        connection.execute(
            "CALL sys.wait_for_job(?)",
            (job_id,),
        )
    finally:
        connection.close()


def apply_dsql_schema(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    admin_user: str = "admin",
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
    statements: list[str] | None = None,
    wait_for_job: Callable[..., None] | None = None,
    migrate_message_revisions: bool | None = None,
) -> list[str]:
    """Apply each DDL statement in its own committed transaction.

    Reconnects after every statement so catalog changes are visible and DSQL's
    one-DDL-per-transaction rule is respected. For ``CREATE INDEX ASYNC``,
    captures ``job_id`` when present, commits, then waits only when a new
    non-empty job id was returned (existing ``IF NOT EXISTS`` indexes skip wait).

    After the planned CREATE/INDEX statements (full schema bootstrap only),
    inspects ``information_schema`` and ALTERs only missing revision columns:
    ``notebooks.conversation_revision`` first (CAS prerequisite), then the
    three message revision columns. Custom ``statements=`` lists skip that
    catalog migration unless ``migrate_message_revisions=True``.

    Returns:
        The list of statements that were executed (CREATE/INDEX plus any
        additive notebook/message revision migrations).
    """
    planned = statements if statements is not None else iter_dsql_ddl_statements()
    applied: list[str] = []
    waiter = wait_for_job or wait_for_async_index_job
    for statement in planned:
        connection = _connect_admin(
            endpoint=endpoint,
            region=region,
            database=database,
            admin_user=admin_user,
            connect_fn=connect_fn,
            token_provider=token_provider,
        )
        job_id: str | None = None
        try:
            result = connection.execute(statement)
            if is_async_index_ddl(statement):
                job_id = _job_id_from_result(result)
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:  # noqa: BLE001
                pass
            connection.close()
            raise
        else:
            connection.close()
        if job_id:
            waiter(
                job_id=job_id,
                endpoint=endpoint,
                region=region,
                database=database,
                admin_user=admin_user,
                connect_fn=connect_fn,
                token_provider=token_provider,
            )
        applied.append(statement)

    should_migrate = (
        migrate_message_revisions
        if migrate_message_revisions is not None
        else statements is None
    )
    if should_migrate:
        applied.extend(
            apply_missing_revision_columns(
                endpoint=endpoint,
                region=region,
                database=database,
                admin_user=admin_user,
                connect_fn=connect_fn,
                token_provider=token_provider,
            )
        )
    return applied


def _apply_admin_statements(
    *,
    planned: list[str],
    endpoint: str,
    region: str,
    database: str,
    admin_user: str,
    connect_fn: Callable[..., Any] | None,
    token_provider: Callable[[], str] | None,
) -> list[str]:
    """Execute each planned statement in its own committed admin transaction."""
    applied: list[str] = []
    for statement in planned:
        connection = _connect_admin(
            endpoint=endpoint,
            region=region,
            database=database,
            admin_user=admin_user,
            connect_fn=connect_fn,
            token_provider=token_provider,
        )
        try:
            connection.execute(statement)
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:  # noqa: BLE001
                pass
            connection.close()
            raise
        else:
            connection.close()
        applied.append(statement)
    return applied


def initialize_empty_workflow_contract(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    admin_user: str = "admin",
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
) -> str:
    """Initialize the five-phase marker only when no notebooks exist.

    Returns ``initialized`` after writing the marker, ``already-ready`` when a
    populated database already has the exact marker, or ``requires-reset``
    when populated learning data cannot be safely interpreted. Existing
    learning records are never modified by this bootstrap step.
    """
    connection = _connect_admin(
        endpoint=endpoint,
        region=region,
        database=database,
        admin_user=admin_user,
        connect_fn=connect_fn,
        token_provider=token_provider,
    )
    try:
        count_row = connection.execute(
            "SELECT COUNT(*) AS total FROM notebooks"
        ).fetchone()
        notebook_count = int(count_row["total"] if count_row else 0)
        marker_row = connection.execute(
            "SELECT value_text FROM system_metadata WHERE key=?",
            (WORKFLOW_CONTRACT_KEY,),
        ).fetchone()
        try:
            marker = json.loads(str(marker_row["value_text"])) if marker_row else None
        except (TypeError, json.JSONDecodeError):
            marker = None

        if notebook_count > 0:
            connection.rollback()
            return "already-ready" if workflow_contract_is_ready(marker) else "requires-reset"

        connection.execute(
            """
            INSERT INTO system_metadata (key, value_text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (key) DO UPDATE SET
                value_text=excluded.value_text,
                updated_at=excluded.updated_at
            """,
            (
                WORKFLOW_CONTRACT_KEY,
                json.dumps(workflow_contract_payload(), separators=(",", ":")),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
        return "initialized"
    except Exception:
        try:
            connection.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        connection.close()


def apply_missing_revision_columns(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    admin_user: str = "admin",
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
    batch_size: int = REVISION_NULL_BACKFILL_BATCH_SIZE,
) -> list[str]:
    """Inspect catalog and repair notebook/message revision columns.

    Reads ``information_schema.columns`` (names + defaults) for ``notebooks``
    and ``messages``, plans additive DDL (ADD / SET DEFAULT), applies each in
    its own committed transaction, then batch-backfills remaining NULL
    ``conversation_revision`` values. Column existence alone never skips
    DEFAULT or NULL repair. Never runs from application startup.

    Returns:
        Statements that were executed (empty when already fully repaired).
    """
    catalog_connection = _connect_admin(
        endpoint=endpoint,
        region=region,
        database=database,
        admin_user=admin_user,
        connect_fn=connect_fn,
        token_provider=token_provider,
    )
    try:
        notebooks_details = fetch_table_column_details(
            catalog_connection, "notebooks"
        )
        messages_details = fetch_table_column_details(
            catalog_connection, "messages"
        )
        notebooks_columns = {
            meta["name"] for meta in notebooks_details.values() if meta.get("name")
        }
        messages_columns = {
            meta["name"] for meta in messages_details.values() if meta.get("name")
        }
        notebooks_default_zero = False
        messages_default_zero = False
        if "conversation_revision" in notebooks_details:
            notebooks_default_zero = column_default_is_zero(
                notebooks_details["conversation_revision"].get("column_default")
            )
        if "conversation_revision" in messages_details:
            messages_default_zero = column_default_is_zero(
                messages_details["conversation_revision"].get("column_default")
            )
        catalog_connection.commit()
    except Exception:
        try:
            catalog_connection.rollback()
        except Exception:  # noqa: BLE001
            pass
        catalog_connection.close()
        raise
    else:
        catalog_connection.close()

    planned = plan_missing_notebooks_conversation_revision_statements(
        notebooks_columns,
        default_is_zero=(
            notebooks_default_zero
            if "conversation_revision" in {n.lower() for n in notebooks_columns}
            else None
        ),
    ) + plan_missing_message_revision_statements(
        messages_columns,
        revision_default_is_zero=(
            messages_default_zero
            if "conversation_revision" in {n.lower() for n in messages_columns}
            else None
        ),
    )
    applied = _apply_admin_statements(
        planned=planned,
        endpoint=endpoint,
        region=region,
        database=database,
        admin_user=admin_user,
        connect_fn=connect_fn,
        token_provider=token_provider,
    )
    applied.extend(
        apply_revision_null_backfills(
            endpoint=endpoint,
            region=region,
            database=database,
            admin_user=admin_user,
            connect_fn=connect_fn,
            token_provider=token_provider,
            batch_size=batch_size,
        )
    )
    return applied


def apply_revision_null_backfills(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    admin_user: str = "admin",
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
    batch_size: int = REVISION_NULL_BACKFILL_BATCH_SIZE,
    tables: tuple[str, ...] = ("notebooks", "messages"),
) -> list[str]:
    """Batch-repair NULL ``conversation_revision`` values until none remain.

    Each SELECT+UPDATE batch uses its own committed admin transaction and
    stays within *batch_size* row modifications. Safe to rerun; no-op when
    columns are absent or no NULLs remain.

    Returns:
        UPDATE statements that were executed.
    """
    limit = max(1, int(batch_size))
    applied: list[str] = []
    for table in tables:
        cleaned = str(table or "").strip().lower()
        if cleaned not in _REVISION_BACKFILL_TABLES:
            raise ValueError(f"Unsupported revision backfill table: {table!r}")
        while True:
            connection = _connect_admin(
                endpoint=endpoint,
                region=region,
                database=database,
                admin_user=admin_user,
                connect_fn=connect_fn,
                token_provider=token_provider,
            )
            try:
                details = fetch_table_column_details(connection, cleaned)
                if "conversation_revision" not in details:
                    connection.commit()
                    connection.close()
                    break
                ids = fetch_null_conversation_revision_ids(
                    connection,
                    cleaned,
                    batch_size=limit,
                )
                statement = build_revision_null_backfill_update(cleaned, ids)
                if statement is None:
                    connection.commit()
                    connection.close()
                    break
                connection.execute(statement)
                connection.commit()
            except Exception:
                try:
                    connection.rollback()
                except Exception:  # noqa: BLE001
                    pass
                connection.close()
                raise
            else:
                connection.close()
            applied.append(statement)
    return applied


# Backwards-compatible alias used by earlier tests/call sites.
apply_missing_message_revision_columns = apply_missing_revision_columns


def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags and apply the DSQL schema as admin."""
    parser = argparse.ArgumentParser(
        description=(
            "Admin-only Aurora DSQL schema bootstrap. "
            "One DDL per transaction; waits for ASYNC index jobs; "
            "additive notebook/message revision ALTERs from catalog; "
            "five-phase marker only for an empty database; "
            "not used by application startup."
        )
    )
    parser.add_argument(
        "--endpoint",
        default=os.getenv("DSQL_ENDPOINT", settings.dsql_endpoint),
        help="DSQL cluster endpoint hostname (default: DSQL_ENDPOINT).",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", settings.aws_region or "us-west-2"),
        help="AWS region (default: AWS_REGION / us-west-2).",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("DSQL_DATABASE", settings.dsql_database or "postgres"),
        help="Database name (default: postgres).",
    )
    parser.add_argument(
        "--admin-user",
        default=os.getenv("DSQL_ADMIN_USER", "admin"),
        help="Admin DB user for DDL only (default: admin). Never the runtime role.",
    )
    parser.add_argument(
        "--runtime-iam-role-arn",
        default=os.getenv("DSQL_RUNTIME_IAM_ROLE_ARN", ""),
        help=(
            "Exact EC2 module IAM role ARN to map to co_design_app. Required by "
            "the production deployment job; omitted only for legacy schema repair."
        ),
    )
    args = parser.parse_args(argv)
    if (args.admin_user or "").strip().lower() == RUNTIME_ROLE_NAME.lower():
        raise SystemExit(
            f"--admin-user must not be the runtime role {RUNTIME_ROLE_NAME!r}"
        )
    applied = apply_dsql_schema(
        endpoint=str(args.endpoint or ""),
        region=str(args.region or ""),
        database=str(args.database or "postgres"),
        admin_user=str(args.admin_user or "admin"),
    )
    workflow_status = initialize_empty_workflow_contract(
        endpoint=str(args.endpoint or ""),
        region=str(args.region or ""),
        database=str(args.database or "postgres"),
        admin_user=str(args.admin_user or "admin"),
    )
    if str(args.runtime_iam_role_arn or "").strip():
        configure_runtime_iam_role(
            endpoint=str(args.endpoint or ""),
            region=str(args.region or ""),
            database=str(args.database or "postgres"),
            admin_user=str(args.admin_user or "admin"),
            iam_role_arn=str(args.runtime_iam_role_arn),
        )
        print(f"Mapped {args.runtime_iam_role_arn} to {RUNTIME_ROLE_NAME} with runtime CRUD only.")
    print(f"Applied {len(applied)} DSQL DDL statement(s) as {args.admin_user}.")
    if workflow_status == "requires-reset":
        print(
            "Workflow marker not changed: existing learning data requires the "
            "reviewed reset procedure in docs/operations/RESEARCH_DATA_RESET.md."
        )
        return 2
    elif workflow_status == "initialized":
        print("Initialized the five-phase workflow marker on the empty database.")
    else:
        print("The existing five-phase workflow marker is ready.")
    print()
    if not str(args.runtime_iam_role_arn or "").strip():
        print("Next: rerun with --runtime-iam-role-arn <module EC2 role ARN>.")
    print(f"Set DSQL_USER={RUNTIME_ROLE_NAME} for the EC2 app (IAM DbConnect; not admin).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
