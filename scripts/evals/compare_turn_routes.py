"""Fit and evaluate CPU routing candidates on fixed synthetic splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
from importlib.metadata import version
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from time import perf_counter
from typing import Any, Callable

from scripts.evals import evaluate_laya_turn_decisions as base
from scripts.evals import evaluate_retrieval as retrieval

Row = dict[str, Any]
Predict = Callable[[str], dict[str, dict[str, float]]]


def scenarios(name: str) -> list[Row]:
    """Load one authored split and translate synthetic file names to gate inputs."""
    path = base.DATA / name
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
    return base.route_state(row["message"], row["history"], [], row["selected_sources"])


def training() -> list[tuple[str, dict[str, str]]]:
    """Return identical ordered labelled states for both candidate fits."""
    rows = scenarios("routing_matched_train.jsonl")
    examples = [(state(r), {"scope": r["scope"], "mode": r["mode"]}) for r in rows]
    for scope, mode, file, message in base.read_training("laya_routing_training.synthetic.tsv", 4):
        examples.append(
            (
                base.route_state(message, [], [], [] if file == "-" else [{"title": file}]),
                {"scope": scope, "mode": mode},
            )
        )
    return examples


def fit_laya(checkpoint: Path, output: Path) -> Any:
    """Fit, save and reload both Laya choices on CPU."""
    from laya import Learner

    reader = base.load_vega_reader(checkpoint)
    bundle = output / "routing.zip"
    model = Learner(base.ROUTE_QUESTIONS, examples=training(), reader=reader, auto=False, cache=0)
    model.save_bundle(bundle)
    return Learner(bundle=bundle, reader=reader, auto=False, cache=0)


def laya_predictor(model: Any) -> Predict:
    """Read both probability vectors for calibration and reporting."""

    def predict(text: str) -> dict[str, dict[str, float]]:
        answers = model.decide(text)["answers"]
        return {key: answers[key]["probs"] for key in base.ROUTE_QUESTIONS}

    return predict


def fit_setfit(checkpoint: Path, output: Path) -> Any:
    """Train a contrastive sentence encoder and logistic joint scope/mode head."""
    from datasets import Dataset
    from setfit import SetFitModel, Trainer, TrainingArguments
    from transformers import set_seed

    set_seed(42)
    examples = training()
    labels = [r["scope"] + "/" + r["mode"] for _, r in examples]
    import torch

    torch.set_num_threads(2)
    model = SetFitModel.from_pretrained(str(checkpoint), device="cpu")
    args = TrainingArguments(
        batch_size=8,
        max_steps=24,
        max_length=128,
        use_amp=False,
        save_strategy="no",
        report_to="none",
        output_dir=str(output / "trainer"),
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=Dataset.from_dict({"text": [text for text, _ in examples], "label": labels}),
    )
    trainer.train()
    model.save_pretrained(str(output / "setfit"))
    return SetFitModel.from_pretrained(str(output / "setfit"), device="cpu")


def save(path: Path, data: Any) -> None:
    """Write JSON report data with a trailing newline."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def provenance(candidate: str) -> Row:
    """Identify the software, labelled inputs and ordered state/label pairs used in a run."""
    packages = (
        ("laya", "vegaml", "torch")
        if candidate == "laya"
        else (
            "setfit",
            "sentence-transformers",
            "transformers",
            "torch",
            "onnxruntime",
            "scikit-learn",
        )
    )
    files = [
        "laya_routing_training.synthetic.tsv",
        "routing_matched_train.jsonl",
        "routing_calibration.synthetic.jsonl",
        "routing_fresh.synthetic.jsonl",
        retrieval.MESSAGES_PATH.name,
        retrieval.FOLLOWUPS_PATH.name,
    ]
    examples = training()
    return dict(
        candidate=candidate,
        system=platform.platform(),
        python=platform.python_version(),
        packages={name: version(name) for name in packages},
        dataset_sha256={
            name: hashlib.sha256((base.DATA / name).read_bytes()).hexdigest() for name in files
        },
        training_count=len(examples),
        training_sha256=hashlib.sha256(
            json.dumps(examples, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    )


def inputs() -> dict[str, list[Row]]:
    """Load all evaluation splits and reject cross-split example or family leaks."""
    materials = retrieval.load_materials()
    ids = [r["id"] for r in retrieval.load_questions(retrieval.QUESTIONS_PATH, materials)]
    historical = retrieval.load_messages(retrieval.MESSAGES_PATH, materials, ids)
    historical += retrieval.load_followups(materials=materials, question_ids=ids)
    splits = {s: scenarios(f"routing_{s}.synthetic.jsonl") for s in ("calibration", "fresh")}
    splits["historical"] = historical
    matched = scenarios("routing_matched_train.jsonl")
    seen = {base.normalized(r["message"]) for r in matched}
    seen.update(
        base.normalized(r[3]) for r in base.read_training("laya_routing_training.synthetic.tsv", 4)
    )
    groups = {r["group"] for r in matched}
    for rows in splits.values():
        messages = {base.normalized(r["message"]) for r in rows}
        families = {r["group"] for r in rows if "group" in r}
        if groups & families or seen & messages:
            raise ValueError("Overlapping experiment splits")
        groups.update(families)
        seen.update(messages)
    return splits


def observe(row: Row, predict: Predict) -> Row:
    """Record raw model decisions even for turns reserved for gate-only serving."""
    gate = retrieval.gate_decision(row)
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
    for key, schema in base.ROUTE_QUESTIONS.items():
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
        gate=base.scope_name(gate.course, gate.student),
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


def interval(n: int, total: int) -> Row:
    """Compute counts and descriptive Wilson 95% intervals for turn-level rates."""
    result = retrieval.rate_record(n, total)
    if total:
        p, z = n / total, 1.96
        center = p + z * z / (2 * total)
        delta = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
        result["wilson95"] = [
            max(0, (center - delta) / (1 + z * z / total)),
            min(1, (center + delta) / (1 + z * z / total)),
        ]
    return result


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
                gate = retrieval.gate_decision(row)
                effective, reason = base.scope_name(gate.course, gate.student), "busy"
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
            if r["file"] and not r["explicit_mode"] and not retrieval.gate_decision(r).scope_cleared
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


def compact_predictors(model: Any, output: Path) -> tuple[Predict, Predict]:
    """Export the fitted encoder and linear head together and expose both CPU paths."""
    import numpy as np
    import onnxruntime as ort
    import torch

    class Export(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.body = model.model_body
            self.register_buffer("weights", torch.from_numpy(model.model_head.coef_.T).float())
            self.register_buffer("bias", torch.from_numpy(model.model_head.intercept_).float())

        def forward(self, input_ids: Any, attention_mask: Any) -> Any:
            embedding = self.body(dict(input_ids=input_ids, attention_mask=attention_mask))[
                "sentence_embedding"
            ]
            return (embedding @ self.weights + self.bias).softmax(dim=-1)

    graph = output / "setfit.onnx"
    features = model.model_body.tokenize(["A short routing example."])
    names = ["input_ids", "attention_mask"]
    torch.onnx.export(
        Export().eval(),
        tuple(features[n] for n in names),
        str(graph),
        input_names=names,
        output_names=["probabilities"],
        opset_version=17,
        dynamic_axes={
            **{n: {0: "batch", 1: "tokens"} for n in names},
            "probabilities": {0: "batch"},
        },
    )
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = torch.get_num_threads()
    session = ort.InferenceSession(
        str(graph), sess_options=opts, providers=["CPUExecutionProvider"]
    )

    def marginal(values: Any) -> dict[str, dict[str, float]]:
        probs = {
            head: dict.fromkeys(schema["criteria"], 0.0)
            for head, schema in base.ROUTE_QUESTIONS.items()
        }
        for label, value in zip(model.model_head.classes_, values, strict=True):
            scope, mode = label.split("/")
            probs["scope"][scope] += float(value)
            probs["mode"][mode] += float(value)
        return probs

    def exported(text: str) -> dict[str, dict[str, float]]:
        tokens = model.model_body.tokenize([text])
        values = session.run(None, {n: np.asarray(tokens[n]) for n in names})[0][0]
        return marginal(values)

    return lambda s: marginal(model.predict_proba(s, as_numpy=True)), exported


def main() -> None:
    """Run one experiment in its isolated dependency environment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", choices=("laya", "compact"))
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--reuse", action="store_true", help="reload fitted bundle already in output directory"
    )
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    retrieval._block_network()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=args.reuse)
    if (output / "report.json").exists():
        raise FileExistsError("Choose a new report directory")
    splits = inputs()
    if args.candidate == "laya":
        if args.reuse:
            from laya import Learner

            model = Learner(
                bundle=output / "routing.zip",
                reader=base.load_vega_reader(args.checkpoint),
                auto=False,
                cache=0,
            )
        else:
            model = fit_laya(args.checkpoint, output)
        report = evaluate(laya_predictor(model), splits)
        report["learner_status"] = model.status()["questions"]
        report["run"] = provenance("laya")
        save(output / "report.json", report)
    else:
        import torch
        from setfit import SetFitModel

        model = (
            SetFitModel.from_pretrained(str(output / "setfit"), device="cpu")
            if args.reuse
            else fit_setfit(args.checkpoint, output)
        )
        torch.set_num_threads(1)
        native, exported = compact_predictors(model, output)
        report = evaluate(native, splits)
        report["run"] = provenance("compact")
        save(output / "report.json", report)
        onnx = evaluate(exported, splits, report["cutoffs"])
        onnx["run"] = report["run"]
        pairs = [
            (a, b)
            for split in splits
            for a, b in zip(report["rows"][split], onnx["rows"][split], strict=True)
        ]
        onnx["agreement_with_native"] = {
            key: interval(sum(a[key] == b[key] for a, b in pairs), len(pairs))
            for key in ("raw", "effective", "effective_mode")
        }
        save(output / "onnx-report.json", onnx)


if __name__ == "__main__":
    main()
