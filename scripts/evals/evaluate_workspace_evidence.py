"""Evaluate retrieval for workspace evidence — offline, deterministic, no Bedrock.

Extends the labelled retrieval evaluation to the workspace scenarios the
programme spec names: explicit and implicit lecture questions, project
coaching, ambiguous follow-ups, selected uploads and canvas/artifact evidence.
The corpus is ``scripts/evals/datasets/workspace_evidence.synthetic.jsonl``
(all rows ``synthetic: true``). The gate runs through the same production
adapter the existing evaluation uses (``scripts/evals/lib/gate.py`` →
``backend.coaching.evidence_scope``), and course retrieval runs through the
same offline lexical stand-in (``OfflineCourseSearch`` over one chunk per PDF
page), so numbers describe that stand-in only — they say nothing about
Knowledge Base quality.

New measurements on top of the existing recall/wrong-skip/empty-result eval:
precision@K, recall@K, MRR, citation correctness (the expected verbatim
evidence snippet must appear in the retrieved page text), authorization
filtering (rows that restrict retrieval to selected course materials must not
return hits outside that set), and honest evidence gaps (upload questions have
no course-corpus evidence offline). Latency is the local wall time of the
offline lexical search. No Bedrock, Knowledge Base or paid call is possible;
live Knowledge Base evaluation remains the separately approved, capped
``--live-kb`` mode of ``scripts/evals/evaluate_retrieval.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.evals.lib.gate import gate_decision  # noqa: E402
from scripts.evals.lib.output import write_json_output  # noqa: E402
from scripts.evals.lib.paths import MATERIALS_PATH  # noqa: E402

CORPUS_PATH = (
    _PROJECT_ROOT / "scripts" / "evals" / "datasets" / "workspace_evidence.synthetic.jsonl"
)

EVIDENCE_SOURCE_VOCABULARY = {"course", "student_upload", "workspace_context", "both", "none"}


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, Any]]:
    """Load and validate the labelled workspace-evidence corpus."""
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError(f"empty corpus: {path}")
    ids: set[str] = set()
    for row in rows:
        missing = {
            "id",
            "message",
            "stage",
            "history",
            "selected_sources",
            "attachments",
            "expected_decision",
            "expected_scope",
            "evidence_source",
            "authorized_materials",
            "expected_material",
            "expected_pages",
            "alt_expected",
            "evidence",
            "category",
            "certainty",
            "follow_up",
            "rationale",
            "synthetic",
        } - set(row)
        if missing:
            raise ValueError(f"{row.get('id')}: missing fields {sorted(missing)}")
        if row["id"] in ids:
            raise ValueError(f"duplicate id {row['id']}")
        ids.add(row["id"])
        if row["synthetic"] is not True:
            raise ValueError(f"{row['id']}: corpus rows must be marked synthetic")
        if row["expected_decision"] not in {"retrieve", "skip"}:
            raise ValueError(f"{row['id']}: bad expected_decision")
        if row["evidence_source"] not in EVIDENCE_SOURCE_VOCABULARY:
            raise ValueError(f"{row['id']}: bad evidence_source")
    return rows


def _load_materials() -> dict[str, dict[str, Any]]:
    items = json.loads(MATERIALS_PATH.read_text(encoding="utf-8"))
    return {item["material_id"]: item for item in items}


def _normalize(text: str) -> str:
    import re
    import unicodedata

    value = unicodedata.normalize("NFKC", text)
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", value).strip().casefold()


def measure_gate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare the production first-pass gate with each row's expected decision."""
    agreements = 0
    clear_agreements = 0
    disagreements: list[dict[str, Any]] = []
    for row in rows:
        decision = gate_decision(row)
        actual = "retrieve" if decision.retrieve else "skip"
        expected = str(row["expected_decision"])
        if actual == expected:
            agreements += 1
            if row["certainty"] == "clear":
                clear_agreements += 1
        else:
            disagreements.append({"id": row["id"], "expected": expected, "actual": actual})
    total = len(rows)
    return {
        "total": total,
        "agreement": {"hits": agreements, "rate": round(agreements / total, 4) if total else 0.0},
        "agreement_clear_only": {
            "hits": clear_agreements,
            "total": sum(1 for row in rows if row["certainty"] == "clear"),
            "rate": (
                round(clear_agreements / sum(1 for row in rows if row["certainty"] == "clear"), 4)
                if any(row["certainty"] == "clear" for row in rows)
                else 0.0
            ),
        },
        "disagreements": disagreements,
    }


def _acceptable(
    row: Mapping[str, Any],
    material_id: str,
    page: int | None,
) -> bool:
    """Whether one hit answers the row (material, and page when available)."""
    if str(row["evidence_source"]) not in {"course", "both"}:
        return False
    targets: dict[str, frozenset[int]] = {
        str(row["expected_material"]): frozenset(int(p) for p in row["expected_pages"])
    }
    for alt in row["alt_expected"]:
        targets.setdefault(str(alt["material"]), frozenset(int(p) for p in alt["pages"]))
    if material_id not in targets:
        return False
    allowed = targets[material_id]
    return page is None or page in allowed


def measure_retrieval(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run the offline lexical retriever over the course-evidence rows."""
    from scripts.evals.lib.fixtures import load_materials
    from scripts.evals.lib.offline import OfflineCourseSearch

    manifest = load_materials()
    by_id = {entry["material_id"]: entry for entry in manifest}

    def _search_for(material_ids: Sequence[str]) -> OfflineCourseSearch:
        selected = [by_id[mid] for mid in material_ids if mid in by_id]
        if not selected:
            raise ValueError(f"no authorized materials among {material_ids}")
        return OfflineCourseSearch(selected)

    all_search = OfflineCourseSearch(manifest)
    authorized_cache: dict[tuple[str, ...], OfflineCourseSearch] = {}

    scored_rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    unauthorized_rows: list[dict[str, Any]] = []
    authorized_rows: list[dict[str, Any]] = []
    miss_rows: list[str] = []
    course_rows = [
        row
        for row in rows
        if row["expected_decision"] == "retrieve"
        and str(row["evidence_source"]) in {"course", "both"}
    ]
    precision_sums: dict[str, float] = {}
    precision_totals: dict[str, int] = {}
    recall_counts: dict[str, int] = {}
    mrr_sum = 0.0
    citation_hits = 0

    for row in course_rows:
        authorized = tuple(sorted(str(mid) for mid in row["authorized_materials"]))
        search = all_search
        if authorized:
            if authorized not in authorized_cache:
                authorized_cache[authorized] = _search_for(authorized)
            search = authorized_cache[authorized]
        started = time.perf_counter()
        hits = search.search(str(row["message"]), history=row["history"])
        latency_ms = (time.perf_counter() - started) * 1_000.0
        latencies.append(latency_ms)

        allowed_set = set(authorized) or {entry["material_id"] for entry in manifest}
        within = True
        for hit in hits:
            hit_material = str(hit.material_id)
            if hit_material not in allowed_set:
                within = False
        if not within:
            unauthorized_rows.append({"id": row["id"], "returned_materials": sorted(
                {str(hit.material_id) for hit in hits}
            )})
        acceptable_ranks = [
            index + 1
            for index, hit in enumerate(hits)
            if _acceptable(row, str(hit.material_id), hit.page)
        ]
        first_hit = acceptable_ranks[0] if acceptable_ranks else 0
        mrr_sum += 1.0 / first_hit if first_hit else 0.0
        for k in (1, 2, 4, 8):
            top = hits[:k]
            relevant_top = sum(
                1 for hit in top if _acceptable(row, str(hit.material_id), hit.page)
            )
            precision_sums[k] = precision_sums.get(k, 0.0) + relevant_top / k
            precision_totals[k] = precision_totals.get(k, 0) + 1
            if relevant_top:
                recall_counts[k] = recall_counts.get(k, 0) + 1
        citation_ok = False
        if first_hit:
            hit = hits[first_hit - 1]
            snippet = _normalize(str(row["evidence"]))
            citation_ok = bool(snippet) and snippet in _normalize(hit.text)
            if citation_ok:
                citation_hits += 1
        if not acceptable_ranks:
            miss_rows.append(row["id"])
        entry = {
            "id": row["id"],
            "authorized_materials": list(authorized),
            "hits": len(hits),
            "first_acceptable_rank": first_hit,
            "citation_correct": citation_ok,
            "hits_within_authorized": within,
        }
        scored_rows.append(entry)
        if authorized:
            authorized_rows.append(entry)

    total = len(course_rows)
    precision = {
        f"precision_at_{k}": {
            "value": round(precision_sums.get(k, 0.0) / precision_totals[k], 4)
            if precision_totals.get(k)
            else 0.0,
            "rows": precision_totals.get(k, 0),
        }
        for k in (1, 2, 4, 8)
    }
    recall = {
        f"recall_at_{k}": {
            "hits": recall_counts.get(k, 0),
            "total": total,
            "rate": round(recall_counts.get(k, 0) / total, 4) if total else 0.0,
        }
        for k in (1, 2, 4, 8)
    }

    def _pct(values: list[float], percent: int) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        return round(ordered[(percent * len(ordered) - 1) // 100], 3)

    return {
        "corpus": CORPUS_PATH.name,
        "rows_measured": total,
        "retriever": "scripts.evals.lib.offline.OfflineCourseSearch (lexical stand-in, one chunk per PDF page)",
        **precision,
        **recall,
        "mrr": {"value": round(mrr_sum / total, 4) if total else 0.0, "rows": total},
        "citation_correct_rate": {
            "hits": citation_hits,
            "total": total,
            "rate": round(citation_hits / total, 4) if total else 0.0,
        },
        "unauthorized_hit_rows": unauthorized_rows,
        "authorized_rows": authorized_rows,
        "filter_correct_rate": {
            "hits": total - len(unauthorized_rows),
            "total": total,
            "rate": round((total - len(unauthorized_rows)) / total, 4) if total else 0.0,
        },
        "latency_ms": {
            "note": "local wall time of the offline lexical search on this host",
            "p50": _pct(latencies, 50),
            "p95": _pct(latencies, 95),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "miss_rows": miss_rows,
    }


def measure_upload_gaps(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Record the honest offline gaps for upload- and workspace-sourced rows."""
    from scripts.evals.lib.fixtures import load_materials
    from scripts.evals.lib.offline import OfflineCourseSearch

    manifest = load_materials()
    all_search = OfflineCourseSearch(manifest)
    upload_rows = [
        row
        for row in rows
        if str(row["evidence_source"]) in {"student_upload", "workspace_context", "none"}
    ]
    wrongly_credited: list[str] = []
    for row in upload_rows:
        if str(row["evidence_source"]) != "student_upload":
            continue
        hits = all_search.search(str(row["message"]), history=row["history"])
        if any(_acceptable(row, str(hit.material_id), hit.page) for hit in hits):
            wrongly_credited.append(row["id"])
    return {
        "student_upload_expected_gap_rows": sum(
            1 for row in rows if str(row["evidence_source"]) == "student_upload"
        ),
        "workspace_context_rows": sum(
            1 for row in rows if str(row["evidence_source"]) == "workspace_context"
        ),
        "course_rows": sum(1 for row in rows if str(row["evidence_source"]) in {"course", "both"}),
        "course_miss_rows": 0,
        "student_upload_rows_wrongly_credited_by_course_search": wrongly_credited,
        "note": (
            "Upload and canvas/artifact evidence is resolved server-side from "
            "the student's own files and workspace selections; the offline "
            "course corpus cannot contain it, so the honest offline outcome for "
            "upload rows is a gap handled by the upload retrieval policy, not a "
            "course hit."
        ),
    }


def build_report() -> dict[str, Any]:
    """Build the full offline workspace-evidence evaluation report."""
    rows = load_corpus()
    retrieval = measure_retrieval(rows)
    gaps = measure_upload_gaps(rows)
    gaps["course_miss_rows"] = len(retrieval["miss_rows"])
    return {
        "measurement_kind": "offline-simulation",
        "ticket": 42,
        "scope": (
            "Extended labelled retrieval evaluation over workspace-evidence "
            "scenarios (explicit/implicit lecture questions, project coaching, "
            "ambiguous follow-ups, selected uploads, canvas/artifact evidence) "
            "using the production gate adapter and the offline lexical course "
            "retriever. No Bedrock, Knowledge Base or paid call."
        ),
        "gate": measure_gate(rows),
        "retrieval": retrieval,
        "evidence_gaps": gaps,
        "limitations": [
            "Course search is the offline lexical stand-in; these numbers say nothing about Knowledge Base quality.",
            "The 295-message gate corpus and its numbers are unchanged; this corpus extends coverage, it does not replace the existing gate.",
            "Rows are synthetic and hand-labelled; wording is cleaner than real student traffic.",
            "Live Knowledge Base evaluation is the separately approved, capped --live-kb mode of scripts/evals/evaluate_retrieval.py and was not executed here.",
        ],
        "recommendation": {
            "change_retrieval_defaults": False,
            "summary": (
                "No chunking, reranking, rewriting, hybrid-search, router or "
                "vector-store change is adopted: advanced methods stay "
                "measurement-gated and require an observed gap with educational "
                "demand, privacy and cost assessment. The recorded gaps and "
                "filter results define what a future variant must beat."
            ),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument(
        "--i-approve-live-aws",
        action="store_true",
        help="Refused. This script never calls AWS.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.i_approve_live_aws:
        print("this entry point never calls AWS", file=sys.stderr)
        return 2
    from scripts.evals.lib.offline import block_network

    block_network()
    report = build_report()
    if args.json_output is not None:
        write_json_output(args.json_output, report)
    retrieval = report["retrieval"]
    gate = report["gate"]
    print(
        f"offline workspace-evidence eval: gate agreement "
        f"{gate['agreement']['hits']}/{gate['total']}, recall@4 "
        f"{retrieval['recall_at_4']['hits']}/{retrieval['recall_at_4']['total']}, "
        f"MRR {retrieval['mrr']['value']}, unauthorized hits "
        f"{len(retrieval['unauthorized_hit_rows'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
