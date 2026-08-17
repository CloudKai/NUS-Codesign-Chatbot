"""Canonical filtering of notebook progress fields that carry meaning.

Slim Fast Chat assessments leave learning-progress strings empty. Merging
those empty values into notebook metadata would blank previously stored
progress. Callers omit empty fields from patches and persist summaries so
existing non-empty values survive.

``EducationalAssessment`` declares the four notebook progress fields as
strings (``learning_summary``, ``working_conclusion``,
``understanding_change``, and ``critical_understanding_level``, persisted as
``critical_understanding``). Whitespace-only strings are empty. Boolean
``False`` and numeric ``0`` are treated as meaningful so a historical
non-string value is not dropped by accident.
"""

from __future__ import annotations

from typing import Any, Mapping

PROGRESS_METADATA_KEYS: tuple[str, str, str, str] = (
    "learning_summary",
    "working_conclusion",
    "understanding_change",
    "critical_understanding",
)


def progress_value_is_meaningful(value: object) -> bool:
    """Return whether *value* carries information for a progress field.

    Args:
        value: Candidate progress-field value from an assessment or patch.

    Returns:
        ``True`` when the value should overwrite stored notebook progress.
        ``None`` and whitespace-only strings are empty. ``False`` and ``0``
        are meaningful. Unknown non-null types are preserved.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.split())
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return True


def normalize_progress_value(value: object) -> object:
    """Return a persistable progress value.

    Args:
        value: A value already known to be meaningful.

    Returns:
        Whitespace-collapsed text for strings; other types unchanged.
    """
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return value


def meaningful_progress_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the four progress keys whose values carry meaning.

    Args:
        fields: Mapping that may include progress keys and unrelated keys.
            Unrelated keys are ignored. *fields* is not mutated.

    Returns:
        A new dict of meaningful progress fields ready to merge into notebook
        metadata. Empty when every progress value is blank.

    Raises:
        None. Invalid types are preserved rather than coerced away.
    """
    meaningful: dict[str, Any] = {}
    for key in PROGRESS_METADATA_KEYS:
        if key not in fields:
            continue
        value = fields[key]
        if not progress_value_is_meaningful(value):
            continue
        meaningful[key] = normalize_progress_value(value)
    return meaningful


def overlay_progress_fields(
    existing: Mapping[str, Any],
    *incoming: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep stored progress, then overlay later mappings that carry meaning.

    Args:
        existing: Current notebook progress (blob, metadata, or journey).
        incoming: Later patches or assessment mappings. Empty values in these
            mappings are ignored so they cannot blank *existing*.

    Returns:
        Meaningful progress fields with later non-empty values winning.
    """
    merged = meaningful_progress_fields(existing)
    for mapping in incoming:
        merged.update(meaningful_progress_fields(mapping))
    return merged
