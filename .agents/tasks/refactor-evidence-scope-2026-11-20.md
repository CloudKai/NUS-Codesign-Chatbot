# Refactor report (draft): one owner for first-pass evidence scope

Status: draft, written before any code change. Item 1 and item 2 results are appended below as they finish.

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
