"""Shared fixtures for the script and eval-command tests."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def _restore_socket_state():
    """Undo ``scripts.evals.lib.offline.block_network`` after every test.

    The offline eval commands call ``block_network`` at the start of ``main``. It
    replaces ``socket.socket.connect``, ``connect_ex``, ``socket.create_connection``
    and ``socket.getaddrinfo`` for the rest of the process. Some tests run a command's
    ``main`` in-process and patch ``evaluate_retrieval._block_network`` to avoid that,
    but a command now calls the ``lib`` function, so that patch no longer reaches it.
    This fixture keeps the blocked sockets from leaking into later tests.
    """
    saved = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.create_connection,
        socket.getaddrinfo,
    )
    yield
    (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.create_connection,
        socket.getaddrinfo,
    ) = saved
