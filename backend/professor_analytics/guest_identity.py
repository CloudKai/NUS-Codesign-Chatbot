"""Provider-neutral public identity projection for guest lecturer records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


_GUEST_IDENTIFIER_PREFIX = "guest:"
_PUBLIC_ID_PREFIX = "guest_"
_HASH_DOMAIN = b"co-design-professor-guest-identity-v1\0"


@dataclass(frozen=True)
class PublicStudentIdentity:
    """Safe identity fields to expose in lecturer analytics and research."""

    id: str
    name: str
    email: str | None
    is_guest: bool


def is_guest_identity(identifier: object, cognito_sub: object) -> bool:
    """Identify persisted guests from the guest owner namespace and no Cognito sub."""
    return str(identifier or "").startswith(_GUEST_IDENTIFIER_PREFIX) and not str(
        cognito_sub or ""
    ).strip()


def guest_public_id(owner_id: str) -> str:
    """Derive a stable, opaque lecturer ID from the immutable guest owner ID."""
    digest = hashlib.sha256(_HASH_DOMAIN + owner_id.encode("utf-8")).hexdigest()
    return f"{_PUBLIC_ID_PREFIX}{digest[:20]}"


def project_student_identity(
    *,
    owner_id: str,
    identifier: object,
    cognito_sub: object,
    display_name: object,
    email: object,
) -> PublicStudentIdentity:
    """Return lecturer-safe identity without leaking guest account identifiers."""
    if is_guest_identity(identifier, cognito_sub):
        public_id = guest_public_id(owner_id)
        suffix = public_id.removeprefix(_PUBLIC_ID_PREFIX)[-10:].upper()
        return PublicStudentIdentity(
            id=public_id,
            name=f"Guest {suffix}",
            email=None,
            is_guest=True,
        )
    return PublicStudentIdentity(
        id=owner_id,
        name=str(display_name or "Student"),
        email=str(email) if email is not None else None,
        is_guest=False,
    )
