"""Compare two captures made by run_offline_evals.sh.

    python .agents/tasks/refactor-baseline/diff_outputs.py BEFORE_DIR AFTER_DIR [BEFORE_LABEL AFTER_LABEL]

Labels default to "before" and "after". Exit code 0 means every file matches
once the fields that vary per run are removed; 1 means a real difference
(printed as a unified diff of the normalised JSON or text).

Normalisation:
* ``run.git_sha``, ``run.git_dirty``, ``run.generated_at_utc`` (JSON outputs
  written through ``_write_json_output``) and the top-level ``git_sha`` and
  ``utc`` of measure_stream_first_text are removed.
* benchmark_course_intent_stub and measure_stream_first_text are timing and
  memory measurements: every float leaf is masked as ``<float>`` (except the
  ``simulated`` input block), so keys, counts, strings and list lengths still
  have to match.
* Exit codes and every other file are compared exactly.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path
from typing import Any

RUN_KEYS = {"git_sha", "git_dirty", "generated_at_utc"}
TIMING_JSON = {"benchmark_course_intent_stub", "measure_stream_first_text"}
# stdout of these embeds a path or timings; the JSON file is compared instead.
SKIP_STDOUT = {"stub_snapshots", "benchmark_course_intent_stub", "measure_stream_first_text"}


def _normalise(value: Any, *, mask_floats: bool, inside_simulated: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            k: _normalise(v, mask_floats=mask_floats, inside_simulated=inside_simulated or k == "simulated")
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_normalise(v, mask_floats=mask_floats, inside_simulated=inside_simulated) for v in value]
    if mask_floats and isinstance(value, float) and not inside_simulated:
        return "<float>"
    return value


def _load_json(path: Path, name: str) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if isinstance(data.get("run"), dict):
            data["run"] = {k: v for k, v in data["run"].items() if k not in RUN_KEYS}
        if name == "measure_stream_first_text":
            data.pop("git_sha", None)
            data.pop("utc", None)
    data = _normalise(data, mask_floats=name in TIMING_JSON)
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _read(path: Path, name: str) -> str:
    return _load_json(path, name) if path.suffix == ".json" else path.read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 5):
        print(__doc__)
        return 2
    before_dir, after_dir = Path(argv[1]), Path(argv[2])
    before_label, after_label = (argv[3], argv[4]) if len(argv) == 5 else ("before", "after")
    failures = 0
    checked = 0

    codes = {}
    for label, directory in ((before_label, before_dir), (after_label, after_dir)):
        path = directory / f"exit-codes.{label}.tsv"
        codes[label] = path.read_text(encoding="utf-8") if path.exists() else None
    checked += 1
    if codes[before_label] != codes[after_label]:
        failures += 1
        print("DIFF exit codes")
        print("".join(difflib.unified_diff(
            (codes[before_label] or "").splitlines(True), (codes[after_label] or "").splitlines(True),
            "before", "after")))
    else:
        print("same exit codes")

    for path in sorted(before_dir.glob(f"*.{before_label}.*")):
        base = path.name.replace(f".{before_label}.", ".", 1)
        name, _, kind = base.partition(".")
        if base.startswith("exit-codes"):
            continue
        if kind == "stdout.txt" and name in SKIP_STDOUT:
            continue
        other = after_dir / path.name.replace(f".{before_label}.", f".{after_label}.", 1)
        checked += 1
        if not other.exists():
            failures += 1
            print(f"MISSING {other}")
            continue
        left, right = _read(path, name), _read(other, name)
        if left == right:
            print(f"same  {base}")
        else:
            failures += 1
            print(f"DIFF  {base}")
            print("".join(difflib.unified_diff(
                left.splitlines(True), right.splitlines(True), f"before/{base}", f"after/{base}")))
    print(f"{checked} comparisons, {failures} differing")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
