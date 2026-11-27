"""Shared browser-origin equivalence for the same-origin request guards.

The CSRF guards compare a browser ``Origin`` header (or ``Host`` header) with
the configured public URL. Locally the server binds ``127.0.0.1:8000`` while
students often open ``http://localhost:8000``; hosts that differ only as
loopback aliases with the same scheme and port are one origin in practice.
Foreign hosts and ports still never match.
"""
from urllib.parse import urlparse

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _netloc_parts(netloc: str) -> tuple[str, int | None]:
    """Split a ``host[:port]`` pair into a lowercased hostname and port."""
    parsed = urlparse(f"//{netloc}")
    return (parsed.hostname or "").lower(), parsed.port


def same_netloc(left: str, right: str) -> bool:
    """Return whether two ``host[:port]`` pairs match, counting loopback
    aliases (``localhost``, ``127.0.0.1``, ``::1``) as one host."""
    left_host, left_port = _netloc_parts(left)
    right_host, right_port = _netloc_parts(right)
    if left_port != right_port:
        return False
    return left_host == right_host or {left_host, right_host} <= _LOOPBACK_HOSTS


def same_public_origin(supplied: str, expected: str) -> bool:
    """Return whether a browser origin URL matches the configured public URL.

    The scheme must match exactly; hosts compare through :func:`same_netloc`.
    """
    supplied_scheme = (urlparse(supplied or "").scheme or "").lower()
    expected_scheme = (urlparse(expected or "").scheme or "").lower()
    if not expected_scheme or supplied_scheme != expected_scheme:
        return False
    return same_netloc(urlparse(supplied or "").netloc, urlparse(expected).netloc)


def same_configured_origin(supplied: str, *expected_urls: str) -> bool:
    """Return whether a browser origin matches any configured server origin.

    Development reaches one server through two URLs: the public entrypoint
    (Caddy) and the direct API bind. A browser tab on either sends an Origin
    that is this same server, so both count; foreign hosts and ports match none.
    """
    return any(same_public_origin(supplied, url) for url in expected_urls if url)
