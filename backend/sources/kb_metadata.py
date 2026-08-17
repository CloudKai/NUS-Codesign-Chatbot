"""Canonical Bedrock Knowledge Base sidecar payloads for course materials.

Sidecar JSON follows the Amazon S3 data-source metadata format in
https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html
(``fileName.extension.metadata.json`` next to the source object). The
``course_material_id`` attribute is filter-only (``includeForEmbedding`` false).
Identity always comes from :func:`backend.retrieval.course_material_id_from_object_key`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.retrieval import course_material_id_from_object_key

COURSE_MATERIAL_METADATA_KEY = "course_material_id"
METADATA_SUFFIX = ".metadata.json"


def sidecar_object_key(object_key: str) -> str:
    """Return the S3 key of the Bedrock metadata sidecar for one course object.

    Args:
        object_key: Canonical course object key such as
            ``course/lectureNotes/week1.pdf``.

    Returns:
        ``{object_key}.metadata.json``. Empty when *object_key* is empty.
    """
    cleaned = str(object_key or "").strip().lstrip("/")
    if not cleaned:
        return ""
    if cleaned.endswith(METADATA_SUFFIX):
        return cleaned
    return f"{cleaned}{METADATA_SUFFIX}"


def is_metadata_sidecar_key(object_key: str) -> bool:
    """Return whether *object_key* is itself a Bedrock metadata sidecar."""
    cleaned = str(object_key or "").strip().replace("\\", "/")
    return cleaned.endswith(METADATA_SUFFIX)


def bedrock_course_material_sidecar_payload(object_key: str) -> dict[str, Any]:
    """Return the Bedrock S3 sidecar document for one course object.

    Args:
        object_key: Canonical ``course/...`` object key.

    Returns:
        JSON-serializable sidecar body. Empty ``metadataAttributes`` when the
        canonical id cannot be derived.

    Raises:
        ValueError: When *object_key* is a sidecar path (do not nest metadata).
    """
    if is_metadata_sidecar_key(object_key):
        raise ValueError("refusing to generate metadata for a sidecar object")
    material_id = course_material_id_from_object_key(object_key)
    if not material_id:
        return {"metadataAttributes": {}}
    return {
        "metadataAttributes": {
            COURSE_MATERIAL_METADATA_KEY: {
                "value": {
                    "type": "STRING",
                    "stringValue": material_id,
                },
                "includeForEmbedding": False,
            }
        }
    }


def sidecar_json_bytes(object_key: str) -> bytes:
    """Return deterministic UTF-8 sidecar JSON for one course object.

    Args:
        object_key: Canonical course object key.

    Returns:
        Sorted, two-space-indented JSON ending with a newline.
    """
    payload = bedrock_course_material_sidecar_payload(object_key)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)
    return f"{text}\n".encode("utf-8")


def expected_sidecar_material_id(object_key: str) -> str:
    """Return the canonical ``course_material_id`` for one course object key."""
    if is_metadata_sidecar_key(object_key):
        return ""
    return course_material_id_from_object_key(object_key)


def sidecar_material_id_from_payload(payload: Any) -> str:
    """Return ``course_material_id`` from a sidecar mapping, if present.

    Args:
        payload: Parsed sidecar JSON.

    Returns:
        The string value, or empty when missing/malformed.
    """
    if not isinstance(payload, dict):
        return ""
    attributes = payload.get("metadataAttributes")
    if not isinstance(attributes, dict):
        return ""
    item = attributes.get(COURSE_MATERIAL_METADATA_KEY)
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    value = item.get("value")
    if isinstance(value, dict):
        return str(value.get("stringValue") or "").strip()
    if isinstance(value, str):
        return value.strip()
    return str(item.get("stringValue") or "").strip()


def local_sidecar_path(source_path: Path) -> Path:
    """Return the local sibling sidecar path for one course file."""
    return Path(f"{source_path}{METADATA_SUFFIX}")
