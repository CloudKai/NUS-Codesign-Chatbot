"""Copy and transfer a browser guest workspace into a verified account."""

from __future__ import annotations

from typing import Any

from backend.persistence.object_keys import notebook_prefix
from backend.persistence.ports import FileStorage
from backend.student_store import StudentStore


def copy_guest_objects(
    *, storage: FileStorage, guest_user_id: str, account_user_id: str,
    notebook_ids: list[str], required_keys: list[str] | None = None,
) -> dict[str, str]:
    """Copy guest notebook objects to account prefixes and verify each byte set.

    Existing destination objects are accepted only when their content matches,
    making retry safe without allowing an account object to be overwritten.
    """
    mapping: dict[str, str] = {}
    for notebook_id in notebook_ids:
        old_prefix = notebook_prefix(user_id=guest_user_id, notebook_id=notebook_id)
        new_prefix = notebook_prefix(user_id=account_user_id, notebook_id=notebook_id)
        for item in storage.list_prefix(old_prefix):
            source_bytes = storage.get_bytes(item.key)
            destination = new_prefix + item.key[len(old_prefix):]
            if storage.exists(destination):
                if storage.get_bytes(destination) != source_bytes:
                    raise ValueError("Account storage already contains a different object")
            else:
                storage.put_bytes(key=destination, data=source_bytes)
                if storage.get_bytes(destination) != source_bytes:
                    raise OSError("Copied object verification failed")
            mapping[item.key] = destination
    for key in required_keys or []:
        if key.startswith("users/") and key not in mapping:
            raise FileNotFoundError("A referenced private upload is unavailable")
    return mapping


def cleanup_guest_objects(
    *, storage: FileStorage, guest_user_id: str, notebook_ids: list[str]
) -> None:
    """Best-effort cleanup after database ownership and references commit."""
    for notebook_id in notebook_ids:
        prefix = notebook_prefix(user_id=guest_user_id, notebook_id=notebook_id)
        try:
            storage.delete_prefix(prefix)
        except Exception:
            # Orphaned guest objects are inaccessible after claim; cleanup is
            # safe to retry and must not turn a committed claim into a failure.
            continue


def safe_preview_account(profile: dict[str, Any]) -> dict[str, str]:
    """Select non-secret account labels for the confirmation preview."""
    return {
        "display_name": str(profile.get("display_name") or "Student")[:80],
        "email": str(profile.get("email") or "")[:254],
    }


def complete_guest_claim(
    *, store: StudentStore, storage: FileStorage, secret: str,
    target_user_id: str, operation_id: str,
) -> dict[str, Any] | None:
    """Finish one account-bound guest claim, preserving guest access on failure.

    Returns the prior result for an idempotent replay, or ``None`` when the
    credential or preview is no longer claimable. Uploaded objects are copied
    before the atomic notebook ownership change; old objects are cleaned only
    after that change commits.
    """
    replay = store.guest_claim_transfer(
        secret=secret, target_user_id=target_user_id, operation_id=operation_id,
        expected_sources=[], expected_notebooks=[], expected_fingerprint="", key_map={},
    )
    if replay is not None:
        cleanup = store.guest_claim_cleanup_info(
            secret=secret, target_user_id=target_user_id, operation_id=operation_id,
        )
        if cleanup:
            cleanup_guest_objects(
                storage=storage, guest_user_id=cleanup[0], notebook_ids=cleanup[1],
            )
        return replay

    snapshot = store.begin_guest_claim(
        secret=secret, target_user_id=target_user_id, operation_id=operation_id,
    )
    if snapshot is None:
        return None
    if snapshot.get("preview_changed"):
        raise ValueError("Guest workspace changed during claim")

    guest_user_id = str(snapshot["guest_user_id"])
    notebook_ids = [str(item[0]) for item in snapshot["notebooks"]]
    try:
        key_map = copy_guest_objects(
            storage=storage, guest_user_id=guest_user_id,
            account_user_id=target_user_id, notebook_ids=notebook_ids,
            required_keys=[
                str(key)
                for _source_id, object_key, extracted_key in snapshot["sources"]
                for key in (object_key, extracted_key) if key
            ],
        )
        result = store.guest_claim_transfer(
            secret=secret, target_user_id=target_user_id,
            operation_id=operation_id, expected_sources=snapshot["sources"],
            expected_notebooks=snapshot["notebooks"],
            expected_fingerprint=snapshot["fingerprint"], key_map=key_map,
        )
        if result is None:
            raise ValueError("Guest claim could not be completed")
    except Exception:
        store.release_guest_claim(
            secret=secret, target_user_id=target_user_id, operation_id=operation_id,
        )
        raise

    cleanup_guest_objects(
        storage=storage, guest_user_id=guest_user_id, notebook_ids=notebook_ids,
    )
    return result


def claim_guest_workspace_automatically(
    *, store: StudentStore, secret: str, target_user_id: str,
    storage: FileStorage | None = None,
) -> dict[str, Any] | None:
    """Claim the browser's valid guest workspace after verified Cognito sign-in.

    A missing, expired, or unrelated guest credential returns ``None`` without
    touching any account. The persisted operation ID makes callback retries
    safe for the same verified account.
    """
    preview = store.create_guest_claim_preview(
        secret=secret, target_user_id=target_user_id,
    )
    if preview is None:
        return None
    if storage is None:
        from backend.persistence.factory import get_file_storage

        storage = get_file_storage()
    result = complete_guest_claim(
        store=store, storage=storage, secret=secret,
        target_user_id=target_user_id,
        operation_id=str(preview["operation_id"]),
    )
    if result is None:
        raise ValueError("Guest claim became unavailable after preview")
    return result
