# Refactor report (draft): one owner for first-pass evidence scope

Status: item 1 implemented and verified (section "Item 1 result" at the end); the sections above are the pre-change draft and stay as written. Item 2 has not started.

- Branch `improvement/backend`, HEAD `9d43fe6` at the time of writing, working tree clean.
- Date in the file name is 2026-11-20. The sandbox clock (`date +%F`) also reads 2026-11-20, so no override was needed.
- Line numbers below were re-found by grep and by reading `backend/coaching/execution.py` and `scripts/evals/evaluate_retrieval.py` at `9d43fe6`. Test coverage is mapped from test names and greps, not from a coverage tool.

## Decision points before the refactor

### 1. `backend/coaching/execution.py`, all inside `_prepare_authoritative_turn` (starts at 2805)

Inputs available before the first decision: `attachment_ids` (2927), `selected_sources = list(snapshot.selected_sources)` (2952, attachments included, taken before any clearing), `image_inputs` and `unresolved_image_ids` from `image_inputs_for_sources` (3032-3041, this reads storage), `authoritative_stage`, `request.interaction_intent`, `frozen_history_revision` (parameter, 2810).

| # | Lines | Decision | `record_field` | Existing tests |
|---|---|---|---|---|
| 1 | 3055-3066 | `gate_started`, then `resolve_mode_policy(message, titles, filenames, has_selected_sources=bool(selected_sources))`. | none | `tests/domain/test_retrieval_gate.py`, `tests/domain/test_retrieval_gate_recall.py`, `tests/domain/test_mode_classification.py` (test the policy function, not this call site) |
| 2 | 3067-3076 | Lecture Help: policy becomes `high_confidence_source`, `qa`, `retrieve=True`. `elif interaction_intent == "project_coaching"`: `expected_mode="coaching"`. | none | `tests/http/test_lecture_help.py:20,49,90,154,174,216` |
| 3 | 3077-3095 | Current-stage status (`not lecture_help`): policy `qa`, `retrieve=False`. Snapshot sources, image sources, image inputs and unresolved ids are cleared. | `current_stage_status_request` (3095) | `tests/domain/test_mode_classification.py:1136,1847` |
| 4 | 3096-3128 | Thinking Path navigation. `progression_request` (3096-3102) is progression or terminal completion. `workflow_no_retrieve` (3103-3106) is meta-guidance. Both need `not lecture_help`. If `progression_request or (workflow_no_retrieve and not stage_status_request)`: policy `coaching`, `retrieve=False`, same clearing as #3. | `stage_progression_request` (3121), else `workflow_skips_retrieval` (3123) | `tests/domain/test_progression_effect.py:289,322,353` (mock turns, by name), `tests/domain/test_retrieval_gate.py:226` (policy level) |
| 5 | 3129-3173 | Attachment-only question (`is_private_attachment_question`, 3129). Runs even if #3 or #4 cleared the scope. Snapshot selected and retrieval sources, image sources, image inputs and unresolved ids are narrowed to the attachment ids. | none here | `tests/domain/test_mode_classification.py:430,450,457,470,1425`, `tests/domain/test_rag_fallback.py:307,357`, `tests/domain/test_course_library_chat_context.py:250`, `tests/domain/test_needs_sources.py:1045` |
| 6 | 3174-3190 | `effective_source_ids` frozen from `snapshot.selected_sources` (3174-3178). Then rows with unresolved image bytes are dropped from the snapshot (3179-3189). | none | covered through #5 and the request stamps (`source_ids`) in the tests above |
| 7 | 3191-3195 | `missing_image_qa`: some image source remains selected, every original selected source is an image, no image bytes resolved, and `looks_like_information_request`. | none | **none found.** `tests/http/test_api.py:552` and `tests/domain/test_mode_classification.py:1425` cover the resolved-image path only |
| 8 | 3196-3210 | `needs_retrieval = bool(mode_policy.retrieve)`. Set True by attachment-only (3201-3203), `missing_image_qa` (3204-3208), and `force_retrieval and selected_sources` (3209-3210). The force check reads the original `selected_sources`, so it holds even after #3 or #4 cleared the snapshot. | `attachment_retrieval_scoped` (3203) | attachment-only: same as #5. `force_retrieval`: **no direct test.** Deep Review reaches it from 1715 and 1947-1949, exercised by `tests/domain/test_deep_review_execution.py:344` and `tests/http/test_deep_review.py:110`, which do not assert scope |
| 9 | 3211-3227 | Course catalog retrieval. `include_course_catalog` needs `needs_retrieval`, and not attachment-only, status, progression, or `workflow_no_retrieve and not stage_status_request`. Then `lecture_help or _wants_course_catalog_retrieval(message, mode_retrieve=bool(mode_policy.retrieve) or force_retrieval)`. True forces `needs_retrieval = True`. | none here (`course_catalog_retrieval` is recorded later, 2668, inside `_hydrate_retrieval_sources`) | `tests/domain/test_course_library_chat_context.py:229,303,339,359,365,393`, `tests/domain/test_upload_retrieval_policy.py:329`, `tests/domain/test_needs_sources.py:724`, `tests/http/test_lecture_help.py:174` |
| 10 | 3228-3236 | `evidence_scoped` is the OR of `lecture_help`, `force_retrieval`, `stage_status_request`, `progression_request`, raw `workflow_no_retrieve` (not masked by status, unlike #4 and #9), `attachment_only_question`, `missing_image_qa`. | none | indirectly through `source_need_check` tests, `tests/domain/test_needs_sources.py:433` and `tests/domain/test_rag_fallback.py` |
| 11 | 3237-3264 | Laya / course-intent hook. Runs only when `self._course_intent_classifier is not None` (3237) and `local_course_intent_candidate(message, intent=mode_policy.intent, evidence_scoped=evidence_scoped or effective_source_ids or request.interaction_intent or frozen_history_revision is not None, searched=include_course_catalog)` (3237-3244). Then `source_check_course_titles(snapshot.visible_sources)` (3246), `classifier.score(message, store_history, titles)` (3249, model call), cutoff from settings, first-turn cutoff via `is_first_student_turn(store_history)` (3253-3257). On `score >= cutoff`: `include_course_catalog = needs_retrieval = True` and policy becomes `qa`, `retrieve=True` (3260-3261). | `local_course_intent_retrieval` (3262) | `tests/domain/test_needs_sources.py:201,248,275,291,351,368,383` |
| 12 | 3265-3277 | Upload retrieval policy: `_wants_student_upload_retrieval(enabled=settings.fast_chat_upload_retrieval_enabled, needs_retrieval, has_student_upload=bool(searchable_student_uploads(snapshot.selected_sources)), evidence_scoped, student_message)`. Uses the post-clear, post-narrowing snapshot. | `upload_retrieval_policy` (3277) | `tests/domain/test_upload_retrieval_policy.py:226,263,277,312,329,343,373,398,410` |
| 13 | 3278-3280 | Gate timing and final values. | `retrieval_gate_ms`, `retrieval_required`, `mode_policy_intent` | `tests/domain/test_coach_turn_perf.py:303` asserts only that `retrieval_gate_ms=` is in the TIMING blob |

Helper definitions the decisions call (all in `execution.py`): `_COURSE_CATALOG_RETRIEVAL_CUES` 172, `_wants_course_catalog_retrieval` 242, `_wants_source_need_check` 275, `searchable_student_uploads` 303, `is_chit_chat` 327, `local_course_intent_candidate` 342, `_wants_student_upload_retrieval` 354-391. Tests import these names from `backend.coaching.execution`: `tests/domain/test_course_library_chat_context.py:342,360`, `tests/domain/test_upload_retrieval_policy.py`, `tests/domain/test_needs_sources.py`.

### 2. State reads and `record_field` interleavings

Order of events, using today's line numbers.

1. Before the gate (not decision telemetry): `notebook_load_ms` 2834, `history_load_ms` 2878, `source_load_ms` 2905, `history_source_join_ms` 2915.
2. Reads feeding the decision: `selected_sources` 2952; image bytes 3032-3041 (storage I/O); `is_locked_course_source` (127 import, used in 321 and for authorization at 2983).
3. Telemetry inside the decision, in emission order: `current_stage_status_request` 3095, then `stage_progression_request` 3121 or `workflow_skips_retrieval` 3123, then `attachment_retrieval_scoped` 3203, then `local_course_intent_retrieval` 3262, then `upload_retrieval_policy` 3277, then `retrieval_gate_ms` 3278, `retrieval_required` 3279, `mode_policy_intent` 3280.
4. A model call and two settings reads sit between #4's telemetry and #12's: `classifier.score` 3249 (reads `store_history`), `local_course_intent_threshold` and `local_course_intent_first_turn_threshold` (3253-3254), then `fast_chat_upload_retrieval_enabled` (3267). A pure module cannot read these. They stay in `execution.py`.
5. After the gate, readers of the decision that stay in `execution.py`:
   - `_hydrate_retrieval_sources(include_course_catalog=...)` 3283-3310, which records `course_catalog_retrieval` and `course_catalog_source_count` (2668-2669) after `mode_policy_intent`.
   - Failure flips: 3299-3301 and 3350-3352 set `retrieval_required` False and `needs_retrieval` False and record `upload_retrieval_policy_failed`. The `retrieval_required` key is therefore written twice.
   - Post-hydration filters 3311-3325 (unresolved image ids, attachment narrowing).
   - Retrieval failure path 3365-3375: `image_only` from `image_inputs`, and `mode_policy.expected_mode != "qa"` at 3370. The plan did not list this reader.
   - `retrieval_total_ms`, `course_kb_retrieval_ms`, `student_source_retrieval_ms` 3375-3377; `retrieved_chunk_count`, `retrieved_context_chars`, `rag_used` 3378-3380.
   - `_wants_source_need_check(searched=needs_retrieval and retrieval_sources, evidence_scoped=evidence_scoped)` 3381-3385, `source_need_check` 3387, `source_check_title_count` 3393 (reads `fast_chat_needs_sources_enabled`).
   - `allow_model_knowledge = not effective_source_ids and not include_course_catalog` 3400.
   - Request stamps: `retrieval_required` 3454, `source_need_check` 3455, `expected_response_mode` (`"qa"` if `missing_image_qa` else `mode_policy.expected_mode`) 3457-3459, `mode_policy_intent` 3460, `source_ids` from `effective_source_ids`, `allow_model_knowledge` 3446.

Consumers of the same predicates outside first-pass scope. They stay where they are:
- `request.interaction_intent != "lecture_help"` guards: 818, 1060, 1952, 1962, 1981, 2090, 2432, 2436, 2439, 2504.
- Stage status and progression readers: 1953 (status), 2030-2032 (repeat move-on), 2149, 2242 (`is_stage_progression_request`). The plan cited "2020/2025" for the repeat move-on and did not list 2149 and 2242.
- `force_retrieval` producers: 1715 (frozen Deep Review) and 1947-1949 (`owned_review`).
- `_maybe_rag_fallback` starts at 2679. Its decision logic is 2705-2740 and it reads the request stamps `retrieved_chunks`, `source_need_check`, `retrieval_required`, `source_ids`, then calls `_hydrate_retrieval_sources(snapshot, include_course_catalog=source_need)` at 2729-2730.

### 3. `scripts/evals/evaluate_retrieval.py`

| Lines | What it re-implements | Existing tests |
|---|---|---|
| 579-594 | `GateDecision` fields (`retrieve`, `course`, `student`, `classifier_retrieve`, `second_chance`, `expected_mode`, `intent`, `needs_retrieval`, `scope_cleared`, `attachment_only`). The baseline JSON stores `dataclasses.asdict` of it. | `tests/scripts/test_evaluate_retrieval.py:1043,1114-1120` |
| 604-682 | `gate_decision`. `resolve_mode_policy` 630-635 (#1), `lecture_help` 636 from `row["explicit_mode"]` (#2), `status` 637 (#3), `progression` 638-640 and `workflow_no_retrieve` 641 (#4), `cleared` 642, `mode_retrieve` 643, `attachment_only` 644-646 (#5), `needs` 647, `personal` 648-653, `include_course` 654-659 (#9), `student` 660, `second_chance` 668-670 (mirrors `_wants_source_need_check`), `expected_mode` ladder 671-678. | 288, 502, 523, 697, 1043, 1071, 1086, 1114-1120, 1124 |
| 953-975 | `_eval_upload_entries`: projects selected and attached rows to source dicts, guessing `mime` from the filename. | 1062 |
| 1087-1215 | `_upload_retrieval_policy`: rebuilds #10 as `scope_cleared or attachment_only` (1121) and calls `_wants_student_upload_retrieval` with `enabled=True` (#12). Uses `[]` uploads when cleared (1115). | 1062-1073, 1097-1099 |
| 1954-2002 | `build_live_request`: rederives `source_ids` from `scope_cleared` and `attachment_only` (1978-1981) and stamps `allow_model_knowledge`, `retrieval_required`, `expected_response_mode`, `mode_policy_intent`. | 1114-1120, 1124 |
| 1229, 1327, 1357, 2288 | Call sites of `gate_decision` (gate, follow-ups, standalone rows, live model). | covered by the tests above |

Laya eligibility copies outside `evaluate_retrieval.py`, each calling `local_course_intent_candidate` imported from `backend.coaching.execution`:
- `scripts/evals/evaluate_combined_gate.py:144-157`
- `scripts/evals/evaluate_course_intent.py:34,64-71`
- `scripts/evals/evaluate_course_intent_learn.py:92,119-126`

All three use `evidence_scoped = scope_cleared or attachments or selected_sources` and `searched = decision.retrieve`. Tests: `tests/scripts/test_evaluate_combined_gate.py`, `tests/scripts/test_evaluate_course_intent_learn.py`, `tests/scripts/test_benchmark_course_intent.py`. None references `gate_decision` directly.

### 4. Corrections to the plan, and facts it did not state

1. **Line numbers hold.** Every range in plan section A matches HEAD. The brief's own link numbers (3048 and 3203) cannot be checked here, because the brief text available is truncated. The current numbers are the table above.
2. **Telemetry test claim is wrong.** Plan section D says telemetry names and order in `test_coach_turn_perf.py` must not change. That file only asserts `retrieval_gate_ms=` appears (line 303). No existing test asserts `current_stage_status_request`, `stage_progression_request`, `workflow_skips_retrieval`, `attachment_retrieval_scoped`, `local_course_intent_retrieval`, `upload_retrieval_policy`, `retrieval_required` or `mode_policy_intent`. The planned T3 is the only guard on telemetry order and must be written from the order in section 2 above (or from running the same cases on `9d43fe6`).
3. **Two decisions have no direct test:** missing image Q&A (#7) and `force_retrieval` (#8). T1 must cover both through the module. The refactor of `execution.py` itself is unguarded for them. A before/after capture of the request stamps and telemetry on `9d43fe6` is the fallback.
4. **Readers missed by the plan:** the retrieval failure path at 3365-3370 reads `mode_policy.expected_mode` and `image_inputs`; `evidence_scoped` is read again at 3384; `is_stage_progression_request` at 2149 and 2242. The repeat move-on guard is at 2030-2032, not 2020/2025.
5. **Eval Laya expressions differ from production in two places, not one.** Production passes `searched=include_course_catalog` (course catalog only) and an `evidence_scoped` that also ORs `request.interaction_intent`, post-clear `effective_source_ids` and `frozen_history_revision is not None`. The eval scripts pass `searched=decision.retrieve` (course or personal files) and the pre-clear row sources. The plan listed the `evidence_scoped` difference and not the `searched` difference. Plan test T6 (equal on all 295 rows) is the right check, and the three expressions must stay as they are.
6. **Eval treats every selected source as personal.** `gate_decision` has no locked-course concept (`student = needs and bool(personal)`, 660). Production excludes locked course rows from personal files in `_hydrate_retrieval_sources` (2655) and `searchable_student_uploads` (321). This is only safe while no dataset row has a locked course source, so the adapter should pass `is_course_library=False` and say so in a comment.
7. **Known eval/production divergences** (status plus progression ends in `qa` in the eval and `coaching` in production; raw versus final intent) are as in the plan, section B. I did not re-check the 649-row claim here.

### 5. What the refactor must not move

Authorization (2927-3000), image byte loading (3032-3041), the Laya model call and cutoffs (3246-3262), the upload setting read (3267), hydration and storage failure handling (3283-3352), and every reader listed in section 2 step 5 stay in `execution.py`. The new module takes plain inputs only.

## Item 1 result: first-pass evidence scope has one owner

No live command, no AWS, Bedrock, AgentCore, Knowledge Base or OpenAI call was run. No existing test was edited. No setting default changed. Nothing was pushed in this step.

### Commits (author and committer `CloudKai <kaiming_01@live.com>`, all local)

| SHA | Message |
|---|---|
| `754116a` | docs: draft evidence-scope report with verified decision points before refactor (before this step) |
| `3e18abe` | test: record first-pass evidence scope decisions before moving them (characterisation on the unchanged code) |
| `6c91e5c` | refactor: add evidence_scope, one pure owner for first-pass evidence scope |
| `26e6fed` | refactor: execution.py takes first-pass scope from evidence_scope |
| `dda9e34` | refactor: gate_decision is a thin adapter over evidence_scope (includes `gate-decisions-after.json`) |
| `94e8eed` | docs: describe the evidence_scope owner and the eval adapter |

### Decision points moved (line numbers)

Before = `backend/coaching/execution.py` at `9d43fe6`. After = `backend/coaching/evidence_scope.py` (new, 614 lines) at `94e8eed`. `execution.py` went from 3055-3280 for the whole gate to 2928-3052 (125 lines, mostly snapshot replacement and telemetry).

| # | Decision | Before (`execution.py`) | After (`evidence_scope.py`, `decide_first_pass_scope` starts 348) |
|---|---|---|---|
| 1 | `resolve_mode_policy` over titles and filenames | 3055-3066 | 382-390 |
| 2 | Lecture Help, Project Coaching | 3067-3076 | 391-407 |
| 3 | Current-stage status | 3077-3095 | 410-424 |
| 4 | Thinking Path progression, terminal completion, workflow guidance | 3096-3128 | 425-451 |
| 5 | Attachment-only question and narrowing | 3129-3173 | 453-465 |
| 6 | Effective source ids, unresolved image ids | 3174-3190 | 463-466 |
| 7 | Missing image Q&A | 3191-3195 | 467-473 |
| 8 | `needs_retrieval`, attachment, missing image, `force_retrieval` | 3196-3210 | 475-483 |
| 9 | Course catalog retrieval | 3211-3227 | 485-501 |
| 10 | `evidence_scoped` | 3228-3236 | 502-510 |
| 11 | Laya eligibility and promotion (the model call stays) | 3237-3264 | 511-528 (eligibility, promotion); model call at `execution.py` 3012-3032 |
| 12 | Upload retrieval policy | 3265-3277 | 529-546 |
| 13 | Final values, telemetry | 3278-3280 | `execution.py` 3050-3052; `ScopeDecision` built at 547-575 |

Helpers moved with their bodies unchanged (before in `execution.py`, after in `evidence_scope.py`): `_COURSE_CATALOG_RETRIEVAL_CUES` 172 to line 41; `_wants_course_catalog_retrieval` 242 to `wants_course_catalog_retrieval` 230 (now built on the new `course_catalog_cues` 210); `_wants_source_need_check` 275 to 253; `is_chit_chat` 327 to 281; `local_course_intent_candidate` 342 to 296; `_wants_student_upload_retrieval` 354 to 308. `searchable_student_uploads` stays in `execution.py` (it needs `is_locked_course_source`) and calls the module's `is_searchable_student_upload` (201). The old names stay importable from `execution.py` as aliases, so the existing tests import them unchanged.

Eval side (`scripts/evals/evaluate_retrieval.py`): `gate_decision` 604-682 (80 lines of precedence code) is now `scope_inputs_for_row` 598 and a 20-line `gate_decision` 653 that maps the module result to the unchanged `GateDecision`. `_upload_retrieval_policy` (now 1085) asks the module with the setting on instead of rebuilding `evidence_scoped`. The three Laya eval scripts import `local_course_intent_candidate` from `evidence_scope`.

### State reads and telemetry cases

Kept in `execution.py` and passed in or applied after the module call:

1. Image bytes (`image_inputs_for_sources`, storage I/O) become `ScopeSource.image_bytes_resolved`.
2. `is_locked_course_source` becomes `ScopeSource.is_course_library`. It is now evaluated for every selected source at the start of the gate. It is a pure dict read.
3. The Laya model call, course titles, cutoffs, `is_first_student_turn`. The module returns `course_intent_eligible`; the caller scores; a second call with `course_intent_promoted=True` applies the promotion before the upload rule, as before.
4. `runtime_settings.fast_chat_upload_retrieval_enabled`. It was read after the model call. It is now read when building the inputs and read again after the model call; the scope is decided a second time only if the promotion fired or the value changed. It differs from the old behaviour only if something changes the setting during the model call.
5. Snapshot replacement (clear, attachment narrowing, unresolved-row drop), hydration, the failure flips that set `retrieval_required` back to False, `source_need_check` after hydration, `allow_model_knowledge`, request stamps, and the retrieval failure path (`mode_policy.expected_mode`, `image_inputs`) stay as they were.

Telemetry: the module returns data only. `execution.py` records `current_stage_status_request`, `stage_progression_request` or `workflow_skips_retrieval`, and `attachment_retrieval_scoped` before the model call, then `local_course_intent_retrieval` and `upload_retrieval_policy` after it, then `retrieval_gate_ms`, `retrieval_required`, `mode_policy_intent`. Order and values are unchanged; `tests/domain/test_evidence_scope_turn.py` pins the call order for 38 scenarios (recorded on the old code in `3e18abe`). No case was found where the order could not be kept.

New finding on telemetry: `current_stage_status_request`, `stage_progression_request`, `workflow_skips_retrieval` and `attachment_retrieval_scoped` are not in `SAFE_PERF_FIELDS` (`backend/turn_perf.py`). `CoachTurnPerf.set` drops them and logs `turn_perf_rejected_field` at WARNING. The calls were kept so the warnings stay. Whether those four names should be allow-listed is a separate decision, not made here.

### Differences between the old eval mirror and the module (none changes a number)

1. Status and progression together: old eval mode `qa`, module (as production) `coaching`. No natural message triggers both predicates, so no row of the 5652-row cross product moved. The matrix test covers it with patched predicates.
2. `second_chance` is now `wants_source_need_check(enabled=True, searched, evidence_scoped)`. It equals the old expression on every row.
3. `UPLOAD_POLICY_DEFINITION` (a string written to the JSON) still names `_wants_student_upload_retrieval`. I did not edit it because that would change the output JSON; the alias still exists in `execution.py`.
4. Not changed, left as a residual duplicate: `build_live_request` derives `source_ids` from `scope_cleared` and `attachment_only` of a `GateDecision`. `evaluate_laya_turn_decisions.scope_name` and the dump script keep their own scope-label helper (`scope_label` now exists in the module). The three Laya eval scripts keep their `evidence_scoped` and `searched` approximations; test T6 shows they equal the module on all 295 rows (147 eligible).

### Verification

| Check | Result |
|---|---|
| `diff gate-decisions-before.json gate-decisions-after.json` (same `dump_gate_decisions.py` command, recorded in `commands.md`) | empty, exit 0, also `cmp` identical |
| Legacy `gate_decision` cross product, 5652 rows (every gate and follow-up message, plus 7 compound ones, times 3 explicit modes, 2 attachment states, 3 source states) | identical to the capture made on the old code |
| `run_offline_evals.sh` after-capture vs baseline (`diff_outputs.py`) | 41 comparisons, 0 differing, exit 0; log `.agents/tasks/refactor-evidence-scope/item1-offline-diff.txt` |
| `evaluate_retrieval` JSON and stdout vs baseline | equal apart from `run.git_sha`, `git_dirty`, `generated_at_utc` |
| Numbers | wrong-skip 76/154 (49.4%), clear rows 51/113, classifier only 85/154, false-retrieve 7/141 (5.0%), recall@4 material 91/94, page 78/94, follow-ups 8/9 and 0/3: all unchanged |
| `ruff check .` | pass |
| Full mock suite | 2876 passed, 2 failed, 1 skipped (baseline 2753 passed, 2 failed, 1 skipped). The 123 extra passes are the new tests: 79 (`test_evidence_scope.py`), 38 (`test_evidence_scope_turn.py`), 6 (`test_gate_scope_equivalence.py`). The 2 failures are the known `tests/http/test_notebook_reader.py` ones (no `frontend/dist`). |
| Production-path tests (`test_needs_sources`, `test_rag_fallback`, `test_upload_retrieval_policy`, `test_course_library_chat_context`, `test_mode_classification`, `test_progression_effect`, `test_retrieval_gate`, `test_coach_turn_perf`) | pass, none edited |
| Mutation check | flipping the workflow-not-status mask in the module failed the matrix and four turn scenarios |

### Risks

- The turn scenarios in `3e18abe` pin behaviour for `force_retrieval` and missing image Q&A, which had no direct test. Deep Review frozen-history turns (`frozen_history`) are covered in the matrix only, not at turn level.
- One transient failure of `tests/domain/test_deep_review_execution.py::test_deep_review_started_in_cg_ignores_later_stage_advance` in one combined domain and scripts run on `26e6fed`. It passed alone four times, in five further domain runs, and in the full suite. It uses a background Deep Review worker. I did not find a link to this change, and I did not run it on the old commit to confirm it is flaky there.
- The setting is read twice per turn now (see state read 4).
- The ten-step precedence now sits in one 230-line function. The matrix and turn tests are the guard; a later rule change must update both.
