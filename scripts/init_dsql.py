"""Admin-only Aurora DSQL schema bootstrap (one DDL statement per transaction).

Aurora DSQL allows only one DDL statement per transaction. This script opens a
fresh admin connection for each CREATE TABLE / CREATE INDEX statement, commits,
and reconnects. It never runs at application startup.

Runtime traffic must use ``DSQL_USER=co_design_app`` (DbConnect), not admin.

Example:

```sh
DSQL_ENDPOINT=<hostname> AWS_REGION=us-west-2 \\
  .venv/bin/python scripts/init_dsql.py --admin-user admin
```

After success, grant runtime privileges (map the EC2 IAM role to co_design_app
in IAM; do not commit account ARNs):

```sql
GRANT USAGE ON SCHEMA public TO co_design_app;
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
    generate_dsql_auth_token,
)
from backend.persistence.dsql_schema import (  # noqa: E402
    RUNTIME_GRANT_SQL,
    RUNTIME_ROLE_NAME,
    iter_dsql_ddl_statements,
)
from backend.settings import settings  # noqa: E402


def _connect_admin(
    *,
    endpoint: str,
    region: str,
    database: str,
    admin_user: str,
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
) -> DsqlConnectionProxy:
    """Open one admin connection for a single DDL transaction."""
    if not endpoint.strip():
        raise ValueError("DSQL_ENDPOINT is required")
    token = (token_provider or (
        lambda: generate_dsql_auth_token(endpoint=endpoint, region=region)
    ))()
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
        sslmode="require",
    )
    return DsqlConnectionProxy(raw)


def apply_dsql_schema(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    admin_user: str = "admin",
    connect_fn: Callable[..., Any] | None = None,
    token_provider: Callable[[], str] | None = None,
    statements: list[str] | None = None,
) -> list[str]:
    """Apply each DDL statement in its own committed transaction.

    Reconnects after every statement so catalog changes are visible and DSQL's
    one-DDL-per-transaction rule is respected.

    Returns:
        The list of statements that were executed.
    """
    planned = statements if statements is not None else iter_dsql_ddl_statements()
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


def main(argv: list[str] | None = None) -> int:
    """Parse CLI flags and apply the DSQL schema as admin."""
    parser = argparse.ArgumentParser(
        description=(
            "Admin-only Aurora DSQL schema bootstrap. "
            "One DDL per transaction; not used by application startup."
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
