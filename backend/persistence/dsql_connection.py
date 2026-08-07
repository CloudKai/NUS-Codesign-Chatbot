"""Aurora DSQL connection helpers (IAM auth, retries, SQL adaptation).

Aurora DSQL is PostgreSQL-wire compatible but not identical to PostgreSQL:
no foreign keys, no temporary tables, optimistic concurrency (retry on
serialization failures), and JSON should be stored as TEXT. Authentication
uses short-lived IAM tokens — never a permanent password in source or ``.env``.
"""

from __future__ import annotations

import logging
import random
import re
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Sequence

logger = logging.getLogger(__name__)

# SQLSTATE for serialization/OCC conflicts that callers should retry.
_RETRYABLE_SQLSTATES = {"40001", "40P01"}


def generate_dsql_auth_token(
    *,
    endpoint: str,
    region: str,
    expires_seconds: int = 900,
    client: Any | None = None,
) -> str:
    """Generate a short-lived DSQL IAM auth token.

    Returns:
        Token string used as the database password for one connection.

    Raises:
        RuntimeError: when boto3 is unavailable or token generation fails.
    """
    if client is None:
        try:
            import boto3
        except ImportError as error:  # pragma: no cover - production dependency
            raise RuntimeError(
                "boto3 is required when DATABASE_PROVIDER=dsql"
            ) from error
        client = boto3.client("dsql", region_name=region)
    # boto3 DSQL client method name is generate_db_connect_auth_token.
    token = client.generate_db_connect_auth_token(
        Hostname=endpoint,
        Region=region,
        ExpiresIn=expires_seconds,
    )
    if not token:
        raise RuntimeError("DSQL auth token generation returned an empty token")
    return str(token)


def adapt_sqlite_sql(sql: str) -> str:
    """Translate SQLite-oriented SQL fragments to DSQL/PostgreSQL placeholders.

    Converts ``?`` placeholders to ``%s``, maps ``INSERT OR IGNORE`` /
    ``INSERT OR REPLACE``, and leaves ``ON CONFLICT`` clauses intact.
    """
    text = sql.strip()
    upper = text.upper()
    if upper.startswith("INSERT OR IGNORE INTO"):
        text = "INSERT INTO" + text[len("INSERT OR IGNORE INTO") :]
        if "ON CONFLICT" not in text.upper():
            text = text.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    elif upper.startswith("INSERT OR REPLACE INTO"):
        # Prefer explicit conflict targets from callers; fall back to DO NOTHING
        # only when the statement already includes ON CONFLICT.
        text = "INSERT INTO" + text[len("INSERT OR REPLACE INTO") :]
        if "ON CONFLICT" not in text.upper():
            # oauth_login_states uses state PK — generic upsert via excluded.
            text = (
                text.rstrip().rstrip(";")
                + " ON CONFLICT (state) DO UPDATE SET "
                + "codeVerifier = EXCLUDED.codeVerifier, "
                + "createdAt = EXCLUDED.createdAt, "
                + "expiresAt = EXCLUDED.expiresAt"
            )
    # Convert qmark placeholders that are not inside quotes (simple scanner).
    return _qmark_to_percent(text)


def _qmark_to_percent(sql: str) -> str:
    """Replace unbound ``?`` placeholders with ``%s`` outside string literals."""
    result: list[str] = []
    in_single = False
    in_double = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'" and not in_double:
            in_single = not in_single
            result.append(char)
        elif char == '"' and not in_single:
            in_double = not in_double
            result.append(char)
        elif char == "?" and not in_single and not in_double:
            result.append("%s")
        else:
            result.append(char)
        index += 1
    return "".join(result)


_FK_LINE = re.compile(
    r",?\s*FOREIGN KEY\s*\([^)]+\)\s*REFERENCES\s+[^,\n]+(?:\s+ON DELETE CASCADE)?",
    re.IGNORECASE,
)


def strip_foreign_keys(ddl: str) -> str:
    """Remove FOREIGN KEY clauses unsupported by Aurora DSQL."""
    cleaned = _FK_LINE.sub("", ddl)
    cleaned = re.sub(r",\s*\)", ")", cleaned)
    return cleaned


class DsqlCursorResult:
    """Minimal cursor result exposing ``rowcount`` and fetch helpers."""

    def __init__(self, rows: list[Any], rowcount: int):
        self._rows = rows
        self.rowcount = rowcount
        self._index = 0

    def fetchone(self) -> Any | None:
        """Return the next row or ``None``."""
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self) -> list[Any]:
        """Return all remaining rows."""
        remaining = self._rows[self._index :]
        self._index = len(self._rows)
        return remaining


class DsqlConnectionProxy:
    """sqlite3-like connection facade over a psycopg connection.

    Accepts ``?`` placeholders and common SQLite insert idioms so
    ``StudentStore`` can share query text with the DSQL dialect.
    """

    def __init__(self, raw: Any):
        self._raw = raw

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> DsqlCursorResult:
        """Execute one adapted statement and return a fetchable result."""
        adapted = adapt_sqlite_sql(sql)
        values = tuple(params or ())
        with self._raw.cursor() as cursor:
            cursor.execute(adapted, values)
            rows: list[Any] = []
            if cursor.description is not None:
                columns = [col.name for col in cursor.description]
                for raw_row in cursor.fetchall():
                    rows.append(_Row(columns, raw_row))
            rowcount = int(cursor.rowcount or 0)
        return DsqlCursorResult(rows, rowcount)

    def executescript(self, script: str) -> None:
        """Execute multiple DDL/DML statements, skipping SQLite PRAGMAs."""
        for statement in _split_statements(script):
            upper = statement.strip().upper()
            if not upper or upper.startswith("PRAGMA"):
                continue
            self.execute(strip_foreign_keys(statement))

    def commit(self) -> None:
        """Commit the underlying transaction."""
        self._raw.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._raw.close()

    def __enter__(self) -> DsqlConnectionProxy:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self._raw.rollback()
        finally:
            self.close()


class _Row(dict):
    """Mapping row that also supports SQLite-style ``row['col']`` access.

    Aurora DSQL/PostgreSQL folds unquoted identifiers to lowercase, while the
    existing StudentStore queries use camelCase keys. Lookups are therefore
    case-insensitive.
    """

    def __init__(self, columns: list[str], values: Sequence[Any]):
        super().__init__(zip(columns, values))
        self._by_lower = {str(column).lower(): column for column in columns}

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        if key in self:
            return super().__getitem__(key)
        mapped = self._by_lower.get(str(key).lower())
        if mapped is not None:
            return super().__getitem__(mapped)
        raise KeyError(key)


def _split_statements(script: str) -> list[str]:
    """Split a SQL script on semicolons outside quotes."""
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    for char in script:
        if char == "'":
            in_single = not in_single
            current.append(char)
        elif char == ";" and not in_single:
            statements.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def is_retryable_db_error(error: BaseException) -> bool:
    """Return whether *error* is an Aurora DSQL OCC/serialization conflict."""
    sqlstate = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
    if sqlstate in _RETRYABLE_SQLSTATES:
        return True
    text = str(error).lower()
    return "could not serialize" in text or "serialization failure" in text


def connect_dsql(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    user: str = "admin",
    port: int = 5432,
    token_provider: Callable[[], str] | None = None,
    connect_fn: Callable[..., Any] | None = None,
    max_attempts: int = 3,
) -> DsqlConnectionProxy:
    """Open one DSQL connection using a fresh IAM auth token.

    Retries a small number of times on retryable serialization errors during
    connect only. Callers must not log the token.
    """
    if not endpoint.strip():
        raise ValueError("DSQL_ENDPOINT is required when DATABASE_PROVIDER=dsql")
    if not region.strip():
        raise ValueError("AWS_REGION is required when DATABASE_PROVIDER=dsql")

    def _default_token() -> str:
        return generate_dsql_auth_token(endpoint=endpoint, region=region)

    provider = token_provider or _default_token
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        token = provider()
        try:
            if connect_fn is None:
                try:
                    import psycopg
                except ImportError as error:  # pragma: no cover
                    raise RuntimeError(
                        "psycopg is required when DATABASE_PROVIDER=dsql"
                    ) from error

                def _connect(**kwargs: Any) -> Any:
                    return psycopg.connect(**kwargs)

                connect_fn = _connect
            raw = connect_fn(
                host=endpoint,
                port=port,
                dbname=database,
                user=user,
                password=token,
                sslmode="require",
            )
            return DsqlConnectionProxy(raw)
        except Exception as error:  # noqa: BLE001 - classified below
            last_error = error
            if attempt >= max_attempts or not is_retryable_db_error(error):
                logger.exception(
                    "DSQL connection failed (attempt %s/%s)", attempt, max_attempts
                )
                raise
            sleep_for = (0.05 * (2 ** (attempt - 1))) + random.uniform(0, 0.05)
            time.sleep(sleep_for)
    assert last_error is not None
    raise last_error


@contextmanager
def dsql_connection(**kwargs: Any) -> Iterator[DsqlConnectionProxy]:
    """Context manager that opens and closes one DSQL connection."""
    connection = connect_dsql(**kwargs)
    try:
        yield connection
        connection.commit()
    except Exception:
        try:
            connection._raw.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        connection.close()
