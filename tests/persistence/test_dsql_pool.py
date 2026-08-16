"""Unit tests for DSQL connection pooling (backend.persistence.dsql_connection).

No real network/DSQL cluster involved — psycopg.Connection and
psycopg_pool.ConnectionPool are monkeypatched with fakes so these stay fast,
deterministic, and mock-first per tests/AGENTS.md.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.persistence import dsql_connection as dc
from backend.persistence.dsql_connection import (
    DsqlConnectionProxy,
    _make_token_connection_class,
    _pool_key,
    get_dsql_pool,
    pooled_connect_dsql,
)


@pytest.fixture(autouse=True)
def _clear_pool_registry():
    """Each test starts with an empty pool registry regardless of test order."""
    dc._pool_registry.clear()
    yield
    dc._pool_registry.clear()


class _FakePsycopgConnection:
    """Stand-in for psycopg.Connection whose .connect() records its kwargs.

    Recorded on the module-level list, not a ``cls`` attribute: ``super().connect()``
    called from a subclass's classmethod still receives that subclass as ``cls``, so
    ``cls.last_kwargs = ...`` would shadow-create the attribute on the subclass
    instead of mutating this base class's.
    """

    recorded_kwargs: list[dict[str, Any]] = []

    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: Any) -> "_FakePsycopgConnection":
        _FakePsycopgConnection.recorded_kwargs.append(kwargs)
        return cls()


class _FakePool:
    """Stand-in for psycopg_pool.ConnectionPool that never opens a real socket."""

    instances: list["_FakePool"] = []

    def __init__(self, conninfo: str = "", **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.closed = False
        self._checked_out: list[object] = []
        _FakePool.instances.append(self)

    def getconn(self) -> object:
        conn = object()
        self._checked_out.append(conn)
        return conn

    def putconn(self, conn: object) -> None:
        self._checked_out.remove(conn)

    def close(self) -> None:
        self.closed = True


def test_pool_key_distinguishes_endpoint_database_user_port():
    """Different connection targets must not share a pool."""
    a = _pool_key(endpoint="db-a", region="us-west-2", database="postgres", user="co_design_app", port=5432)
    b = _pool_key(endpoint="db-b", region="us-west-2", database="postgres", user="co_design_app", port=5432)
    assert a != b


def test_get_dsql_pool_reuses_same_pool_for_same_key(monkeypatch: pytest.MonkeyPatch):
    """Two calls with identical connection params return the same pool object."""
    monkeypatch.setattr("psycopg_pool.ConnectionPool", _FakePool)
    _FakePool.instances.clear()

    first = get_dsql_pool(endpoint="db-a", region="us-west-2", database="postgres", user="co_design_app")
    second = get_dsql_pool(endpoint="db-a", region="us-west-2", database="postgres", user="co_design_app")

    assert first is second
    assert len(_FakePool.instances) == 1


def test_get_dsql_pool_opens_a_new_pool_per_distinct_key(monkeypatch: pytest.MonkeyPatch):
    """Different endpoints get their own, independent pool."""
    monkeypatch.setattr("psycopg_pool.ConnectionPool", _FakePool)
    _FakePool.instances.clear()

    get_dsql_pool(endpoint="db-a", region="us-west-2", database="postgres", user="co_design_app")
    get_dsql_pool(endpoint="db-b", region="us-west-2", database="postgres", user="co_design_app")

    assert len(_FakePool.instances) == 2


def test_get_dsql_pool_passes_sizing_and_static_connect_kwargs(monkeypatch: pytest.MonkeyPatch):
    """Pool sizing and connection kwargs (minus password) reach the pool as configured."""
    monkeypatch.setattr("psycopg_pool.ConnectionPool", _FakePool)
    _FakePool.instances.clear()

    get_dsql_pool(
        endpoint="db-a",
        region="us-west-2",
        database="postgres",
        user="co_design_app",
        min_size=3,
        max_size=7,
        max_lifetime_seconds=123,
        max_idle_seconds=45,
    )

    pool = _FakePool.instances[0]
    assert pool.kwargs["min_size"] == 3
    assert pool.kwargs["max_size"] == 7
    assert pool.kwargs["max_lifetime"] == 123
    assert pool.kwargs["max_idle"] == 45
    assert pool.kwargs["kwargs"]["host"] == "db-a"
    assert pool.kwargs["kwargs"]["dbname"] == "postgres"
    assert pool.kwargs["kwargs"]["user"] == "co_design_app"
    assert "password" not in pool.kwargs["kwargs"]  # injected per-connection, not static


def test_token_connection_class_mints_a_fresh_token_per_connect(monkeypatch: pytest.MonkeyPatch):
    """The pool's connection_class must fetch a fresh token and pass it as password."""
    monkeypatch.setattr("psycopg.Connection", _FakePsycopgConnection)
    _FakePsycopgConnection.recorded_kwargs = []
    calls = {"count": 0}

    def fake_token_provider() -> str:
        calls["count"] += 1
        return f"token-{calls['count']}"

    connection_class = _make_token_connection_class(fake_token_provider)

    connection_class.connect(host="db-a")
    connection_class.connect(host="db-a")

    assert [kw["password"] for kw in _FakePsycopgConnection.recorded_kwargs] == ["token-1", "token-2"]
    assert calls["count"] == 2  # one fresh token per physical connect, not cached


def test_pooled_connect_dsql_checks_out_and_releases_back_to_pool(monkeypatch: pytest.MonkeyPatch):
    """close() on the returned proxy must return the connection to the pool, not close it."""
    monkeypatch.setattr("psycopg_pool.ConnectionPool", _FakePool)
    _FakePool.instances.clear()

    proxy = pooled_connect_dsql(endpoint="db-a", region="us-west-2", database="postgres", user="co_design_app")
    pool = _FakePool.instances[0]
    assert len(pool._checked_out) == 1

    proxy.close()
    assert len(pool._checked_out) == 0  # returned, not leaked
    assert pool.closed is False  # the pool itself stays open


def test_pooled_connect_dsql_rejects_admin_user():
    """Same guardrail as connect_dsql(): the app runtime must never use the admin role."""
    with pytest.raises(ValueError, match="admin"):
        pooled_connect_dsql(endpoint="db-a", region="us-west-2", user="admin")


def test_pooled_connect_dsql_rejects_missing_endpoint():
    with pytest.raises(ValueError, match="DSQL_ENDPOINT"):
        pooled_connect_dsql(endpoint="", region="us-west-2")


def test_connection_proxy_close_prefers_release_over_raw_close():
    """When a release callback is given (pooled case), close() must not touch raw.close()."""

    class _RawSpy:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    raw = _RawSpy()
    released = {"called": False}
    proxy = DsqlConnectionProxy(raw, release=lambda: released.__setitem__("called", True))

    proxy.close()

    assert released["called"] is True
    assert raw.closed is False  # release, not a real close


def test_connection_proxy_close_falls_back_to_raw_close_when_unpooled():
    """No release callback (non-pooled connect_dsql path): close() still closes the socket."""

    class _RawSpy:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    raw = _RawSpy()
    proxy = DsqlConnectionProxy(raw)

    proxy.close()

    assert raw.closed is True


def test_close_all_dsql_pools_closes_every_registered_pool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("psycopg_pool.ConnectionPool", _FakePool)
    _FakePool.instances.clear()

    get_dsql_pool(endpoint="db-a", region="us-west-2", database="postgres", user="co_design_app")
    get_dsql_pool(endpoint="db-b", region="us-west-2", database="postgres", user="co_design_app")

    dc.close_all_dsql_pools()

    assert all(pool.closed for pool in _FakePool.instances)
    assert dc._pool_registry == {}
