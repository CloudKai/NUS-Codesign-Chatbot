"""Page-run memo for repeated workspace reads inside one Streamlit script run.

The bucket is stored on ``st.session_state`` so it cannot leak across browser
sessions. It is keyed by the current full-script ``_app_runs`` counter, so a
later full rerun cannot reuse another run's payloads. Fragment refreshes keep
the same counter; writes invalidate matching keys instead. This is not an
authorization cache and must not be used for ``/auth/me`` or other
session-validity results.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import streamlit as st


T = TypeVar("T")

_SESSION_KEY = "_ui_run_memo"


def run_memo_token() -> tuple[Any, ...]:
    """Return the identity of the current full Streamlit script run.

    Fragment reruns keep the same ``_app_runs`` value. Writes invalidate
    matching keys, so a Sources fragment refresh after upload still refetches.

    Returns:
        A one-item tuple of the full-script counter (or ``None`` before init).
    """
    return (st.session_state.get("_app_runs"),)


def _bucket() -> dict[tuple[Any, ...], Any]:
    """Return the memo dict for this run, replacing a stale bucket if needed."""
    token = run_memo_token()
    stored = st.session_state.get(_SESSION_KEY)
    if not isinstance(stored, dict) or stored.get("token") != token:
        stored = {"token": token, "data": {}}
        st.session_state[_SESSION_KEY] = stored
    data = stored.get("data")
    if not isinstance(data, dict):
        data = {}
        stored["data"] = data
    return data


def memoized(key: tuple[Any, ...], loader: Callable[[], T]) -> T:
    """Return a cached value for ``key`` in this run, loading it once.

    Args:
        key: Tuple identity for one read (method name plus arguments).
        loader: Called at most once per matching key in this run.

    Returns:
        The cached or freshly loaded value.
    """
    data = _bucket()
    if key in data:
        return data[key]
    value = loader()
    data[key] = value
    return value


def invalidate_memo(*prefixes: tuple[Any, ...]) -> None:
    """Drop memo entries that start with any of ``prefixes``.

    Args:
        prefixes: Key prefixes to remove. With no prefixes, clear the run memo.
    """
    data = _bucket()
    if not prefixes:
        data.clear()
        return
    for existing in list(data):
        for prefix in prefixes:
            if existing[: len(prefix)] == prefix:
                del data[existing]
                break
