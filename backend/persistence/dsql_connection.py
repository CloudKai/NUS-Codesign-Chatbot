"""Aurora DSQL connection helpers (IAM auth, OCC retries, SQL adaptation).

Aurora DSQL is PostgreSQL-wire compatible but not identical to PostgreSQL:
no foreign keys, no temporary tables, optimistic concurrency (retry on
serialization failures), and JSON should be stored as TEXT. Authentication
uses short-lived IAM tokens via ``generate_db_connect_auth_token`` (DbConnect)
— never a permanent password and never DbConnectAdmin for the app runtime role.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Sequence, TypeVar

logger = logging.getLogger(__name__)

# SQLSTATE for serialization/OCC conflicts that callers should retry.
_RETRYABLE_SQLSTATES = {"40001", "40P01"}

# Default bounded OCC attempts for write transactions.
DEFAULT_OCC_MAX_ATTEMPTS = 5

T = TypeVar("T")


def generate_dsql_auth_token(
    *,
    endpoint: str,
    region: str,
    expires_seconds: int = 900,
    client: Any | None = None,
) -> str:
    """Generate a short-lived DSQL IAM DbConnect auth token.

    Uses ``generate_db_connect_auth_token`` (custom/runtime role), not
    DbConnectAdmin. Callers must not log the token.

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
    token = client.generate_db_connect_auth_token(
        Hostname=endpoint,
        Region=region,
        ExpiresIn=expires_seconds,
    )
    if not token:
        raise RuntimeError("DSQL auth token generation returned an empty token")
    return str(token)


def generate_dsql_admin_auth_token(
    *,
    endpoint: str,
    region: str,
    expires_seconds: int = 900,
    client: Any | None = None,
) -> str:
    """Generate a short-lived DSQL IAM DbConnectAdmin auth token.

    Uses ``generate_db_connect_admin_auth_token`` for schema migration only.
    Never call this from application runtime (``co_design_app``).

    Returns:
        Token string used as the admin database password for one connection.

    Raises:
        RuntimeError: when boto3 is unavailable or token generation fails.
    """
    if client is None:
        try:
            import boto3
        except ImportError as error:  # pragma: no cover - production dependency
            raise RuntimeError(
                "boto3 is required for DSQL admin bootstrap"
            ) from error
        client = boto3.client("dsql", region_name=region)
    token = client.generate_db_connect_admin_auth_token(
        Hostname=endpoint,
        Region=region,
        ExpiresIn=expires_seconds,
    )
    if not token:
        raise RuntimeError(
            "DSQL admin auth token generation returned an empty token"
        )
    return str(token)


def adapt_sqlite_sql(sql: str) -> str:
    """Translate SQLite-oriented SQL fragments to DSQL/PostgreSQL placeholders.

    Converts ``?`` placeholders to ``%s`` and maps the generic SQLite
    ``INSERT OR IGNORE`` form. Callers that need an upsert must provide an
    explicit, table-specific ``ON CONFLICT`` clause.
    """
    text = sql.strip()
    upper = text.upper()
    if upper.startswith("INSERT OR IGNORE INTO"):
        text = "INSERT INTO" + text[len("INSERT OR IGNORE INTO") :]
        if "ON CONFLICT" not in text.upper():
            text = text.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    elif upper.startswith("INSERT OR REPLACE INTO"):
        raise ValueError(
            "INSERT OR REPLACE is not portable; use an explicit ON CONFLICT clause"
        )
    return _qmark_to_percent(text)


def _qmark_to_percent(sql: str) -> str:
    """Replace unbound ``?`` placeholders with ``%s`` outside string literals.

    Also escapes literal ``%`` as ``%%`` so psycopg does not treat LIKE/JSON
    fragments such as ``LIKE '%"_internal_type"%'`` as placeholders.
    """
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
        elif char == "%":
            # psycopg pyformat: every literal percent must be doubled, including
            # those inside SQL string literals used by LIKE filters.
            result.append("%%")
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

    def __init__(self, raw: Any, *, release: Callable[[], None] | None = None):
        """Wrap *raw*. If *release* is given, ``close()`` calls it instead of
        closing the socket — used to return a pooled connection to its pool
        rather than tearing it down.
        """
        self._raw = raw
        self._release = release

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
        """Execute multiple DML statements in the current transaction.

        Intended for tests only. Production DDL must use
        ``scripts/init_dsql.py`` (one DDL per committed transaction).
        """
        for statement in split_sql_statements(script):
            upper = statement.strip().upper()
            if not upper or upper.startswith("PRAGMA"):
                continue
            self.execute(strip_foreign_keys(statement))

    def commit(self) -> None:
        """Commit the underlying transaction."""
        self._raw.commit()

    def rollback(self) -> None:
        """Roll back the underlying transaction."""
        self._raw.rollback()

    def close(self) -> None:
        """Release the underlying connection: return it to its pool, or close it."""
        if self._release is not None:
            self._release()
        else:
            self._raw.close()

    def __enter__(self) -> DsqlConnectionProxy:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
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


def split_sql_statements(script: str) -> list[str]:
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


# Backwards-compatible private alias used by older call sites/tests.
_split_statements = split_sql_statements


def is_retryable_db_error(error: BaseException) -> bool:
    """Return whether *error* is an Aurora DSQL OCC/serialization conflict."""
    sqlstate = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
    if sqlstate in _RETRYABLE_SQLSTATES:
        return True
    # botocore / nested causes
    cause = getattr(error, "__cause__", None)
    if cause is not None and cause is not error:
        if is_retryable_db_error(cause):
            return True
    text = str(error).lower()
    return (
        "could not serialize" in text
        or "serialization failure" in text
        or "occonflict" in text.replace(" ", "")
        or "optimistic concurrency" in text
    )


def run_dsql_transaction(
    work: Callable[[], T],
    *,
    max_attempts: int = DEFAULT_OCC_MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run an idempotent unit of work with OCC retries on SQLSTATE 40001.

    Retries the *entire* ``work`` callback after rollback/failure. Callers must
    keep ``work`` free of non-idempotent external side effects (S3 uploads,
    emails, etc.) or perform those only after the DB transaction succeeds.

    Args:
        work: Zero-argument callable that opens its own connection/transaction.
        max_attempts: Inclusive upper bound on attempts (default 5).
        sleep: Injectable sleeper for tests.

    Returns:
        The return value of ``work`` on success.

    Raises:
        The last non-retryable or exhausted error from ``work``.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return work()
        except Exception as error:  # noqa: BLE001 - classified below
            last_error = error
            if attempt >= max_attempts or not is_retryable_db_error(error):
                raise
            sleep_for = (0.05 * (2 ** (attempt - 1))) + random.uniform(0, 0.05)
            logger.warning(
                "DSQL OCC conflict on attempt %s/%s; retrying in %.3fs",
                attempt,
                max_attempts,
                sleep_for,
            )
            sleep(sleep_for)
    assert last_error is not None
    raise last_error


def connect_dsql(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    user: str = "co_design_app",
    port: int = 5432,
    token_provider: Callable[[], str] | None = None,
    connect_fn: Callable[..., Any] | None = None,
) -> DsqlConnectionProxy:
    """Open one DSQL connection using a fresh IAM DbConnect auth token.

    Defaults to the runtime role ``co_design_app``. Do not pass ``admin`` for
    application traffic. OCC retries belong in ``run_dsql_transaction``, not
    around ``connect`` alone.
    """
    if not endpoint.strip():
        raise ValueError("DSQL_ENDPOINT is required when DATABASE_PROVIDER=dsql")
    if not region.strip():
        raise ValueError("AWS_REGION is required when DATABASE_PROVIDER=dsql")
    role = (user or "").strip()
    if not role:
        raise ValueError("DSQL_USER is required when DATABASE_PROVIDER=dsql")
    if role.lower() == "admin":
        raise ValueError(
            "DSQL_USER=admin is not allowed for application runtime; "
            "use co_design_app (admin is for scripts/init_dsql.py only)"
        )

    def _default_token() -> str:
        return generate_dsql_auth_token(endpoint=endpoint, region=region)

    provider = token_provider or _default_token
    token = provider()
    active_connect = connect_fn
    if active_connect is None:
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover
            raise RuntimeError(
                "psycopg is required when DATABASE_PROVIDER=dsql"
            ) from error

        def _connect(**kwargs: Any) -> Any:
            return psycopg.connect(**kwargs)

        active_connect = _connect
    raw = active_connect(
        host=endpoint,
        port=port,
        dbname=database,
        user=role,
        password=token,
        sslmode="verify-full",
        sslrootcert=os.getenv(
            "DSQL_SSLROOTCERT",
            "system",
        ),
    )
    return DsqlConnectionProxy(raw)


@contextmanager
def dsql_connection(**kwargs: Any) -> Iterator[DsqlConnectionProxy]:
    """Context manager that opens and closes one DSQL connection."""
    connection = connect_dsql(**kwargs)
    try:
        yield connection
        connection.commit()
    except Exception:
        try:
            connection.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        connection.close()


# --- Connection pooling ----------------------------------------------------
#
# connect_dsql() above pays a fresh TLS handshake plus a live AWS API call
# (IAM DbConnect token mint) on every single call. Under concurrent load that
# is the dominant cost, not the query itself. A pooled connection reuses an
# already-authenticated socket across many checkouts; the IAM token is only
# needed again when the pool opens a brand-new physical connection (at
# startup, on growth, or when a connection is recycled), so pooling is safe
# as long as connections are recycled well before the token's ExpiresIn.

_pool_registry: dict[tuple[str, str, str, str, int], Any] = {}
_pool_registry_lock = threading.Lock()


def _pool_key(*, endpoint: str, region: str, database: str, user: str, port: int) -> tuple[str, str, str, str, int]:
    return (endpoint, region, database, user, port)


def _make_token_connection_class(token_provider: Callable[[], str]) -> type:
    """Build a psycopg Connection subclass that injects a fresh token per connect.

    The pool calls ``connection_class.connect(conninfo, **kwargs)`` every time
    it opens a *new* physical connection (not on every checkout). Overriding
    ``connect`` here is the documented way to supply a credential that must be
    re-fetched per physical connection rather than baked into a static conninfo.
    """
    import psycopg

    class _TokenConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs: Any) -> Any:
            kwargs = dict(kwargs)
            kwargs["password"] = token_provider()
            return super().connect(conninfo, **kwargs)

    return _TokenConnection


def get_dsql_pool(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    user: str = "co_design_app",
    port: int = 5432,
    token_provider: Callable[[], str] | None = None,
    min_size: int = 2,
    max_size: int = 10,
    max_lifetime_seconds: float = 600,
    max_idle_seconds: float = 300,
) -> Any:
    """Return the process-wide pool for one (endpoint, database, user), opening it if needed.

    One pool is shared across every ``DsqlStudentStore`` instance in the
    process (they all connect as the same ``co_design_app`` role; per-student
    isolation is enforced by application-level ownership checks, not by
    per-student connections), so pooling is process-wide, not per-store.
    """
    key = _pool_key(endpoint=endpoint, region=region, database=database, user=user, port=port)
    existing = _pool_registry.get(key)
    if existing is not None:
        return existing
    with _pool_registry_lock:
        existing = _pool_registry.get(key)
        if existing is not None:
            return existing
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as error:  # pragma: no cover - production dependency
            raise RuntimeError(
                "psycopg-pool is required for pooled DSQL connections "
                "(pip install 'psycopg[binary,pool]')"
            ) from error

        def _default_token() -> str:
            return generate_dsql_auth_token(endpoint=endpoint, region=region)

        provider = token_provider or _default_token
        connection_class = _make_token_connection_class(provider)
        pool = ConnectionPool(
            conninfo="",
            connection_class=connection_class,
            kwargs={
                "host": endpoint,
                "port": port,
                "dbname": database,
                "user": user,
                "sslmode": "verify-full",
                "sslrootcert": os.getenv("DSQL_SSLROOTCERT", "system"),
            },
            min_size=min_size,
            max_size=max_size,
            max_lifetime=max_lifetime_seconds,
            max_idle=max_idle_seconds,
            open=True,
        )
        _pool_registry[key] = pool
        logger.info(
            "Opened DSQL connection pool for %s (min=%s max=%s max_lifetime=%ss)",
            endpoint,
            min_size,
            max_size,
            max_lifetime_seconds,
        )
        return pool


def close_all_dsql_pools() -> None:
    """Close every pool opened via ``get_dsql_pool``. Call on process shutdown."""
    with _pool_registry_lock:
        for pool in _pool_registry.values():
            try:
                pool.close()
            except Exception:  # noqa: BLE001
                logger.warning("Error closing a DSQL connection pool", exc_info=True)
        _pool_registry.clear()


def pooled_connect_dsql(
    *,
    endpoint: str,
    region: str,
    database: str = "postgres",
    user: str = "co_design_app",
    port: int = 5432,
    token_provider: Callable[[], str] | None = None,
    min_size: int = 2,
    max_size: int = 10,
    max_lifetime_seconds: float = 600,
    max_idle_seconds: float = 300,
) -> DsqlConnectionProxy:
    """Check out one connection from the process-wide pool.

    Same validation and call shape as ``connect_dsql``, so it's a drop-in
    replacement at call sites. ``close()`` on the returned proxy returns the
    connection to the pool instead of closing the socket.
    """
    if not endpoint.strip():
        raise ValueError("DSQL_ENDPOINT is required when DATABASE_PROVIDER=dsql")
    if not region.strip():
        raise ValueError("AWS_REGION is required when DATABASE_PROVIDER=dsql")
    role = (user or "").strip()
    if not role:
        raise ValueError("DSQL_USER is required when DATABASE_PROVIDER=dsql")
    if role.lower() == "admin":
        raise ValueError(
            "DSQL_USER=admin is not allowed for application runtime; "
            "use co_design_app (admin is for scripts/init_dsql.py only)"
        )
    pool = get_dsql_pool(
        endpoint=endpoint,
        region=region,
        database=database,
        user=role,
        port=port,
        token_provider=token_provider,
        min_size=min_size,
        max_size=max_size,
        max_lifetime_seconds=max_lifetime_seconds,
        max_idle_seconds=max_idle_seconds,
    )
    raw = pool.getconn()
    return DsqlConnectionProxy(raw, release=lambda: pool.putconn(raw))
