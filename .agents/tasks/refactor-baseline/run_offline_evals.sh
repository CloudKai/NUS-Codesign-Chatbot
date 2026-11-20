#!/bin/sh
# Re-runnable capture of every scripts/evals command that runs offline here.
#
#   sh .agents/tasks/refactor-baseline/run_offline_evals.sh OUT_DIR LABEL
#
# Run from the repository root. LABEL is "before" or "after" and becomes part of
# each output file name (<name>.<LABEL>.json / .stdout.txt). Exit codes go to
# OUT_DIR/exit-codes.<LABEL>.tsv. No command here uses a live flag: nothing
# calls AWS, Bedrock, AgentCore, a Knowledge Base, OpenAI or any network.
# See commands.md for the fields that vary per run.

set -u
OUT="${1:?output directory}"
LABEL="${2:?label (before or after)}"
PY="${PY:-/projects/sandbox/.venvs/nus-codesign-py312/bin/python}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
CODES="$OUT/exit-codes.$LABEL.tsv"
: > "$CODES"

export MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false
export AUTO_ADVANCE_STAGES=false APP_ENV=development

# run NAME COMMAND...   stdout -> NAME.LABEL.stdout.txt, stderr -> NAME.LABEL.stderr.txt
run() {
  name="$1"
  shift
  "$@" > "$OUT/$name.$LABEL.stdout.txt" 2> "$OUT/$name.$LABEL.stderr.txt"
  printf '%s\t%s\n' "$name" "$?" >> "$CODES"
}

run evaluate_retrieval "$PY" scripts/evals/evaluate_retrieval.py \
  --json-output "$OUT/evaluate_retrieval.$LABEL.json"
run evaluate_combined_gate "$PY" -m scripts.evals.evaluate_combined_gate \
  --json-output "$OUT/evaluate_combined_gate.$LABEL.json"
run benchmark_agentcore_vs_converse_dry_run "$PY" scripts/evals/benchmark_agentcore_vs_converse.py \
  --dry-run --max-live-calls 100
run benchmark_course_intent_stub "$PY" -m scripts.evals.benchmark_course_intent \
  --stub-ms 5 --passes 3 --warmup 5 --json-output "$OUT/benchmark_course_intent_stub.$LABEL.json"
run measure_stream_first_text "$PY" scripts/evals/measure_stream_first_text.py \
  --runs 3 --label baseline --json-output "$OUT/measure_stream_first_text.$LABEL.json"
run fast_chat_quality_matrix_dry_run "$PY" scripts/evals/fast_chat_quality_matrix.py --dry-run
run evaluate_fast_chat_regression_dry_run "$PY" scripts/evals/evaluate_fast_chat_regression.py --dry-run

# Commands that need laya, vegaml, setfit or local weights cannot run here.
# Their --help output records the CLI surface (flags, defaults) that must not change.
run help_compare_turn_routes "$PY" -m scripts.evals.compare_turn_routes --help
run help_evaluate_passage_support "$PY" -m scripts.evals.evaluate_passage_support --help
run help_evaluate_laya_turn_decisions "$PY" -m scripts.evals.evaluate_laya_turn_decisions --help
run help_evaluate_course_intent_learn "$PY" -m scripts.evals.evaluate_course_intent_learn --help
run help_evaluate_course_intent "$PY" -m scripts.evals.evaluate_course_intent --help
run help_evaluate_combined_gate "$PY" -m scripts.evals.evaluate_combined_gate --help
run help_benchmark_agentcore_vs_converse "$PY" -m scripts.evals.benchmark_agentcore_vs_converse --help
run help_benchmark_course_intent "$PY" -m scripts.evals.benchmark_course_intent --help
run help_evaluate_retrieval "$PY" -m scripts.evals.evaluate_retrieval --help

# Offline refusal paths of the paid tools (exit 2, no client is built).
run benchmark_agentcore_vs_converse_refusal "$PY" scripts/evals/benchmark_agentcore_vs_converse.py
run evaluate_retrieval_live_kb_refusal "$PY" scripts/evals/evaluate_retrieval.py --live-kb

# Stub-model stand-ins for the commands that need weights (deterministic parts only).
run stub_snapshots "$PY" "$HERE/stub_snapshots.py" "$OUT" "$LABEL"
