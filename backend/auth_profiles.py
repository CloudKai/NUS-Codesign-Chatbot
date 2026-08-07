"""Cognito identity claims to application user profile rules.

Pure helpers keep educational/persistence logic free of Streamlit and Cognito
SDKs. Persistence is performed by ``StudentStore`` adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.student_store import StudentStore

STUDENT_ROLE = "student"
PROTECTED_ROLES = frozenset({"lecturer", "admin"})


@dataclass(frozen=True)
class AuthProfile:
    """Application user profile bound to a Cognito subject."""

    user_id: str
    cognito_sub: str
    store_identifier: str
    email: str | None
    display_name: str
    role: str
    created: bool


def store_identifier_for_sub(cognito_sub: str) -> str:
    """Return the StudentStore owner identifier for a Cognito subject."""
    return f"cognito:{cognito_sub.strip()}"


def resolve_display_name(claims: Mapping[str, Any]) -> str:
    """Choose a display name from Cognito claims with safe fallbacks."""
    for key in ("given_name", "name", "preferred_username", "cognito:username"):
        value = str(claims.get(key) or "").strip()
        if value:
            return value[:80]
    email = str(claims.get("email") or "").strip()
    if email and "@" in email:
        return email.split("@", 1)[0][:80]
    if email:
        return email[:80]
    return "Student"


def resolve_role(existing_role: str | None) -> str:
    """Return the role to persist; never elevate from client claims."""
    role = str(existing_role or STUDENT_ROLE).strip().lower() or STUDENT_ROLE
    if role in PROTECTED_ROLES:
        return role
    return STUDENT_ROLE


def sync_authenticated_user(
    claims: Mapping[str, Any],
    *,
    store: StudentStore | None = None,
) -> AuthProfile:
    """Upsert the Cognito user profile and return the bound store identity.

    Args:
        claims: Identity claims from ``st.user`` (must include ``sub``).
        store: Optional store instance; defaults to a temporary admin connection
            used only for user-row upsert before the UI binds the owner store.

    Returns:
        AuthProfile with store identifier ``cognito:{sub}``.

    Raises:
        ValueError: If ``sub`` is missing.
    """
    cognito_sub = str(claims.get("sub") or "").strip()
    if not cognito_sub:
        raise ValueError("Cognito sub claim is required for profile sync")
    email_raw = str(claims.get("email") or "").strip() or None
    display_name = resolve_display_name(claims)
    identifier = store_identifier_for_sub(cognito_sub)
    active_store = store or StudentStore(identifier=identifier)
    result = active_store.upsert_cognito_user(
        cognito_sub=cognito_sub,
        identifier=identifier,
        email=email_raw,
        display_name=display_name,
    )
    return AuthProfile(
        user_id=str(result["id"]),
        cognito_sub=cognito_sub,
        store_identifier=identifier,
        email=email_raw,
        display_name=str(result.get("display_name") or display_name),
        role=str(result.get("role") or STUDENT_ROLE),
        created=bool(result.get("created")),
    )
