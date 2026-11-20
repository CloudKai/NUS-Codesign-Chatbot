# Head-to-head routing evaluation: pre-registration

Branch `improvement/backend`, written at base commit `e9bebcb`. This file is committed and pushed before any code that evaluates an arm on the holdout half exists, and before any per-half figure has been computed or read.

## 0. Status of knowledge at the time of writing

- No calibration or holdout size, no per-half count, and no per-half outcome has been computed or read. The split sizes are whatever the rule in section 2 gives.
- Whole-set facts known beforehand, from earlier reports and from reading file schemas. None is split by half:
  - The gate retrieves 85 of 295 messages. It wrongly skips 76 of the 154 `retrieve` rows and wrongly retrieves 7 of the 141 `skip` rows.
  - Stored Laya decisions cover 94 of the 147 eligible rows for the multilingual checkpoint, and 41 for the Learn bundle on a different cutoff.
  - Stored Laya latency comes from a development laptop.
- These facts did not shape any rule below. They are recorded so a reader can judge that.
- The agents running this task will not see any live Knowledge Base score. Live runs are prohibited in the sandbox. Arms C and D, and the KB-dependent parts of A and B, can therefore only be computed by the operator from a live KB gate file. Without that file the report labels them `missing` or `bound` (section 11), never `measured`.
- Arm A and arm B can be computed offline from stored Laya decisions in three readings: floor, ceiling and scored-only. Their holdout figures must also be computed only after this plan is committed and pushed.

## 1. Data

- The evaluated set is the 295 messages in `scripts/evals/datasets/retrieval_gate_messages.synthetic.jsonl` (ids `gm001` to `gm295`). Fields used: `id`, `category`, `expected_decision` (`retrieve` 154, `skip` 141) and the row inputs read by `scripts/evals/lib/gate.py`.
- Eligibility is the existing one, from `scripts/evals/lib/prepared_rows.py` (`prepare_rows`, which calls `local_course_intent_candidate`). 147 rows are eligible. Eligibility only decides which rows Laya may score. All four arms are evaluated on all 295 rows.
- Follow-up cases: the 12 cases in `scripts/evals/datasets/retrieval_gate_followups.synthetic.jsonl` (ids `gm296` to `gm307`) are **outside** the 295. They are not split, not used to choose T, not counted in M1 to M6, not in any test, and are not sent in the live KB gate run.
- `--extra-messages` rows (human-labelled messages) are reported in a separate section. They are never split, never used to choose T, never mixed into M1 or M2, and never included in a paired test. The frozen T and the unchanged Laya cutoffs are applied to them as is. They are descriptive only and carry no pass or fail. A row whose `synthetic` marker is not true is refused unless the operator passes the documented `--allow-non-synthetic` flag, and the section is then marked `real_messages`. Message text is never written to any output.

## 2. Split: calibration and holdout

- Rule, fixed: let `h = int(hashlib.sha256(row_id.encode("utf-8")).hexdigest(), 16)`. The row is **calibration** if `h % 2 == 0`, otherwise **holdout**.
- No salt, no re-roll, no stratification. Sizes are whatever the rule gives and are not known in advance.
- The rule is implemented once, as one function in `scripts/evals/lib/prereg.py`. Every command and test calls that function. The constants block in section 14 is compared with the code by a test.
- Calibration rows are used for exactly one purpose: choosing T (section 3). All reported metrics, paired tests and pass or fail decisions use holdout rows only. Calibration figures may be printed in a separate section labelled as such.

## 3. Choosing T (KB top-score threshold)

T applies to arms C and D. It is chosen per arm (`T_C`, `T_D`) by code, with no human step and no override flag.

- **Input.** Calibration rows only, with the arm's search decisions from section 4 and the live KB gate rows (top validated score, result count, status) for those ids.
- **Injection rule under T.** Evidence is injected iff the arm searched the KB, the call did not fail, the validated result count is at least 1, and top validated score `>= T`. Any local search counts as injected too (section 5).
- **Candidate grid.** The distinct top validated scores observed on calibration rows where the arm searched the KB and the result count is at least 1, plus `+inf` (inject KB evidence never).
- **Objective.** Among candidates whose calibration M2 point estimate is at most 10%, take the one with the lowest calibration M1 point estimate. M2 can only fall and M1 can only rise as T rises, so the feasible set is a set of the highest candidates and the objective picks the lowest feasible T on any plateau.
- **Tie-break.** If candidates tie on M1, take the lower calibration M2. If they still tie, take the highest T.
- **No feasible T.** If no candidate has calibration M2 at most 10% (local searches can make this happen even at `+inf`), the arm is reported as "no feasible T" and **fails**.
- **Frozen.** T is written to the JSON output and applied unchanged to the holdout rows. T is never recomputed using holdout rows.
- **Arm D and Laya readings.** `T_D` is chosen with the floor reading of Laya (unscored eligible rows not promoted). When a full all-rows Laya file is supplied, `T_D` is chosen by the same rule on the calibration rows of that file. The Laya cutoffs are read from the existing files and are never fitted (section 4, arm B).
- **Partial KB file.** KB-dependent metrics need a KB gate file that covers all 295 ids. A partial file gives `missing`. No T is chosen from a partial file.
- **Known weakness.** T is chosen on a point estimate from roughly half of the data, so it is optimistic. KB scores are not calibrated across queries. T is purely empirical for this Knowledge Base.

## 4. Arms

All arms see the same 295 rows and the same eligibility. All scope decisions go through `backend/coaching/evidence_scope.py` (`decide_first_pass_scope`, line 348). No new gate rule, regex or setting is added.

- **A: existing gate.** The KB-search decision of `decide_first_pass_scope(scope_inputs_for_row(row))`, read through `gate_decision(row)` in `scripts/evals/lib/gate.py`.
- **B: gate + Laya.** `decide_first_pass_scope(inputs, course_intent_promoted=promoted and eligible)`, the current promotion rule as composed in `scripts/evals/evaluate_combined_gate.py`. Cutoffs are read and never fitted:
  - **Primary:** the multilingual checkpoint at 0.8 (`settings.local_course_intent_threshold`, `backend/settings.py:390`).
  - **Secondary:** Laya Learn at 0.8563768 for continuing turns and 0.6455846 for the first turn (stored as `thresholds_from_calibration` in `.agents/tasks/phase3d-work/course-intent-by-turn.json`). These are the 0.8564 and 0.6456 of the task. The Learn bundle was fitted on 150 rows of this same set, so Learn is secondary evidence only.
  - **Also secondary:** the stored typed decisions (`.agents/tasks/phase3d-work/typed-decisions.json`).
  - Each source is reported in three readings, as in `evaluate_combined_gate.py`: floor (unscored eligible rows not promoted), ceiling (unscored eligible rows all promoted) and scored-only (unscored eligible rows left out for every arm in that reading).
- **C: KB-score routing.** The row is **skipped** (no KB search) iff any of the three existing skip rules fires. Otherwise the arm searches the KB, and evidence is injected iff the top validated score is `>= T_C`. The three rules, mapped to existing code with no new logic:

  | Rule | Existing code | Arm C reads |
  |---|---|---|
  | Greeting or acknowledgement | `is_chit_chat`, `backend/coaching/evidence_scope.py:281`. It calls `is_greeting_or_acknowledgement` (`backend/retrieval.py:152`) and `looks_like_information_request` (`backend/coaching/mode_policy.py:296`). | `is_chit_chat(row["message"])` |
  | Stage navigation | `scope_cleared`, built at `backend/coaching/evidence_scope.py:447` from `is_current_stage_status_request` (`backend/coaching/workflow_navigation.py:440`), `is_stage_progression_request` (`:705`), `is_terminal_completion_request` (`:730`) and `workflow_skips_retrieval` (`:683`) | `gate_decision(row).scope_cleared` |
  | Personal reasoning | `_is_personal_reasoning` over `_PROJECT_REASONING`, `backend/retrieval_gate.py:338` and `:173`. It returns `INTENT_HIGH_CONFIDENCE_PERSONAL` (`:431`) and reaches `ScopeDecision.classifier_intent` (`evidence_scope.py:176`, set at `:389`). | `gate_decision(row).intent == "high_confidence_personal"` |

  The skip is the OR of the three. Precedence for attribution only is greeting, navigation, personal. All three are isolated without new logic, so arm C is evaluated and not marked "cannot be evaluated". Caveats, reported with the results:
  - Greeting is not an existing skip decision today. The gate skips greetings only because no cue matches. Arm C reuses the predicate as a skip rule. Its docstring lists known misses (`thx`, `haha nice`, `ok will try`). Those rows go to the KB, and T is the only protection.
  - `is_chit_chat` does not check source cues, so a mixed message such as "hello, week 3 reading summary" can be skipped by C where the gate would retrieve.
  - `scope_cleared` also covers meta-guidance and prior-stage review, not only status and progression.
  - Dataset rows carry no `explicit_mode`, so Lecture Help never triggers. `force_retrieval`, frozen history and missing image bytes are held at the values documented in `scripts/evals/lib/gate.py`.
  - Arm C keeps arm A's local-search flag. A production arm C would probably search more local files. That is not modelled (section 5).
- **D: hybrid.** Same KB-search decision as arm B (gate + Laya decide whether to search). Evidence is injected iff the arm searched, the call did not fail, the validated result count is at least 1, and the top validated score is `>= T_D`.

## 5. "Evidence injected" and what "validated" means

**Evidence injected, per arm, per row:**

- **A and B:** a KB search ran, the call did not fail, and the validated result count is at least 1.
- **C and D:** a KB search ran, the call did not fail, the validated result count is at least 1, and the top validated score is `>= T`.
- **Local searches (all arms):** `searches_personal_files` (`backend/coaching/evidence_scope.py:547`) is the local search of student uploads, not a KB search. All four arms inherit it from `decide_first_pass_scope`. In B and D a Laya promotion can add a local search on rows with non-course sources. Any local search counts as injected. That is a stated bound: it is optimistic for M1 and pessimistic for M2.
- A failed or empty KB call means no evidence. The count of failed calls is reported, so a fail-closed outcome is never confused with a low score.

**Validated hit.** The live KB gate reuses the production adapter in `backend/bedrock_retrieve.py` unchanged. A hit counts only if it survives these steps:

1. It maps to a selected course source. `_hit_drop_reason` (`:377`) and `_match_selected_source` (`:409`) require a non-empty S3 bucket equal to the configured `COURSE_MATERIALS_BUCKET`, and a key that canonically matches a selected source. Otherwise the hit is dropped as `bucket_mismatch` or `key_mismatch`.
2. It has text. `_excerpt_text` (`:438`). Empty text is dropped as `empty_text`.
3. Raw hits are sorted by score, descending, before validation (`:990-993`). The score is `_result_score` (`:448`), and the chunk score is rounded to 6 places (`:1042`).
4. `bounded_retrieval_result(..., max_chunks=...)` (`:1091-1094`, defined in `backend/retrieval.py:1161`) skips placeholder and duplicate excerpts and keeps at most 4 chunks.
5. Request settings are production values. `number_of_results = max(1, candidates, max_results)` (`:609`), with `KNOWLEDGE_BASE_RETRIEVE_CANDIDATES` default 12 (`backend/settings.py:313`) and `FAST_CHAT_RETRIEVAL_MAX_CHUNKS` default 4 (`:359`). The filter is on `course_material_id` (`_search_configuration` `:513`, `_course_material_ids` `:491`). The metadata filter mode default is `required` (`:626`). The timeout is 10 s (`:308`).

Definitions used by every metric:

- **Top validated score** is `result.chunks[0].score` after step 4, which is the maximum validated score.
- **Result count** is `len(result.chunks)`, at most 4.
- **`status == "unavailable"`** is a failed call: no evidence, counted and reported. The adapter swallows exceptions (`:781`, `classify_retrieve_failure` at `:89`), so the live run wraps the client to record the raised exception and tests it with `is_auth_or_access_error` (`scripts/evals/lib/live.py:445`) to stop on the first auth error.
- **Elapsed ms** is measured around `retriever.retrieve`.

## 6. Metrics (all on holdout rows, per arm)

Intervals are Wilson 95% (`z = 1.96`). Any sample under 30 rows is marked small, and under 10 very small, as in the existing combined-gate report.

- **M1.** Among rows labelled `retrieve`: the share with NO evidence injected.
- **M2.** Among rows labelled `skip`: the share WITH evidence injected.
- **M3.** Searches added per 100 turns versus arm A: `100 * (searches(arm) - searches(A)) / turns`. KB searches and local searches are counted separately. The value is signed. Turns means the holdout rows. Figures for all 295 rows are shown separately and labelled descriptive.
- **M4.** Added wait per turn, relative to arm A, over all holdout turns:
  `added(arm, row) = laya_ms(arm, row) + kb_ms(arm, row) - kb_ms(A, row)`.
  - `laya_ms` is the stored Laya inference time for each eligible row in arms B and D, and 0 elsewhere.
  - `kb_ms` is the measured elapsed ms of that row in the live KB gate file, for each row where the arm searched.
  - Arm A is 0 by definition.
  - Report p50 and p95 of the added wait (nearest-rank, over all holdout turns), the KB elapsed ms p50 and p95 over the live run, and Laya ms separately. Arm D shows the combined value.
  - Unscored eligible rows get a lower imputation of 0 ms and an upper imputation equal to the largest stored Laya ms in that source.
  - Local-search time is not measured and is labelled `missing`.
- **M5.** Estimated cost per 1,000 turns. KB is `1,000 * kb_searches_per_turn * 1.00 / 1,000` USD, using the user-supplied price of $1 per 1,000 searches, which is not checked against an AWS page. Other costs are excluded. For Laya the report states host memory (RSS, from the all-rows benchmark file) and not dollars. Until that file exists the memory is `missing`.
- **M6.** Operational risk table, facts only, each row with file and line evidence, and `unknown` where no fact exists. Rows: new dependency, memory, concurrency slot, startup failure, timeout, licence status, packaging effort. Evidence pointers to re-check at report time: `requirements.txt` and `requirements-dev.txt`, `Dockerfile:29-31` and `:36`, `compose.prod.yaml`, `backend/course_intent.py:95-114`, `:150-164`, `backend/owner_context.py:71-78`, `backend/http/app.py:282`, `backend/settings.py:308`, `backend/bedrock_retrieve.py:46` and `:195`, `.agents/tasks/phase3d-work/multilingual-concurrency8.json`, and the Phase 4 report (`.agents/tasks/phase4-2026-11-19.md`).
- **Per category.** M1 or M2 (whichever the category's labels define) for each of the 19 categories, with Wilson intervals and the small mark.

## 7. Paired tests (holdout rows only)

- **Test.** Exact two-sided McNemar test. With `b` and `c` the two discordant counts and `n = b + c`: `p = min(1, 2 * P(X <= min(b, c)))` with `X ~ Binomial(n, 0.5)`. When `n = 0`, `p = 1`. Test vectors: `(5, 0)` gives 0.0625, and `(10, 2)` gives 158/4096.
- **Pairs.** A vs B, A vs C, B vs C, C vs D.
- **Families, each reported separately.** `retrieve` rows (outcome: no evidence injected, the M1 outcome), `skip` rows (outcome: evidence injected, the M2 outcome), and all rows (outcome: mistake, meaning no evidence on a `retrieve` row or evidence on a `skip` row).
- **Shown with every test.** Both discordant counts, the number of rows, and the p-value. No multiplicity correction is applied. The p-values are descriptive.
- **Required note, repeated next to the p-values:** arms B and D only add searches to arm A, so "A is never better than B" on M1 is built in. For B this holds on `retrieve` rows. For D it holds for searches only, because T can withhold evidence that arm A would inject. A significant B-over-A result on `retrieve` rows is therefore expected from construction and is not evidence of Laya quality by itself. The M2 family and the all-rows family carry the information.
- Laya pairs are reported per Laya source and per reading (floor, ceiling, scored-only).
- "Significant" means this exact test gives `p < 0.05`.

## 8. Pass rule (fixed)

An arm **passes** if, on the holdout rows, all hold:

1. M1 point estimate `<= 15%`.
2. M2 point estimate `<= 10%`.
3. Added p95 wait `<= 1,000 ms`.

The rule uses point estimates. Intervals are shown and do not change the outcome. The result per arm has three states:

- **pass:** all three criteria hold under the pessimistic reading of every unknown. M1 uses the floor reading of Laya and counts every KB search with at least one validated result as injected. M2 uses the ceiling reading and the highest possible injection. Wait uses the upper imputation.
- **fail:** at least one criterion fails even under the optimistic reading (M1 at the ceiling, M2 at the floor, wait at the lower imputation). An arm with no feasible T also fails.
- **cannot be determined yet:** everything else. This includes any arm whose KB data, wait data or Laya data is missing. Such an arm is never reported as `pass`.

Without a live KB gate file, an arm can end only as `fail` (when a bound already breaks a criterion) or `cannot be determined yet`. Without an all-rows Laya file, B and D cannot reach `pass` unless the stored decisions cover every eligible row. Nothing is relaxed after results are seen.

## 9. Choosing among passing arms

- Moving-parts order: `A < C < B < D`.
- Walk the arms that **passed**, in that order. The first is the champion. Each later passing arm replaces the current champion only if its holdout M1 is lower **and** the exact McNemar test on the `retrieve` rows against the current champion gives `p < 0.05`. Otherwise the champion stays.
- If no arm passes, the report says that no arm passes. It names the criteria that failed.
- If some arm is `cannot be determined yet`, the selection is labelled provisional and names the undetermined arms. No full comparison is claimed until a live KB gate file and an all-rows Laya file exist.

## 10. Laya coverage

Stored Laya decisions cover only part of the 147 eligible rows (multilingual 94, Learn 41). Each Laya source is shown as floor, ceiling and scored-only. An all-rows Laya file produced by `scripts/evals/benchmark_course_intent.py` with host notes (section 12) is read through `--laya-full`. The cutoffs stay as in section 4, so floor, ceiling and scored-only then coincide. Until that file exists, the report contains no statement of a full B or D comparison.

## 11. Status labels

Every reported figure carries one label:

- **measured:** computed by code from data produced in this repository or by an operator run of the harness, with the host recorded.
- **bound:** a one-sided limit that follows from an assumption stated next to it (a stored Laya reading, a search-only proxy when no KB file exists, development-laptop latency, the local-search rule).
- **missing:** no data exists.

## 12. Host for the final measurements

Instance type `<TYPE>`, vCPU `<N>`, RAM `<GB>`, arch `<arm64|x86_64>`. These stay as literal placeholders. The operator has not supplied values, and none are invented. The harness records whatever the operator passes (`--host-instance-type`, `--host-vcpu`, `--host-ram-gb`, `--host-arch`), checks them against the machine, and does not treat a mismatch as fatal. Host details in the report stay unfilled until the operator runs the commands.

## 13. Freeze and amendments

- Nothing in sections 1 to 12 changes after a holdout result is seen.
- If something here turns out to be wrong, a dated amendment section is appended below, labelled post-hoc, and the report says so. The original text is not edited.
- The report records the sha256 of this file and the commit that contains it.
- Live and host modes are built and covered by mock tests only. They are not run in this task. No production routing, no setting default and nothing under `backend/`, `agentcore_runtime/` or `frontend/` changes.

## 14. Machine-readable constants

A test compares this block with the constants in `scripts/evals/lib/prereg.py`.

```json prereg-constants
{
  "split": {
    "hash": "sha256",
    "input": "row id, utf-8",
    "calibration_if": "int(hexdigest, 16) % 2 == 0",
    "holdout_otherwise": true
  },
  "m1_max": 0.15,
  "m2_max": 0.10,
  "added_p95_wait_ms_max": 1000,
  "calibration_m2_target": 0.10,
  "mcnemar_alpha": 0.05,
  "small_n": 30,
  "very_small_n": 10,
  "complexity_order": ["A", "C", "B", "D"],
  "laya_cutoffs": {
    "multilingual": 0.8,
    "learn_continuing": 0.8563768,
    "learn_first_turn": 0.6455846
  },
  "kb": {
    "candidates": 12,
    "max_results": 4,
    "price_usd_per_1000_searches": 1.0
  },
  "gate_message_count": 295
}
```

## Amendments

None.
