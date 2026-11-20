# Refactor baseline (Step 0)

Captured before any code change on branch `improvement/backend`, HEAD
`4fb7c9278220fdd9a3f4b5bff795bfe1428246e6`, clean tree, in sync with
`origin/improvement/backend`. Python 3.12.13 venv, mock-ci env vars:

```sh
export MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false \
  AUTO_ADVANCE_STAGES=false APP_ENV=development
PY=/projects/sandbox/.venvs/nus-codesign-py312/bin/python
```

No live flag was used anywhere. Nothing here calls AWS, Bedrock, AgentCore, a
Knowledge Base or OpenAI.

## Static check and test suite

| Command | Result |
|---|---|
| `ruff check .` | exit 0, `All checks passed!` |
| `$PY -m pytest -p no:cacheprovider` (full suite) | exit 1: **2753 passed, 2 failed, 1 skipped**, 295 warnings, 141.9 s |

Known baseline failures (2), both need the built reader bundle `frontend/dist`
that is not in this checkout (the response is 404 instead of 200):

- `tests/http/test_notebook_reader.py::test_pilot_serves_only_built_public_assets`
- `tests/http/test_notebook_reader.py::test_default_workspace_and_streamlit_gate`

Skipped (1): `tests/domain/test_strands_first_cycle_middleware.py` (`strands` not installed).

Stand-in tests for the eval commands, run alone at this HEAD: `tests/scripts/test_compare_turn_routes.py` 7 passed,
`test_evaluate_course_intent_learn.py` 4, `test_benchmark_course_intent.py` 10,
`test_evaluate_combined_gate.py` 21, `test_benchmark_agentcore_vs_converse.py` 41,
`test_evaluate_retrieval.py` 103.

## Offline gate numbers (295 messages, `evaluate_retrieval.py`, offline)

- wrong-skip: **76/154 (49.4%)**; clear rows only 51/113 (45.1%); classifier only 85/154 (55.2%)
- false-retrieve: **7/141 (5.0%)**
- recall@4 (material): **91/94 (96.8%)**; recall@4 (page) 78/94 (83.0%); empty-result rate 0/94
- follow-up cases: 12 (retrieve 9, skip 3); gate wrong-skip 8/9, false-retrieve 0/3

## Per-message decisions

`gate-decisions-before.json` (165,736 bytes, sorted by id, byte-reproducible) holds,
for each of the 295 gate messages: `effective_scope` (`course`/`student_upload`/`both`/`none`),
`mode` (`GateDecision.expected_mode`), `retrieve`, plus the full `GateDecision` fields. The
section `followup_cases` holds the same for the 12 follow-up cases (retrieve cases also carry the
standalone-question decision that `evaluate_followups` computes). The dataset SHA-256s are stored
in the file.

Collected with a read-only scratch script that calls the existing
`scripts.evals.evaluate_retrieval.gate_decision()`; nothing in the refactored code was touched:

```sh
$PY .agents/tasks/refactor-baseline/dump_gate_decisions.py OUTPUT.json
```

Two runs were byte-identical. Cross-check: 85 messages are retrieved (49 course only, 14 both,
22 student upload only), which matches 154 − 76 = 78 correct retrieves + 7 false retrieves.

Mode counts: `coaching` 221 (207 none, 12 student_upload, 2 course), `qa` 74.

## Re-running and diffing

```sh
sh .agents/tasks/refactor-baseline/run_offline_evals.sh OUT_DIR after   # from the repo root
$PY .agents/tasks/refactor-baseline/diff_outputs.py \
  .agents/tasks/refactor-baseline OUT_DIR before after                  # exit 0 = identical
$PY .agents/tasks/refactor-baseline/dump_gate_decisions.py OUT_DIR/gate-decisions-after.json
cmp .agents/tasks/refactor-baseline/gate-decisions-before.json OUT_DIR/gate-decisions-after.json
```

`run_offline_evals.sh` takes ~80 s and writes `<name>.<label>.{json,stdout.txt,stderr.txt}` plus
`exit-codes.<label>.tsv`. `diff_outputs.py` removes the per-run fields before comparing.

If code moves in item 2, only the `import` lines and function lookups at the top of
`stub_snapshots.py` may change; its JSON output must not.

## Offline commands captured (all run, files in this directory)

| Name | Exact command (repo root) | Output files | Exit | Varies per run |
|---|---|---|---|---|
| evaluate_retrieval | `$PY scripts/evals/evaluate_retrieval.py --json-output OUT/evaluate_retrieval.before.json` | `evaluate_retrieval.before.json`, `.stdout.txt` | 0 | `run.git_sha`, `run.git_dirty`, `run.generated_at_utc` |
| evaluate_combined_gate | `$PY -m scripts.evals.evaluate_combined_gate --json-output OUT/evaluate_combined_gate.before.json` | `evaluate_combined_gate.before.json`, `.stdout.txt` | 0 | same three `run` fields |
| benchmark_agentcore_vs_converse (dry run) | `$PY scripts/evals/benchmark_agentcore_vs_converse.py --dry-run --max-live-calls 100` | `benchmark_agentcore_vs_converse_dry_run.before.stdout.txt` (prints plan, writes no JSON) | 0 | none |
| benchmark_agentcore_vs_converse (refusal) | `$PY scripts/evals/benchmark_agentcore_vs_converse.py` | `..._refusal.before.stderr.txt` | 2 | none |
| evaluate_retrieval `--live-kb` refusal (no call limit, refuses before any client) | `$PY scripts/evals/evaluate_retrieval.py --live-kb` | `evaluate_retrieval_live_kb_refusal.before.stderr.txt` | 2 | none |
| benchmark_course_intent (stub, `real_model: false`) | `$PY -m scripts.evals.benchmark_course_intent --stub-ms 5 --passes 3 --warmup 5 --json-output OUT/benchmark_course_intent_stub.before.json` | `benchmark_course_intent_stub.before.json`, `.stdout.txt` | 0 | all timings and RSS (floats); `run` fields. Counts, strings and keys are stable |
| measure_stream_first_text | `$PY scripts/evals/measure_stream_first_text.py --runs 3 --label baseline --json-output OUT/measure_stream_first_text.before.json` | `measure_stream_first_text.before.json`, `.stdout.txt` | 0 | all timings; top-level `git_sha` (short) and `utc` |
| fast_chat_quality_matrix | `$PY scripts/evals/fast_chat_quality_matrix.py --dry-run` | `fast_chat_quality_matrix_dry_run.before.stdout.txt` | 0 | none |
| evaluate_fast_chat_regression | `$PY scripts/evals/evaluate_fast_chat_regression.py --dry-run` | `evaluate_fast_chat_regression_dry_run.before.stdout.txt` | 0 | none |
| `--help` of nine commands (CLI surface) | `$PY -m scripts.evals.<name> --help` for compare_turn_routes, evaluate_passage_support, evaluate_laya_turn_decisions, evaluate_course_intent_learn, evaluate_course_intent, evaluate_combined_gate, benchmark_agentcore_vs_converse, benchmark_course_intent, evaluate_retrieval | `help_<name>.before.stdout.txt` | 0 each | none |
| stub snapshots | `$PY .agents/tasks/refactor-baseline/stub_snapshots.py OUT before` | `stub_snapshots.before.json` | 0 | none (timing fields removed) |

Run-to-run check: a second capture matched the first after normalisation (41 comparisons, 0 differing). Raw differences were
only the `run` fields, the timing values and the output path printed by `stub_snapshots`.

## Commands that cannot run offline here

`laya`, `vegaml` and `setfit` are not installed (`ModuleNotFoundError`), and no checkpoint or
bundle exists in the sandbox. Their `--help` is captured above. Each stand-in is a stored fixture or a
stub-model test:

| Command | Reason it cannot run | Stand-in |
|---|---|---|
| `compare_turn_routes` (`laya` / `compact`) | needs `--checkpoint`, `laya`/`vegaml` (fit) or `setfit`/`torch`/`onnxruntime` | `tests/scripts/test_compare_turn_routes.py` (7 tests: `observe`, `apply`, explicit scope overrides, runtime context) and `stub_snapshots.before.json` → `compare_turn_routes` (`inputs()`, `training()`, full `evaluate()` with a hash-based stub predictor, timing removed) |
| `evaluate_passage_support` (`rank`/`judge`) | needs a cross-encoder or a Laya judge and checkpoint | `test_fact_union_requires_every_fact` in `tests/scripts/test_compare_turn_routes.py` and `stub_snapshots.before.json` → `evaluate_passage_support` (`run()` lexical only, with a stub judge, with reversed stored orders) |
| `evaluate_laya_turn_decisions` | needs `laya`, `vegaml`, checkpoint | `stub_snapshots.before.json` → `evaluate_laya_turn_decisions` (`route_state`, `evidence_state`, `read_training`, `decide` with a stub judge, `scope_name`). It has no test of its own in `tests/` |
| `evaluate_course_intent_learn` | needs `laya`, `vegaml`, Vega checkpoint | `tests/scripts/test_evaluate_course_intent_learn.py` (4 tests, stub `laya` module) and `stub_snapshots.before.json` → `evaluate_course_intent_learn` (split ids, `select_threshold`, `evaluate_routes`) |
| `evaluate_course_intent` | needs `laya` and a checkpoint | `_p95_ms` only; no test or snapshot covers its `main`. Its `--help` is captured |
| `benchmark_course_intent --checkpoint` | needs `laya` and weights | the `--stub-ms` run above (marked `real_model: false`) and `tests/scripts/test_benchmark_course_intent.py` |
| `evaluate_combined_gate --checkpoint` | re-run of Laya from weights | default offline run (stored `phase3d-work` Laya results) and `tests/scripts/test_evaluate_combined_gate.py` |
| `evaluate_retrieval --live-kb / --live-model`, `benchmark_agentcore_vs_converse --live-benchmark` | paid live calls; never run | refusal exit codes above and the stub-client tests in `tests/scripts/test_evaluate_retrieval.py`, `test_benchmark_agentcore_vs_converse.py` |
| `evaluate_live_coach`, `evaluate_fast_chat_regression` live | paid live calls (`evaluate_live_coach --dry-run` also needs `AGENTCORE_EVAL_HARNESS_ARN`, not set). Neither imports another eval module | `evaluate_fast_chat_regression --dry-run` captured; `tests/scripts/test_evaluate_fast_chat_regression.py` |

## Files in this directory

`gate-decisions-before.json`, `evaluate_retrieval.before.json`, `evaluate_combined_gate.before.json`,
`benchmark_course_intent_stub.before.json`, `measure_stream_first_text.before.json`,
`stub_snapshots.before.json`, the `*.before.stdout.txt` and `*.before.stderr.txt` files,
`exit-codes.before.tsv`, and the four helper scripts `dump_gate_decisions.py`,
`run_offline_evals.sh`, `diff_outputs.py`, `stub_snapshots.py`.

## Item 1 after-capture (evidence scope moved to `backend/coaching/evidence_scope.py`)

Same dump method and command as `gate-decisions-before.json`, run from the repo root with the mock env vars:

```sh
$PY .agents/tasks/refactor-baseline/dump_gate_decisions.py .agents/tasks/refactor-baseline/gate-decisions-after.json
diff .agents/tasks/refactor-baseline/gate-decisions-before.json .agents/tasks/refactor-baseline/gate-decisions-after.json   # empty, exit 0
```

`gate-decisions-after.json` is committed beside the before file. The offline evals were re-run with
`sh .agents/tasks/refactor-baseline/run_offline_evals.sh .agents/tasks/refactor-evidence-scope/out after`
and compared with `diff_outputs.py` (41 comparisons, 0 differing); the log is
`.agents/tasks/refactor-evidence-scope/item1-offline-diff.txt`.
