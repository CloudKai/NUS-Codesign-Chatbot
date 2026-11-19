"""Validate the retrieval question set under ``scripts/evals/datasets``.

Offline only. Reads the question file, the materials manifest and the lecture
PDFs in the repo. No AWS, Knowledge Base or paid calls.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import pytest

from backend.retrieval import course_material_id_from_object_key
from backend.sources.library import virtual_course_source_id

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "scripts" / "evals" / "datasets"
QUESTIONS_PATH = DATA_DIR / "retrieval_questions.jsonl"
MATERIALS_PATH = DATA_DIR / "course_materials.json"

KINDS = {"definition", "list", "procedure", "example", "detail", "logistics"}
ROW_KEYS = {
    "id",
    "question",
    "expected_material",
    "expected_pages",
    "alt_expected",
    "evidence",
    "kind",
    "note",
}


def _normalize(text: str) -> str:
    """Fold ligatures and quote styles, then collapse whitespace and case."""
    value = unicodedata.normalize("NFKC", text)
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", value).strip().casefold()


def _rows() -> list[dict]:
    lines = QUESTIONS_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _materials() -> dict[str, dict]:
    items = json.loads(MATERIALS_PATH.read_text(encoding="utf-8"))
    return {item["material_id"]: item for item in items}


def test_question_file_schema_and_count() -> None:
    rows = _rows()
    materials = _materials()
    assert 60 <= len(rows) <= 100
    assert len({row["id"] for row in rows}) == len(rows)
    assert len({row["question"].casefold() for row in rows}) == len(rows)
    for row in rows:
        assert set(row) == ROW_KEYS, row["id"]
        assert row["kind"] in KINDS, row["id"]
        assert row["question"].strip() and row["evidence"].strip(), row["id"]
        locations = [(row["expected_material"], row["expected_pages"])] + [
            (alt["material"], alt["pages"]) for alt in row["alt_expected"]
        ]
        for material_id, pages in locations:
            assert material_id in materials, (row["id"], material_id)
            assert pages and pages == sorted(set(pages)), (row["id"], pages)
            total = materials[material_id]["pdf_pages"]
            assert all(isinstance(p, int) and 1 <= p <= total for p in pages), (
                row["id"],
                material_id,
                pages,
            )


def test_manifest_matches_repo_id_and_source_functions() -> None:
    for item in _materials().values():
        key = item["object_key"]
        assert item["material_id"] == course_material_id_from_object_key(key)
        assert item["source_id"] == virtual_course_source_id(key)
        assert (ROOT / item["local_path"]).is_file()
        assert item["local_path"].endswith(key.removeprefix("course/"))


def test_evidence_text_is_on_the_tagged_pages() -> None:
    """Every tagged location must contain its verbatim evidence snippet."""
    fitz = pytest.importorskip("fitz")
    materials = _materials()
    cache: dict[str, list[str]] = {}

    def page_texts(material_id: str) -> list[str]:
        if material_id not in cache:
            path = ROOT / materials[material_id]["local_path"]
            with fitz.open(path) as doc:
                cache[material_id] = [_normalize(page.get_text()) for page in doc]
        return cache[material_id]

    problems: list[str] = []
    for row in _rows():
        checks = [
            (row["expected_material"], row["expected_pages"], row["evidence"])
        ] + [
            (alt["material"], alt["pages"], alt["evidence"])
            for alt in row["alt_expected"]
        ]
        for material_id, pages, evidence in checks:
            texts = page_texts(material_id)
            needle = _normalize(evidence)
            if not any(needle in texts[page - 1] for page in pages):
                problems.append(f"{row['id']} {material_id} {pages}: {evidence!r}")
    assert not problems, "\n".join(problems)
