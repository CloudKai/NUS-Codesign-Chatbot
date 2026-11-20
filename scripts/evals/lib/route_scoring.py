"""Score routing candidates on the fixed synthetic splits, with no model loaded here.

``evaluate`` takes any ``predict`` callable, so the report logic runs with a stub.
Fitting and loading a model stays in ``compare_turn_routes``.
"""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import perf_counter
from typing import Any, Callable

from scripts.evals.lib.fixtures import (
    load_followups,
    load_materials,
    load_messages,
    load_questions,
    read_training,
)
from scripts.evals.lib.gate import gate_decision
from scripts.evals.lib.metrics import interval
from scripts.evals.lib.paths import DATASET_DIR, MESSAGES_PATH, QUESTIONS_PATH
from scripts.evals.lib.turn_state import ROUTE_QUESTIONS, normalized, route_state, scope_name

Row = dict[str, Any]


Predict = Callable[[str], dict[str, dict[str, float]]]


def scenarios(name: str) -> list[Row]:
    """Load one authored split and translate synthetic file names to gate inputs."""
    path = DATASET_DIR / name
    rows = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        row = json.loads(line)

        def source(key: str) -> list[Row]:
            value = row.get(key)
            return [{"title": value, "filename": value}] if value else []

        rows.append(
            dict(
                row,
                id=f"{path.stem}-{i}",
                stage="problem_identification",
                expected_scope=row["scope"],
                selected_sources=source("file"),
                attachments=source("attachment"),
            )
        )
    return rows


def state(row: Row) -> str:
    """Serialize only fields available before routing."""
    return route_state(row["message"], row["history"], [], row["selected_sources"])


def training() -> list[tuple[str, dict[str, str]]]:
    """Return identical ordered labelled states for both candidate fits."""
    rows = scenarios("routing_matched_train.jsonl")
    examples = [(state(r), {"scope": r["scope"], "mode": r["mode"]}) for r in rows]
    for scope, mode, file, message in read_training("laya_routing_training.synthetic.tsv", 4):
        examples.append(
            (
                route_state(message, [], [], [] if file == "-" else [{"title": file}]),
                {"scope": scope, "mode": mode},
            )
        )
    return examples


def laya_predictor(model: Any) -> Predict:
    """Read both probability vectors for calibration and reporting."""

    def predict(text: str) -> dict[str, dict[str, float]]:
        answers = model.decide(text)["answers"]
        return {key: answers[key]["probs"] for key in ROUTE_QUESTIONS}

    return predict


def inputs() -> dict[str, list[Row]]:
    """Load all evaluation splits and reject cross-split example or family leaks."""
    materials = load_materials()
    ids = [r["id"] for r in load_questions(QUESTIONS_PATH, materials)]
    historical = load_messages(MESSAGES_PATH, materials, ids)
    historical += load_followups(materials=materials, question_ids=ids)
    splits = {s: scenarios(f"routing_{s}.synthetic.jsonl") for s in ("calibration", "fresh")}
    splits["historical"] = historical
    matched = scenarios("routing_matched_train.jsonl")
    seen = {normalized(r["message"]) for r in matched}
    seen.update(
        normalized(r[3]) for r in read_training("laya_routing_training.synthetic.tsv", 4)
    )
    groups = {r["group"] for r in matched}
    for rows in splits.values():
        messages = {normalized(r["message"]) for r in rows}
        families = {r["group"] for r in rows if "group" in r}
        if groups & families or seen & messages:
            raise ValueError("Overlapping experiment splits")
        groups.update(families)
        seen.update(messages)
    return splits


def observe(row: Row, predict: Predict) -> Row:
    """Record raw model decisions even for turns reserved for gate-only serving."""
    gate = gate_decision(row)
    selected = bool(row["selected_sources"])
    prior = any(t["role"] == "user" for t in row["history"])
    locked = (
        row.get("explicit_mode")
        or ("workflow" if gate.scope_cleared else None)
        or ("attachment" if gate.attachment_only or row["attachments"] else None)
    )
    start = perf_counter()
    probs = predict(state(row))
    elapsed = 1000 * (perf_counter() - start)
    for key, schema in ROUTE_QUESTIONS.items():
        values = probs[key]
        if (
            set(values) != set(schema["criteria"])
            or not math.isclose(sum(values.values()), 1, abs_tol=1e-4)
            or any(not 0 <= v <= 1 for v in values.values())
        ):
            raise ValueError(f"Invalid probabilities for {key}")
    return dict(
        id=row["id"],
        group=row.get("group"),
        selected_file=selected,
        follow_up=prior,
        mixed_source=row["expected_scope"] == "both",
        multilingual=row.get("multilingual", row["id"] in {"gm090", "gm091", "gm092"}),
        gold_scope=row["expected_scope"],
        gold_mode=row.get("mode"),
        protected=locked,
        expected_workflow=row.get("expected_workflow", False),
        gate=scope_name(gate.course, gate.student),
        gate_mode="lecture_help" if gate.expected_mode == "qa" else "project_coaching",
        probabilities=probs,
        raw={k: max(p, key=p.get) for k, p in probs.items()},
        latency_ms=elapsed,
    )


def apply(row: Row, head: str, cutoff: float) -> tuple[str, str | None]:
    """Apply explicit scope, observable eligibility, availability and calibrated confidence."""
    raw = row["raw"][head]
    reason = row["protected"]
    if not reason and not (row["selected_file"] or row["follow_up"]):
        reason = "opening_without_file"
    if (
        not reason
        and head == "scope"
        and raw in {"both", "student_upload"}
        and not row["selected_file"]
    ):
        reason = "unavailable_source"
    if not reason and row["probabilities"][head][raw] < cutoff:
        reason = "below_cutoff"
    return (row["gate" if head == "scope" else "gate_mode"] if reason else raw), reason


def summary(rows: list[Row]) -> Row:
    """Summarize both policies, with retrieval error denominators fixed by gold scope."""
    report = {}
    for name in ("all", "selected_file", "follow_up", "mixed_source", "multilingual"):
        group = [r for r in rows if name == "all" or r[name]]
        report[name] = {}
        for method, mode in (("gate", "gate_mode"), ("effective", "effective_mode")):
            skip = [r for r in group if r["gold_scope"] == "none"]
            need = [r for r in group if r["gold_scope"] != "none"]
            labelled = [r for r in group if r["gold_mode"]]
            report[name][method] = dict(
                exact=interval(sum(r[method] == r["gold_scope"] for r in group), len(group)),
                unnecessary=interval(sum(r[method] != "none" for r in skip), len(skip)),
                missed=interval(sum(r[method] == "none" for r in need), len(need)),
                mode=interval(sum(r[mode] == r["gold_mode"] for r in labelled), len(labelled)),
            )
    return report


def latency(predict: Predict, rows: list[Row], cuts: dict[str, float]) -> Row:
    """Time eight waves at each load, including the rule path when the CPU slot is busy."""
    lock = Lock()
    result = {}
    for workers in (1, 8):
        barrier = Barrier(workers)

        def request(row: Row) -> Row:
            barrier.wait()
            start = perf_counter()
            if lock.acquire(blocking=False):
                try:
                    decision = observe(row, predict)
                    effective, reason = apply(decision, "scope", cuts["scope"])
                finally:
                    lock.release()
            else:
                gate = gate_decision(row)
                effective, reason = scope_name(gate.course, gate.student), "busy"
            return dict(
                id=row["id"], effective=effective, reason=reason, ms=1000 * (perf_counter() - start)
            )

        samples = []
        with ThreadPoolExecutor(workers) as pool:
            for i in range(8):
                samples.extend(pool.map(request, [rows[i % len(rows)]] * workers))
        times = sorted(r["ms"] for r in samples)
        result[str(workers)] = {
            "p50_ms": times[math.ceil(len(times) * 0.5) - 1],
            "p95_ms": times[math.ceil(len(times) * 0.95) - 1],
            "busy": sum(r["reason"] == "busy" for r in samples),
            "samples": samples,
        }
    return result


def evaluate(
    predict: Predict, splits: dict[str, list[Row]], fixed: dict[str, float] | None = None
) -> Row:
    """Freeze cutoffs on calibration, then score fresh and historical turns."""
    cuts = dict(fixed or {})
    report: Row = {"cutoffs": cuts, "rows": {}, "metrics": {}}
    for split, inputs_ in splits.items():
        print(f"Scoring {len(inputs_)} {split} turns.", flush=True)
        rows = [observe(r, predict) for r in inputs_]
        if split == "calibration" and not fixed:
            for head in ("scope", "mode"):
                cuts[head] = max(
                    (0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01),
                    key=lambda c: (sum(apply(r, head, c)[0] == r["gold_" + head] for r in rows), c),
                )
        for r in rows:
            r["effective"], r["fallback"] = apply(r, "scope", cuts["scope"])
            r["effective_mode"], r["mode_fallback"] = apply(r, "mode", cuts["mode"])
        report["rows"][split] = rows
        report["metrics"][split] = summary(rows)
    assess(report)
    report["latency"] = latency(
        predict,
        [
            r
            for r in splits["fresh"]
            if r["file"] and not r["explicit_mode"] and not gate_decision(r).scope_cleared
        ],
        cuts,
    )
    return report


def assess(report: Row) -> None:
    """Record the predeclared fresh accuracy, error and scope-preservation gates."""
    metrics = report["metrics"]["fresh"]["all"]
    protected = [
        r
        for split in report["rows"].values()
        for r in split
        if r["protected"] or r["expected_workflow"]
    ]
    passed = sum(
        r["effective"] == r["gate"] and r["effective_mode"] == r["gate_mode"] for r in protected
    )
    report["protected_checks"] = interval(passed, len(protected))
    m = metrics["effective"]
    report["qualifies"] = bool(
        protected
        and passed == len(protected)
        and m["exact"]["numerator"] > metrics["gate"]["exact"]["numerator"]
        and m["unnecessary"]["rate"] < 0.10
        and m["missed"]["rate"] < 0.25
    )
    report["protected_by_reason"] = {
        reason: sum((r["protected"] or "workflow_paraphrase") == reason for r in protected)
        for reason in sorted({r["protected"] or "workflow_paraphrase" for r in protected})
    }
