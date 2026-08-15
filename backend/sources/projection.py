"""Resolve notebook source bytes and image inputs across storage adapters."""

from __future__ import annotations

import base64
import mimetypes
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from backend.settings import settings
from backend.student_store import StudentStore


def safe_source_file_path(source: dict[str, Any]) -> Path | None:
    """Resolve a notebook source path when it stays inside ``files_dir``.

    Returns:
        Absolute path when the file exists and is owned by the configured files
        root; otherwise ``None`` (missing path, missing file, object storage,
        or traversal).
    """
    metadata = source.get("metadata") or {}
    if metadata.get("storage_provider") in {"s3", "memory"}:
        return None
    if source.get("object_key") and metadata.get("storage_provider") in {
        "s3",
        "memory",
    }:
        return None
    path_value = source.get("path") or metadata.get("local_path")
    if not path_value:
        return None
    path = Path(str(path_value)).resolve()
    files_root = settings.files_dir.resolve()
    if not path.is_file() or files_root not in path.parents:
        return None
    return path


def read_source_bytes(source: dict[str, Any]) -> bytes | None:
    """Return source file bytes from local disk or configured object storage."""
    metadata = source.get("metadata") or {}
    object_key = (
        source.get("object_key")
        or metadata.get("object_key")
        or (
            source.get("path")
            if metadata.get("storage_provider") in {"s3", "memory"}
            else None
        )
    )
    if object_key:
        from backend.persistence.factory import file_storage_for_key

        try:
            return file_storage_for_key(str(object_key)).get_bytes(str(object_key))
        except FileNotFoundError:
            return None
    path = safe_source_file_path(source)
    if path is None:
        # Compatibility: path may be a local_path stored only in metadata.
        local_path = metadata.get("local_path")
        if local_path:
            candidate = {**source, "path": local_path, "metadata": metadata}
            path = safe_source_file_path(candidate)
            if path is not None:
                return path.read_bytes()
        return None
    return path.read_bytes()


def source_image_input(source: dict[str, Any]) -> dict[str, str] | None:
    """Build an OpenAI-style ``input_image`` part for a notebook image source.

    Returns None when the source is not an image, the path is missing, or the
    file is outside the configured files directory (path-traversal guard).
    """
    if source.get("kind") != "image":
        return None
    payload = read_source_bytes(source)
    if payload is None:
        return None
    name = str(source.get("title") or source.get("path") or "image.png")
    mime = str(
        source.get("mime")
        or mimetypes.guess_type(name)[0]
        or "image/png"
    )
    encoded = base64.b64encode(payload).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": "auto",
    }


def image_inputs_for_source_ids(
    store: StudentStore,
    thread_id: str,
    source_ids: Iterable[str],
) -> list[dict[str, str]]:
    """Resolve selected notebook images into coach-ready image payloads.

    Resolution stays in the source/infrastructure layer so providers and future
    AWS adapters can swap storage backends without changing the workflow.
    """
    resolved: list[dict[str, str]] = []
    for source_id in source_ids:
        source = store.get_source(thread_id, str(source_id))
        if not source:
            continue
        image_part = source_image_input(source)
        if not image_part:
            continue
        resolved.append(
            {
                "source_id": str(source["id"]),
                "mime": str(source.get("mime") or "image/png"),
                "data_url": image_part["image_url"],
            }
        )
    return resolved
