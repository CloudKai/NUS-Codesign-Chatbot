"""Admin-only Aurora DSQL schema bootstrap (one DDL statement per transaction).

Aurora DSQL allows only one DDL statement per transaction. This script opens a
fresh admin connection for each CREATE TABLE / CREATE INDEX statement, commits,
and reconnects. Asynchronous index builds return a ``job_id``; after commit the
script calls the ``sys.wait_for_job`` procedure on a dedicated autocommit
connection before continuing. After CREATE/INDEX bootstrap it inspects
``information_schema`` and ALTERs only missing revision columns on
``notebooks`` and ``messages`` (additive, idempotent). It never runs at
application startup.

Admin auth uses ``generate_db_connect_admin_auth_token`` (DbConnectAdmin).
Runtime traffic must use ``DSQL_USER=co_design_app`` with DbConnect only.

Example:

```sh
DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \\
  .venv/bin/python scripts/init_dsql.py --admin-user admin
```

After success, grant runtime privileges (map the EC2 IAM role to co_design_app
in IAM; do not commit account ARNs):

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO co_design_app;
```
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.persistence.dsql_connection import (  # noqa: E402
    DsqlConnectionProxy,
    generate_dsql_admin_auth_token,
)
from backend.persistence.dsql_schema import (  # noqa: E402
    RUNTIME_GRANT_SQL,
    RUNTIME_ROLE_NAME,
    iter_dsql_ddl_statements,
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


def is_async_index_ddl(statement: str) -> bool:
    """Return True when *statement* is a CREATE [UNIQUE] INDEX ASYNC DDL."""
    upper = " ".join(statement.upper().split())
    return upper.startswith("CREATE") and " INDEX ASYNC " in f" {upper} "


def plan_missing_notebooks_conversation_revision_statements(
    existing_columns: set[str] | frozenset[str],
) -> list[str]:
    """Return additive notebooks CAS DDL/DML when ``conversation_revision`` is absent.

    Each returned statement is one DDL or a single backfill UPDATE so callers
    can commit one statement per transaction. Idempotent when the column
    already exists.

    Args:
        existing_columns: Lower/mixed-case column names already on ``notebooks``.

    Returns:
        Ordered ADD / SET DEFAULT 0 / NULL-backfill statements, or ``[]``.
    """
    present = {str(name).lower() for name in existing_columns}
    if "conversation_revision" in present:
        return []
    return [
        "ALTER TABLE notebooks ADD COLUMN conversation_revision INTEGER",
        "ALTER TABLE notebooks ALTER COLUMN conversation_revision SET DEFAULT 0",
        "UPDATE notebooks SET conversation_revision = 0 "
        "WHERE conversation_revision IS NULL",
    ]


def plan_missing_message_revision_statements(
    existing_columns: set[str] | frozenset[str],
) -> list[str]:
    """Return additive message-revision DDL/DML for columns absent from catalog.

    Each returned statement is one DDL (or a single backfill UPDATE) so callers
    can commit one statement per transaction. Idempotent: already-present
    columns produce no statements.

    Args:
        existing_columns: Lower/mixed-case column names already on ``messages``.

    Returns:
        Ordered statements to add missing revision columns and, when
        ``conversation_revision`` is newly added, set DEFAULT 0 and backfill
        NULLs (DSQL cannot combine ADD COLUMN with NOT NULL/DEFAULT).
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
            planned.append(
                "UPDATE messages SET conversation_revision = 0 "
                "WHERE conversation_revision IS NULL"
            )
    return planned


def fetch_table_columns(connection: Any, table_name: str) -> set[str]:
    """Return column names for *table_name* from ``information_schema``.

    Args:
        connection: Admin ``DsqlConnectionProxy`` (or compatible execute API).
        table_name: Unqualified table name in the ``public`` schema.

    Returns:
        Set of column names as reported by the catalog (case preserved).
    """
    result = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ?
        """,
        (table_name,),
    )
    columns: set[str] = set()
    for row in result.fetchall():
        if hasattr(row, "get"):
            value = row.get("column_name")
            if value is None:
                for key in row:
                    if str(key).lower() == "column_name":
                        value = row[key]
                        break
        elif isinstance(row, (tuple, list)) and row:
            value = row[0]
        else:
            value = row
        name = str(value or "").strip()
        if name:
            columns.add(name)
    return columns


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
    """Open one verify-full admin connection for a DDL or procedure call."""
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
    raw = active_connect(
        host=endpoint,
        port=5432,
        dbname=database,
        user=admin_user,
        password=token,
        sslmode="verify-full",
        sslrootcert="system",
        autocommit=autocommit,
    )
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


def apply_missing_revision_columns(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    admin_user: str = "admin",
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
) -> list[str]:
    """Inspect catalog and ALTER missing notebook/message revision columns.

    Reads ``information_schema.columns`` for ``notebooks`` and ``messages`` on
    one admin connection, plans additive statements (notebooks CAS column
    first, then message revision columns), and applies each in its own
    committed transaction. No-op when all columns already exist. Never runs
    from application startup.

    Returns:
        Statements that were executed (empty when already up to date).
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
        notebooks_columns = fetch_table_columns(catalog_connection, "notebooks")
        messages_columns = fetch_table_columns(catalog_connection, "messages")
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

    planned = (
        plan_missing_notebooks_conversation_revision_statements(notebooks_columns)
        + plan_missing_message_revision_statements(messages_columns)
    )
    return _apply_admin_statements(
        planned=planned,
        endpoint=endpoint,
        region=region,
        database=database,
        admin_user=admin_user,
        connect_fn=connect_fn,
        token_provider=token_provider,
    )


# Backwards-compatible alias used by earlier tests/call sites.
apply_missing_message_revision_columns = apply_missing_revision_columns


def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags and apply the DSQL schema as admin."""
    parser = argparse.ArgumentParser(
        description=(
            "Admin-only Aurora DSQL schema bootstrap. "
            "One DDL per transaction; waits for ASYNC index jobs; "
            "additive notebook/message revision ALTERs from catalog; "
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
    print(f"Applied {len(applied)} DSQL DDL statement(s) as {args.admin_user}.")
    print()
    print("Next: grant runtime privileges to the application role (no ARNs in Git):")
    print(RUNTIME_GRANT_SQL)
    print()
    print(
        f"Then set DSQL_USER={RUNTIME_ROLE_NAME} for the EC2 app "
        "(IAM DbConnect token; not admin)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
