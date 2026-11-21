"""Real lecture PDFs through the real local retriever: recall floor per question.

Builds ``OfflineCourseSearch`` (``LocalChunkRetriever``, one chunk per PDF page)
over ``lecture_notes/`` and scores every row of
``scripts/evals/datasets/retrieval_questions.jsonl`` against the expected
material and pages, including ``alt_expected``. No model, no network, no AWS.

The floors below are the values measured on the real PDFs. A change that lowers
recall fails the test and the message lists the questions that now miss. A
change that raises recall passes; raise the floor in the same commit.
"""

from __future__ import annotations

import pytest

from scripts.evals.evaluate_retrieval import (
    QuestionOutcome,
    page_recall_at_k,
    recall_at_k,
    score_question,
)
from scripts.evals.lib.fixtures import load_materials, load_questions
from scripts.evals.lib.offline import OfflineCourseSearch, extract_pdf_pages
from scripts.evals.lib.paths import PROJECT_ROOT

# Measured with the offline eval over the 10 lecture PDFs (94 questions).
MATERIAL_RECALL_FLOOR = 91
PAGE_RECALL_FLOOR = 79
QUESTION_COUNT = 94
# Questions whose expected material is not in the top 4 today. Image-only
# slides, generic wording and lexical-only ranking explain them.
KNOWN_MATERIAL_MISSES = frozenset({"rq003", "rq031", "rq073"})


@pytest.fixture(scope="module")
def materials() -> list[dict]:
    return load_materials()


@pytest.fixture(scope="module")
def questions(materials: list[dict]) -> list[dict]:
    return load_questions(materials=materials)


@pytest.fixture(scope="module")
def outcomes(materials: list[dict], questions: list[dict]) -> list[QuestionOutcome]:
    search = OfflineCourseSearch(materials)
    return [
        score_question(
            row["id"],
            search.search(row["question"]),
            expected_material=row["expected_material"],
            expected_pages=row["expected_pages"],
            alt_expected=row["alt_expected"],
            page_aware=True,
        )
        for row in questions
    ]


def _describe(outcome: QuestionOutcome, questions: list[dict]) -> str:
    row = next(q for q in questions if q["id"] == outcome.question_id)
    return (
        f"{outcome.question_id} [{row['kind']}] {row['question']!r} "
        f"expected {row['expected_material']} p{row['expected_pages']}; "
        f"top4 {list(outcome.top_materials)}"
    )


def test_dataset_covers_every_manifest_pdf_and_94_questions(
    materials: list[dict], questions: list[dict]
) -> None:
    assert len(questions) == QUESTION_COUNT
    assert len(materials) == 10
    for entry in materials:
        assert (PROJECT_ROOT / entry["local_path"]).is_file()
    assert {q["expected_material"] for q in questions} <= {m["material_id"] for m in materials}


def test_every_question_returns_at_least_one_result(outcomes: list[QuestionOutcome]) -> None:
    empty = [o.question_id for o in outcomes if o.result_count == 0]
    assert empty == []


def test_material_recall_at_4_does_not_fall_below_measured_floor(
    outcomes: list[QuestionOutcome], questions: list[dict]
) -> None:
    record = recall_at_k(outcomes)
    misses = [_describe(o, questions) for o in outcomes if not o.material_hit]
    print(f"material recall@4: {record['numerator']}/{record['denominator']}")
    print("\n".join(f"MATERIAL MISS {line}" for line in misses))
    assert record["denominator"] == QUESTION_COUNT
    assert record["numerator"] >= MATERIAL_RECALL_FLOOR, "\n".join(misses)


def test_page_recall_at_4_does_not_fall_below_measured_floor(
    outcomes: list[QuestionOutcome], questions: list[dict]
) -> None:
    record = page_recall_at_k(outcomes)
    misses = [_describe(o, questions) for o in outcomes if not o.page_hit]
    print(f"page recall@4: {record['numerator']}/{record['denominator']}")
    print("\n".join(f"PAGE MISS {line}" for line in misses))
    assert record["denominator"] == QUESTION_COUNT
    assert record["numerator"] >= PAGE_RECALL_FLOOR, "\n".join(misses)


def test_questions_that_hit_today_keep_hitting(
    outcomes: list[QuestionOutcome], questions: list[dict]
) -> None:
    """Material misses outside the known set are new regressions."""
    new_misses = [
        _describe(o, questions)
        for o in outcomes
        if not o.material_hit and o.question_id not in KNOWN_MATERIAL_MISSES
    ]
    assert new_misses == []


def test_manifest_pages_without_text_match_the_pdfs(materials: list[dict]) -> None:
    """Image-only pages cannot be retrieved by the lexical retriever or the KB text index."""
    counts = {}
    for entry in materials:
        pages = extract_pdf_pages(PROJECT_ROOT / entry["local_path"])
        counts[entry["material_id"]] = sum(1 for text in pages if not text.strip())
        assert counts[entry["material_id"]] == entry["pages_without_text"], entry["filename"]
    # Week 1 is mostly image-only slides: the known OCR gap.
    assert counts["lecture_week_1_introduction_to_innovation_v3"] == 27


def test_personas_poster_pages_that_share_a_banner_are_all_retrievable(
    materials: list[dict],
) -> None:
    """Regression: step-8 page 4 of Reading 2 opens with the same banner as page 1.

    Duplicate suppression used to compare only the first 400 characters, so page 4
    was dropped even though it ranked second. Every ranked page must reach the
    formatted result.
    """
    personas = [m for m in materials if m["material_id"] == "reading_reading_2_engaging_personas"]
    hits = OfflineCourseSearch(personas).search(
        "How can personas be shared with the rest of the organization?"
    )
    assert 4 in {hit.page for hit in hits}
