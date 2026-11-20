"""Load and validate the fixed eval datasets (course manifest, questions, gate messages).

Offline: reads files under ``scripts/evals/datasets``, plus ``eval_course_titles``,
which imports one production helper lazily. No network, no model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from scripts.evals.lib.paths import (
    FOLLOWUPS_PATH,
    MATERIALS_PATH,
    MESSAGES_PATH,
    QUESTIONS_PATH,
)

QUESTION_COUNT_RANGE = (60, 100)


MIN_MESSAGE_COUNT = 200


QUESTION_KEYS = frozenset(
    {
        "id",
        "question",
        "expected_material",
        "expected_pages",
        "alt_expected",
        "evidence",
        "kind",
        "note",
    }
)


QUESTION_KINDS = frozenset(
    {"definition", "list", "procedure", "example", "detail", "logistics"}
)


MESSAGE_KEYS = frozenset(
    {
        "id",
        "message",
        "stage",
        "selected_sources",
        "attachments",
        "history",
        "expected_decision",
        "expected_scope",
        "category",
        "certainty",
        "follow_up",
        "question_id",
        "expected_material",
        "rationale",
        "synthetic",
    }
)


DECISIONS = frozenset({"retrieve", "skip"})


SCOPES = frozenset({"course", "student_upload", "both", "none"})


CERTAINTIES = frozenset({"clear", "borderline"})


MESSAGE_CATEGORIES = frozenset(
    {
        "course_content",
        "course_logistics",
        "named_material",
        "informal_or_multilingual",
        "mixed_project_and_course",
        "upload_question",
        "attachment_question",
        "upload_and_course",
        "course_with_unrelated_upload",
        "follow_up",
        "greeting_thanks_chitchat",
        "procedural_ui",
        "stage_navigation",
        "stage_meta_guidance",
        "project_reasoning",
        "project_mentions_course",
        "ambiguous_generic",
        "out_of_scope",
        "not_in_course_material",
    }
)


class DatasetError(ValueError):
    """Raised when a data file does not match its documented format."""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise DatasetError(f"{path.name}:{line_number}: blank line")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{path.name}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise DatasetError(f"{path.name}:{line_number}: not an object")
            rows.append(value)
    return rows


def load_materials(path: Path = MATERIALS_PATH) -> list[dict[str, Any]]:
    """Load the course-material manifest."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise DatasetError("course_materials.json must be a non-empty list")
    required = {"material_id", "object_key", "local_path", "filename", "group", "source_id", "pdf_pages"}
    ids: set[str] = set()
    for entry in manifest:
        missing = required - set(entry)
        if missing:
            raise DatasetError(f"manifest entry missing {sorted(missing)}")
        if entry["material_id"] in ids:
            raise DatasetError(f"duplicate material_id {entry['material_id']}")
        ids.add(entry["material_id"])
    return manifest


def validate_questions(
    rows: Sequence[Mapping[str, Any]],
    materials: Sequence[Mapping[str, Any]],
    *,
    count_range: tuple[int, int] = QUESTION_COUNT_RANGE,
) -> None:
    """Raise :class:`DatasetError` if the question rows break the format."""
    low, high = count_range
    if not low <= len(rows) <= high:
        raise DatasetError(f"question count {len(rows)} outside {low}..{high}")
    pages_by_material = {m["material_id"]: int(m["pdf_pages"]) for m in materials}
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id"))
        if set(row) != QUESTION_KEYS:
            raise DatasetError(f"{row_id}: keys {sorted(set(row) ^ QUESTION_KEYS)} differ")
        if not re.fullmatch(r"rq\d{3}", row_id) or row_id in seen:
            raise DatasetError(f"{row_id}: bad or duplicate id")
        seen.add(row_id)
        if not str(row["question"]).strip() or not str(row["evidence"]).strip():
            raise DatasetError(f"{row_id}: empty question or evidence")
        if row["kind"] not in QUESTION_KINDS:
            raise DatasetError(f"{row_id}: unknown kind {row['kind']!r}")
        targets = [(row["expected_material"], row["expected_pages"])]
        if not isinstance(row["alt_expected"], list):
            raise DatasetError(f"{row_id}: alt_expected must be a list")
        for alt in row["alt_expected"]:
            if set(alt) != {"material", "pages", "evidence"}:
                raise DatasetError(f"{row_id}: bad alt_expected entry")
            targets.append((alt["material"], alt["pages"]))
        for material, pages in targets:
            if material not in pages_by_material:
                raise DatasetError(f"{row_id}: unknown material {material}")
            ok = (
                isinstance(pages, list)
                and pages
                and pages == sorted(set(pages))
                and all(isinstance(p, int) and 1 <= p <= pages_by_material[material] for p in pages)
            )
            if not ok:
                raise DatasetError(f"{row_id}: bad pages {pages} for {material}")


def validate_messages(
    rows: Sequence[Mapping[str, Any]],
    materials: Sequence[Mapping[str, Any]],
    question_ids: Iterable[str],
    *,
    min_count: int = MIN_MESSAGE_COUNT,
    require_synthetic: bool = True,
) -> None:
    """Raise :class:`DatasetError` if the message rows break the format."""
    from backend.domain import VALID_STAGE_IDS

    if len(rows) < min_count:
        raise DatasetError(f"message count {len(rows)} below {min_count}")
    material_ids = {m["material_id"] for m in materials}
    known_questions = set(question_ids)
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id"))
        if set(row) != MESSAGE_KEYS:
            raise DatasetError(f"{row_id}: keys {sorted(set(row) ^ MESSAGE_KEYS)} differ")
        if not re.fullmatch(r"gm\d{3}", row_id) or row_id in seen:
            raise DatasetError(f"{row_id}: bad or duplicate id")
        seen.add(row_id)
        if row["synthetic"] is not True and require_synthetic:
            raise DatasetError(f"{row_id}: synthetic marker is not true")
        if not str(row["message"]).strip():
            raise DatasetError(f"{row_id}: empty message")
        if row["stage"] not in VALID_STAGE_IDS:
            raise DatasetError(f"{row_id}: unknown stage {row['stage']!r}")
        if row["expected_decision"] not in DECISIONS:
            raise DatasetError(f"{row_id}: bad expected_decision")
        if row["expected_scope"] not in SCOPES:
            raise DatasetError(f"{row_id}: bad expected_scope")
        if (row["expected_scope"] == "none") != (row["expected_decision"] == "skip"):
            raise DatasetError(f"{row_id}: scope 'none' must match decision 'skip'")
        if row["category"] not in MESSAGE_CATEGORIES:
            raise DatasetError(f"{row_id}: unknown category {row['category']!r}")
        if row["certainty"] not in CERTAINTIES:
            raise DatasetError(f"{row_id}: bad certainty")
        for field in ("selected_sources", "attachments"):
            for entry in row[field]:
                if set(entry) != {"title", "filename"}:
                    raise DatasetError(f"{row_id}: bad {field} entry")
        for turn in row["history"]:
            if set(turn) != {"role", "text"} or turn["role"] not in {"user", "assistant"}:
                raise DatasetError(f"{row_id}: bad history entry")
        if row["question_id"] is not None and row["question_id"] not in known_questions:
            raise DatasetError(f"{row_id}: unknown question_id {row['question_id']}")
        if row["expected_material"] is not None and row["expected_material"] not in material_ids:
            raise DatasetError(f"{row_id}: unknown expected_material")


def load_questions(
    path: Path = QUESTIONS_PATH, materials: Sequence[Mapping[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Load and validate the retrieval questions."""
    manifest = list(materials) if materials is not None else load_materials()
    rows = _read_jsonl(path)
    validate_questions(rows, manifest)
    return rows


def load_messages(
    path: Path = MESSAGES_PATH,
    materials: Sequence[Mapping[str, Any]] | None = None,
    question_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Load and validate the gate messages."""
    manifest = list(materials) if materials is not None else load_materials()
    ids = question_ids if question_ids is not None else [q["id"] for q in load_questions(materials=manifest)]
    rows = _read_jsonl(path)
    validate_messages(rows, manifest, ids)
    return rows


def load_followups(
    path: Path = FOLLOWUPS_PATH,
    materials: Sequence[Mapping[str, Any]] | None = None,
    question_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Load the synthetic follow-up cases (same row format as the gate messages).

    The file is kept apart from the 295 gate messages so their numbers stay
    comparable. Every row must be a follow-up with prior history, and ids must
    not collide with the gate messages.
    """
    manifest = list(materials) if materials is not None else load_materials()
    ids = list(question_ids) if question_ids is not None else [q["id"] for q in load_questions(materials=manifest)]
    rows = _read_jsonl(path)
    validate_messages(rows, manifest, ids, min_count=1)
    gate_ids = {row["id"] for row in _read_jsonl(MESSAGES_PATH)}
    for row in rows:
        if row["id"] in gate_ids:
            raise DatasetError(f"{row['id']}: id also used in the gate messages")
        if row["category"] != "follow_up" or row["follow_up"] is not True or not row["history"]:
            raise DatasetError(f"{row['id']}: not a follow-up with history")
        if row["expected_decision"] == "retrieve" and (
            row["question_id"] is None or row["expected_material"] is None
        ):
            raise DatasetError(f"{row['id']}: retrieve follow-up needs question_id and expected_material")
    return rows


def eval_course_titles(materials: Sequence[Mapping[str, Any]]) -> list[str]:
    """Course titles for the SOURCE CHECK rule, built from the eval manifest.

    Each manifest entry is projected into the locked course source shape
    production lists for a notebook, then passed to the production helper
    ``source_check_course_titles``, so the eval and production share the
    title rules (order, clipping, de-duplication).
    """
    from backend.coaching.execution import source_check_course_titles

    return source_check_course_titles(
        [
            {
                "title": str(entry["filename"]),
                "metadata": {
                    "origin": "lecture_notes_folder",
                    "locked_source": True,
                    "course_material_group": str(entry.get("group") or ""),
                },
            }
            for entry in materials
        ]
    )

