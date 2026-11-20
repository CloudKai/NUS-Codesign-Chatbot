"""Fit and evaluate CPU routing candidates on fixed synthetic splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from importlib.metadata import version
from pathlib import Path
from typing import Any

from backend.course_intent import load_vega_reader
from scripts.evals.lib.metrics import interval
from scripts.evals.lib.offline import block_network
from scripts.evals.lib.output import save
from scripts.evals.lib.paths import DATASET_DIR, FOLLOWUPS_PATH, MESSAGES_PATH

# The scoring half (splits, observe/apply, summaries, latency, assess) lives in
# scripts/evals/lib/route_scoring.py so evaluate_laya_turn_decisions can use it
# without importing this command. The names are re-exported for existing callers.
from scripts.evals.lib.route_scoring import (
    Predict as Predict,
    Row as Row,
    apply as apply,
    assess as assess,
    evaluate,
    inputs,
    laya_predictor,
    latency as latency,
    observe as observe,
    scenarios as scenarios,
    state as state,
    summary as summary,
    training,
)
from scripts.evals.lib.turn_state import ROUTE_QUESTIONS


def fit_laya(checkpoint: Path, output: Path) -> Any:
    """Fit, save and reload both Laya choices on CPU."""
    from laya import Learner

    reader = load_vega_reader(checkpoint)
    bundle = output / "routing.zip"
    model = Learner(ROUTE_QUESTIONS, examples=training(), reader=reader, auto=False, cache=0)
    model.save_bundle(bundle)
    return Learner(bundle=bundle, reader=reader, auto=False, cache=0)


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
        MESSAGES_PATH.name,
        FOLLOWUPS_PATH.name,
    ]
    examples = training()
    return dict(
        candidate=candidate,
        system=platform.platform(),
        python=platform.python_version(),
        packages={name: version(name) for name in packages},
        dataset_sha256={
            name: hashlib.sha256((DATASET_DIR / name).read_bytes()).hexdigest() for name in files
        },
        training_count=len(examples),
        training_sha256=hashlib.sha256(
            json.dumps(examples, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    )


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
            for head, schema in ROUTE_QUESTIONS.items()
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
    block_network()
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
                reader=load_vega_reader(args.checkpoint),
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
