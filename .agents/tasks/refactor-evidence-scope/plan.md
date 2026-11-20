# Implementation Plan: evidence-scope owner and eval-command decoupling

Repo `NUS-Codesign-Chatbot`, branch `improvement/backend`, HEAD `9d43fe6` (baseline commit, on top of `4fb7c92`). Clean tree.
Decomposition: not restructured. The brief already splits the work into item 1 (push, verify, stop-gate) and item 2, and item 2 must wait for item 1 to be pushed. The existing implement/review loop follows that split.

Test env for every command below (repo root):
```sh
export MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false AUTO_ADVANCE_STAGES=false APP_ENV=development
PY=/projects/sandbox/.venvs/nus-codesign-py312/bin/python
```
Commits: `git -c user.name=CloudKai -c user.email=kaiming_01@live.com commit`, no co-author text, push to `improvement/backend` (no PR, no force). Report: `.agents/tasks/refactor-evidence-scope-2026-11-20.md`, `git add -f`, repo-relative paths only.

## A. Decision points in `backend/coaching/execution.py` (`_prepare_authoritative_turn`, line numbers at 9d43fe6)

Method starts 2805. Everything between 3055 and 3279 is the first-pass scope and mode decision.

| # | Lines | Decision | Inputs it reads | Telemetry emitted (`record_field`) |
|---|---|---|---|---|
| 1 | 3055-3066 | `resolve_mode_policy(message, titles, filenames, has_selected_sources=bool(selected_sources))`. `selected_sources` (2952) includes attachments, taken BEFORE any clearing | message, source titles/`filename or name` | none |
| 2 | 3067-3076 | Lecture Help (`interaction_intent=="lecture_help"`): policy becomes `high_confidence_source / qa / retrieve=True`. `elif project_coaching`: `expected_mode="coaching"` | `request.interaction_intent` | none |
| 3 | 3077-3095 | Current-stage status (`not lecture_help and is_current_stage_status_request`): policy `qa, retrieve=False`; snapshot selected/retrieval sources, image sources, image inputs, unresolved ids all cleared | message | `current_stage_status_request=True` (3095) |
| 4 | 3096-3128 | Thinking Path navigation: `progression_request` (progression or terminal completion), `workflow_no_retrieve` (meta-guidance). Both gated by `not lecture_help`; workflow branch also `not stage_status_request`. Policy `coaching, retrieve=False`; same clearing as #3 | message, `authoritative_stage` | `stage_progression_request` (3121) or, `elif`, `workflow_skips_retrieval` (3123). Never both |
| 5 | 3129-3173 | Attachment-only question (`is_private_attachment_question`, runs even if #3/#4 cleared): snapshot selected/retrieval sources narrowed to attachment ids; images and image inputs narrowed; `unresolved_image_ids` recomputed | message, `len(attachment_ids)`, attachment id set | none here |
| 6 | 3174-3190 | `effective_source_ids` frozen (post-scope, pre unresolved-image removal); unresolved image rows then dropped from `snapshot.selected_sources` | snapshot | none |
| 7 | 3191-3195 | Missing image Q&A: `selected_image_sources` non-empty AND `len(selected_image_sources)==len(selected_sources)` (ORIGINAL list) AND no resolved image inputs AND `looks_like_information_request` | image bytes resolved flags | none |
| 8 | 3196-3210 | `needs_retrieval = bool(mode_policy.retrieve)`; `attachment_only` sets True; `missing_image_qa` sets True; `force_retrieval and selected_sources` (ORIGINAL list, so it applies even after clearing) sets True | `force_retrieval` arg | `attachment_retrieval_scoped=True` (3203), only when #5 fired |
| 9 | 3211-3227 | Course catalog: `needs_retrieval and not attachment_only and not status and not progression and not workflow_no_retrieve(not status) and (lecture_help or _wants_course_catalog_retrieval(msg, mode_retrieve=bool(mode_policy.retrieve) or force_retrieval))`; then `needs_retrieval=True` | message | none (`course_catalog_retrieval` is recorded later in `_hydrate_retrieval_sources`, stays) |
| 10 | 3228-3236 | `evidence_scoped = lecture_help or force_retrieval or status or progression or workflow_no_retrieve or attachment_only or missing_image_qa` | | none |
| 11 | 3237-3264 | Laya / course-intent hook: `classifier is not None and local_course_intent_candidate(msg, intent=mode_policy.intent, evidence_scoped=evidence_scoped or effective_source_ids or request.interaction_intent or frozen_history_revision is not None, searched=include_course_catalog)`; then titles, model `score`, cutoff compare (settings, `is_first_student_turn(store_history)`); on pass: catalog True, needs_retrieval True, policy `qa, retrieve=True` | message, store history, settings, visible-source titles, model | `local_course_intent_retrieval=True` (3262) |
| 12 | 3265-3277 | Upload retrieval policy: `_wants_student_upload_retrieval(enabled=settings flag, needs_retrieval, has_student_upload=bool(searchable_student_uploads(snapshot.selected_sources)), evidence_scoped, message)`; sets `needs_retrieval=True` | settings flag (read after the model call), snapshot | `upload_retrieval_policy=True` (3277) |
| 13 | 3278-3280 | Gate timing and final values | `gate_started` (3055) | `retrieval_gate_ms`, `retrieval_required=bool(needs_retrieval)`, `mode_policy_intent=mode_policy.intent` |

Emission order today: status, progression|workflow, attachment_retrieval_scoped, local_course_intent_retrieval, upload_retrieval_policy, retrieval_gate_ms, retrieval_required, mode_policy_intent. `record_field` writes into a dict (`backend/turn_perf.py:248`, `payload = dict(self.fields)`), so insertion order is the emitted JSON key order. `backend/course_intent.py` records no telemetry, so moving the writes after the model call changes nothing observable.

Downstream readers of the decision (stay in `execution.py`, read the module's result): hydration `include_course_catalog` (3283-3310), post-hydration filters for unresolved images and attachment-only (3311-3325), `source_need_check = _wants_source_need_check(enabled, searched=bool(needs_retrieval and retrieval_sources), evidence_scoped)` (3381), `allow_model_knowledge = not effective_source_ids and not include_course_catalog` (3400), request stamps `retrieval_required`, `expected_response_mode = "qa" if missing_image_qa else mode_policy.expected_mode`, `mode_policy_intent` (3454-3460).

Sibling code that re-uses the same predicates but is NOT first-pass scope. Leave in place, list in the report as "not moved": 818 (exact confirm), 1060 (manual stage selection), 1950-1962 and 1981 (`stage_status_request` again, pending-ready reminder), 2020 and 2025 (status short-circuit), 2090, 2432-2439 and 2504 (Lecture Help persistence flags), 2705-2790 (`_maybe_rag_fallback`, second chance), callers that pass `force_retrieval`: 1715 (Deep Review job) and 1947 (`owned_review`).

Pre-existing helpers that currently live in `execution.py` and belong to this decision: `_COURSE_CATALOG_RETRIEVAL_CUES` (172), `_wants_course_catalog_retrieval` (242), `_wants_source_need_check` (275), `searchable_student_uploads` (303), `is_chit_chat` (327), `local_course_intent_candidate` (342), `_wants_student_upload_retrieval` (354).

## B. Decision points in `scripts/evals/evaluate_retrieval.py` (the second copy)

- `GateDecision` (580-594) and `gate_decision(row)` (604-682). It re-implements #1, #2, #3, #4, #5, #8 (partly), #9, and `_wants_source_need_check` (`second_chance`, 666-670), and the expected-mode ladder (671-678).
- `_upload_retrieval_policy` (1087-1215, `evidence_scoped=bool(scope_cleared or attachment_only)` at about 1117) re-composes #10 and #12 (it already calls the shared `_wants_student_upload_retrieval`).
- `build_live_request` (1954-2002) re-derives `source_ids` from `scope_cleared` / `attachment_only` (the `_prepare_authoritative_turn` stamps).
- `evaluate_combined_gate.py:144-157`, `evaluate_course_intent.py:62-72`, `evaluate_course_intent_learn.py:117-125` each rebuild #11's `evidence_scoped` as `scope_cleared or attachments or selected_sources` and `searched=decision.retrieve`.
- Callers of `gate_decision`/`GateDecision`: evaluate_retrieval (1229, 1327, 1357, 2288), evaluate_course_intent, evaluate_course_intent_learn, evaluate_combined_gate, benchmark_agentcore_vs_converse (709), compare_turn_routes (190, 296, 342), baseline helpers `dump_gate_decisions.py`, `stub_snapshots.py`, historical `phase3d-work/sol-teacher/run.py`.

Differences between the eval mirror and production that the module resolves toward production. None changes a number on the shipped data. I checked all 649 rows (295 gate, 12 follow-up, routing splits): no row has status+progression, status+attachment, or progression+attachment, and only 1 Lecture Help and 1 Project Coaching row.
1. status AND progression both true: production ends in `coaching` (progression block runs after status), eval says `qa`. No data row has both.
2. Eval `intent` is the RAW `resolve_mode_policy` intent (Lecture Help does not overwrite it); production telemetry uses the FINAL intent. The module returns both.
3. Eval `classifier_retrieve` is the raw `policy.retrieve` before overrides. The module returns the raw value too.
4. Eval treats every file as personal and never reads image bytes; `missing_image_qa`, `force_retrieval`, and the Laya model are not modelled. They stay explicit inputs at their current assumed values (see C).

## C. Module interface: `backend/coaching/evidence_scope.py`

Imports allowed: stdlib, `backend.coaching.mode_policy`, `backend.coaching.workflow_navigation`, `backend.retrieval_gate`, `backend.specialists.routing`, `backend.retrieval` (`is_greeting_or_acknowledgement`). Verified at 9d43fe6: importing `backend.coaching.mode_policy` in a fresh interpreter loads no `boto3`, `botocore`, `backend.persistence*`, `backend.student_store`, `backend.sources*`, `backend.source_library`, `backend.providers`, `backend.settings`. `backend.sources.library` (home of `is_locked_course_source`) pulls in `student_store` and persistence, so the module must NOT import it: the caller computes the locked-course flag.

```python
@dataclass(frozen=True)
class ScopeSource:
    source_id: str
    title: str = ""
    filename: str = ""            # execution: str(s.get("filename") or s.get("name") or "")
    is_attachment: bool = False   # id in request.attachment_source_ids
    is_course_library: bool = False   # execution: is_locked_course_source(s)
    is_image: bool = False        # kind == "image" or mime startswith "image/"
    image_bytes_resolved: bool = True # image_inputs_for_sources returned it

@dataclass(frozen=True)
class ScopeInputs:
    message: str
    current_stage: str            # authoritative_stage
    sources: tuple[ScopeSource, ...]   # snapshot.selected_sources BEFORE clearing (attachments included)
    attachment_count: int         # len(attachment_ids)
    interaction_intent: str | None    # "lecture_help" | "project_coaching" | None
    force_retrieval: bool
    frozen_history: bool          # frozen_history_revision is not None
    upload_retrieval_enabled: bool    # runtime_settings.fast_chat_upload_retrieval_enabled

@dataclass(frozen=True)
class ScopeDecision:
    mode_policy: ModePolicy       # FINAL policy (after Lecture Help, clears, Laya promotion)
    classifier_retrieve: bool     # RAW resolve_mode_policy retrieve (eval needs it)
    classifier_intent: str        # RAW intent (eval GateDecision.intent)
    expected_mode: str            # "qa" if missing_image_qa else mode_policy.expected_mode (request stamp)
    needs_retrieval: bool
    include_course_catalog: bool
    scope_cleared: bool           # status or progression or workflow-no-retrieve
    attachment_only: bool
    missing_image_qa: bool
    evidence_scoped: bool
    kept_source_ids: tuple[str, ...]      # == execution's effective_source_ids
    unresolved_image_ids: frozenset[str]
    searches_personal_files: bool         # needs_retrieval and a kept, resolved, non-course source exists
    upload_policy_only: bool
    course_intent_eligible: bool          # == local_course_intent_candidate(...); caller still needs a classifier
    course_intent_promoted: bool
    second_chance: bool                   # wants_source_need_check(enabled=True, searched=catalog or personal, evidence_scoped)
    cues: tuple[str, ...]                 # ordered; includes "lecture_help", "project_coaching", "force_retrieval",
                                          # "current_stage_status_request", "stage_progression_request" | "workflow_skips_retrieval",
                                          # "attachment_retrieval_scoped", "missing_image_qa", "course_catalog:<cue>",
                                          # "local_course_intent_retrieval", "upload_retrieval_policy"
TELEMETRY_CUES: frozenset[str]    # the five that execution records via record_field(name, True)

def decide_first_pass_scope(inputs: ScopeInputs, *, course_intent_promoted: bool = False) -> ScopeDecision
```
Also move, unchanged in body: `_COURSE_CATALOG_RETRIEVAL_CUES`, `wants_course_catalog_retrieval`, `wants_source_need_check`, `is_chit_chat`, `local_course_intent_candidate`, `wants_student_upload_retrieval`, plus `is_searchable_student_upload(is_course_library, is_image)` predicate. `execution.py` keeps its old names as re-exports (`_wants_course_catalog_retrieval = wants_course_catalog_retrieval`, etc.) and keeps `searchable_student_uploads(sources)` as a thin wrapper that builds flags with `is_locked_course_source` and calls the module predicate. `_wants_course_catalog_retrieval` gets a sibling `course_catalog_cues(message) -> tuple[str, ...]` (returns `("course_question",)` when `looks_like_course_question`, else the intersection of classifier cues with the catalog set when `classification.retrieve`); `wants_course_catalog_retrieval = mode_retrieve and bool(cues)`, so the boolean is byte-identical.

Two-call protocol (keeps the model call out of the module): execution calls `decide_first_pass_scope(inputs)`. If `classifier is not None and d.course_intent_eligible`, it does the existing titles check, model `score`, and cutoff compare (all stay in execution), and on pass calls `decide_first_pass_scope(inputs, course_intent_promoted=True)`, which applies the promotion (catalog True, needs_retrieval True, policy `qa/retrieve=True`) BEFORE the upload-policy rule, like today. Read `runtime_settings.fast_chat_upload_retrieval_enabled` immediately before each call.

Eval adapter (`gate_decision(row)` in `evaluate_retrieval.py`): build `ScopeInputs` from the row. `sources` = selected (ids `eval-source-N`) then attachments (`eval-attachment-N`, `is_attachment=True`); title/filename from the row; `is_image` from `mimetypes.guess_type(filename)` (same guess as `_eval_upload_entries`), `image_bytes_resolved=True`, `is_course_library=False`; `attachment_count=len(attachments)`; `interaction_intent=row.get("explicit_mode")`; `force_retrieval=False`; `frozen_history=False`; `upload_retrieval_enabled=False` (`_upload_retrieval_policy` applies that rule separately). Each assumed value gets a one-line comment ("eval cannot supply: image bytes / force_retrieval / model second chance; kept at the value the pre-refactor gate assumed"). Map to `GateDecision` with the SAME fields and values: `retrieve = include_course_catalog or searches_personal_files`, `course = include_course_catalog`, `student = searches_personal_files`, `classifier_retrieve`, `second_chance`, `expected_mode`, `intent = classifier_intent`, `needs_retrieval = needs_retrieval or include_course_catalog`, `scope_cleared`, `attachment_only`. Do NOT add fields to `GateDecision`: the baseline JSON stores `dataclasses.asdict(decision)`.

Eval expected_mode ladder to reproduce through the module (production order): policy mode; Lecture Help forces `qa`; `project_coaching` forces `coaching`; status forces `qa`; progression or workflow (not status) forces `coaching`.

### State the pure function cannot see (kept in execution.py and passed in, or applied after)
1. Image bytes: `image_inputs_for_sources(...)` (3032) runs before scoping and does I/O. Passed as `ScopeSource.image_bytes_resolved`. The module narrows images itself (clear / attachment-only), then derives `missing_image_qa` and `unresolved_image_ids`.
2. `is_locked_course_source(s)` (imports the store): passed as `is_course_library`.
3. Laya: `self._course_intent_classifier`, `source_check_course_titles(snapshot.visible_sources)`, `score(...)`, `runtime_settings` cutoffs, `is_first_student_turn(store_history)`. Stay in execution; the result enters as `course_intent_promoted`.
4. `runtime_settings.fast_chat_upload_retrieval_enabled`: read mid-method after the model call; passed as `upload_retrieval_enabled` read right before each call.
5. `retrieval_sources` after hydration (storage): used by `source_need_check` (3381) and the failure paths (3283-3300, 3346-3352) that flip `needs_retrieval`/`retrieval_required` back to False and emit `upload_retrieval_policy_failed`. Stay in execution (`wants_source_need_check` itself moves).
6. `TurnSnapshot` replacement (`replace(snapshot, selected_sources=(), retrieval_sources=())`, attachment narrowing, unresolved-row drop): stays in execution, driven by `scope_cleared`, `attachment_only`, `unresolved_image_ids`, in the same order as today. Image max-5 check and `CoachImageInput.model_validate` stay.
7. `gate_started`/`retrieval_gate_ms`: stay.

### Telemetry-ordering rule
Execution records, in this order: after the first `decide` call, the cues of `d1` that are in `TELEMETRY_CUES` and precede Laya (`current_stage_status_request`, `stage_progression_request`|`workflow_skips_retrieval`, `attachment_retrieval_scoped`); after the Laya step, `local_course_intent_retrieval` if promoted; then `upload_retrieval_policy` if the final decision has `upload_policy_only`; then `retrieval_gate_ms`, `retrieval_required`, `mode_policy_intent` exactly as now. Test it with a perf accumulator (see test T3). Not possible to keep unchanged: nothing found. If the status/progression writes cannot come before the model call because a later edit moves them, stop and report.

## D. Existing-test constraints (stop-and-report if any must change)

Item 1:
- `tests/domain/test_course_library_chat_context.py:341-362`, `test_upload_retrieval_policy.py:19-21,235-252`, `test_needs_sources.py:30,435` import `_COURSE_CATALOG_RETRIEVAL_CUES`, `_wants_course_catalog_retrieval`, `_wants_student_upload_retrieval`, `is_chit_chat`, `searchable_student_uploads`, `_wants_source_need_check` FROM `backend.coaching.execution`. Keep those names importable there (re-exports). Also `backend/coaching/execution.py` is imported by eval scripts (`local_course_intent_candidate`, `source_check_course_titles`).
- Telemetry names in `tests/domain/test_coach_turn_perf.py`: unchanged values and order.
- `tests/scripts/test_evaluate_retrieval.py` loads the script by path (`spec_from_file_location("co_design_evaluate_retrieval")`) and reads `GateDecision` fields at 288, 502, 523, 697, 1071, 1086, 1114-1120. Fields and values must be identical.
- Baseline at 9d43fe6: focused set `test_needs_sources`, `test_upload_retrieval_policy`, `test_course_library_chat_context`, `test_rag_fallback` and `tests/scripts` = 398 passed. Full suite = 2753 passed, 2 failed (`tests/http/test_notebook_reader.py`, no `frontend/dist`), 1 skipped.

Item 2 (patch seams that depend on where a function lives):
- `tests/scripts/test_evaluate_retrieval.py` patches on the loaded module: `_block_network`, `_build_live_client`, `_build_bedrock_runtime_client`, `run_live`, `run_live_model`, `run_offline`, `format_report`, `_git_run_metadata`, `live_model_settings`. Whatever calls them (`main`, `_write_json_output`, `check_live_model_request`, `run_live_model*`) must still resolve them through `evaluate_retrieval`'s own globals. Pattern: keep a thin wrapper in `evaluate_retrieval` that passes the looked-up callable into the shared lib function (`write_json_output(path, result, run=_git_run_metadata())`).
- `tests/scripts/test_benchmark_agentcore_vs_converse.py:204,426` use `bench.retrieval.LiveCallLimitExceeded` and patch `bench.retrieval._git_run_metadata`. Keep a module attribute `retrieval` in `benchmark_agentcore_vs_converse.py` that points at the shared lib module (`from scripts.evals.lib import offline as retrieval` style, not the command), and move exception classes so the class object is identical (re-export from `evaluate_retrieval`).
- STOP-AND-REPORT 1: `tests/scripts/test_evaluate_combined_gate.py:321` patches `retrieval._block_network` (the evaluate_retrieval module) to stub the call made inside `evaluate_combined_gate.main`. STOP-AND-REPORT 2: `tests/scripts/test_benchmark_course_intent.py:20` does the same for `benchmark_course_intent.main`. After decoupling, those mains call the lib function, so the patch no longer reaches them and the real `_block_network` would disable sockets for the whole pytest process. No compatible shim exists (a patched attribute on module A cannot affect a call made through module B). Do the other commits first. At commit C7 do not edit those tests; call `send_message` severity `warning` with the two line numbers and the one-line change (patch target `scripts.evals.lib.offline.block_network`) and wait for the user.
- `tests/scripts/test_evaluate_course_intent_learn.py` patches `backend.course_intent.load_vega_reader` and a stub `laya` in `sys.modules`; `tests/scripts/test_compare_turn_routes.py` uses `routes.{inputs,state,observe,apply}` and `passages.coverage`; `test_evaluate_combined_gate.py` uses `combined.{compose,summarize,rate_ci,wilson_interval,PreparedRow,format_ci,STORED_ORIGIN,RERUN_ORIGIN,probe_laya_runtime,LayaSource,STUB_NAMES,rerun_source,prepare_rows,main,load_stored_multilingual,load_stored_learn,evaluate_source,CostModel}`; `test_benchmark_course_intent.py` uses `bench.{percentile,main,score_rows,memory_snapshot,latency_summary,json}`; `test_benchmark_agentcore_vs_converse.py` uses `bench.{main,BudgetedClient,CallBudget,BenchmarkRefused,load_turns,turns_for_limit,TURN_IDS_SHA,select_benchmark_turns,run_benchmark,check_call_limit,CALLS_PER_TURN,_settings_for_run,build_clients,json}`. All must stay reachable under the same names (compatible re-exports).
- Non-test importers that must keep working: `.agents/tasks/refactor-baseline/dump_gate_decisions.py` (`retrieval.load_*`, `gate_decision`, `*_PATH`), `stub_snapshots.py` (`routes`, `learn`, `base`, `passages`, `retrieval`; only its import lines may change), `phase3d-work/sol-teacher/run.py` (historical, leave).

## E. Item 1 plan (ordered; one commit each unless stated)

- [ ] 1. Characterise before touching code. Add `tests/domain/test_evidence_scope.py` skeleton later; first write a throw-away script `.agents/tasks/refactor-evidence-scope/legacy_gate_snapshot.py` that records, from the CURRENT `gate_decision`, `GateDecision` for the 649 shipped rows plus a cross product (message set from datasets x `explicit_mode` in {None, lecture_help, project_coaching} x attachments {0,1} x selected {0,1}) to `.agents/tasks/refactor-evidence-scope/legacy-cross-product.json`. It lets step 4 prove or list every difference between old eval mirror and new module.
      Files: `.agents/tasks/refactor-evidence-scope/legacy_gate_snapshot.py`, `legacy-cross-product.json`.
      Verify: run it twice with `$PY`, `cmp` the two outputs (byte-identical).
- [ ] 2. Create `backend/coaching/evidence_scope.py` (section C) containing the moved helpers and `decide_first_pass_scope`, written by transcribing the logic of execution.py 3055-3277 in order (#1 to #12). No callers yet. Add `tests/domain/test_evidence_scope.py` (T1 matrix, T2 import walk, T4 module-level unit tests of moved helpers).
      Verify: `$PY -m pytest -p no:cacheprovider tests/domain/test_evidence_scope.py` passes; `ruff check backend tests` clean.
- [ ] 3. Wire `execution.py`: build `ScopeInputs` after `image_inputs` is resolved (replace 3055-3277), call the module with the two-call protocol, apply snapshot replacements in the existing order, record telemetry per the ordering rule, delete the moved helpers and keep re-exports (section D). Keep `searchable_student_uploads`.
      Files: `backend/coaching/execution.py`.
      Verify: `$PY -m pytest -p no:cacheprovider tests/domain` all pass unchanged (explicitly `test_needs_sources.py test_rag_fallback.py test_upload_retrieval_policy.py test_course_library_chat_context.py test_coach_turn_perf.py test_mode_classification.py test_progression_effect.py test_retrieval_gate.py`). Add T3 (telemetry order) in `tests/domain/test_evidence_scope.py` using a `begin_coach_turn_perf` accumulator and the turn-level fixtures from `test_upload_retrieval_policy.py`; compare `list(perf.fields)` for each cue path against the order captured from the pre-change code (generate the expected lists by running the same test on the 9d43fe6 checkout first via `git stash`-free `git worktree`, or hard-code the order from section A).
- [ ] 4. Adapter in `scripts/evals/evaluate_retrieval.py`: replace the body of `gate_decision` with the section C adapter; delete the duplicated precedence code; change `_upload_retrieval_policy` to call the module (`decide_first_pass_scope` with `upload_retrieval_enabled=True`, or, if any digit moves, keep calling the shared `wants_student_upload_retrieval` with `evidence_scoped=scope_cleared or attachment_only` and add a comment). Import `local_course_intent_candidate` from the module in `evaluate_course_intent.py`, `evaluate_course_intent_learn.py`, `evaluate_combined_gate.py` (the three `evidence_scoped` expressions stay as eval approximations; T5 asserts they equal the module's `course_intent_eligible` on the 295 rows). Add `tests/scripts/test_gate_scope_equivalence.py` (T5, T6).
      Verify: `$PY -m pytest -p no:cacheprovider tests/scripts tests/domain/test_evidence_scope.py`; then `$PY .agents/tasks/refactor-baseline/dump_gate_decisions.py /tmp/refactor-out/gate-decisions-after.json && cmp .agents/tasks/refactor-baseline/gate-decisions-before.json /tmp/refactor-out/gate-decisions-after.json` (must print nothing); run the step-1 script again and diff against `legacy-cross-product.json`: every difference is recorded in the report (expected: only status+progression mode, and only on synthetic rows). If a shipped row differs, STOP and report.
- [ ] 5. Docs: `backend/AGENTS.md` module table row for `coaching/evidence_scope.py`; `docs/RAG_ARCHITECTURE.md` paths for `_COURSE_CATALOG_RETRIEVAL_CUES` and `_wants_student_upload_retrieval` (now in `backend/coaching/evidence_scope.py`); `docs/RETRIEVAL_EVAL.md` and `scripts/evals/evaluate_retrieval.py` docstrings that say the gate "mirrors" execution.py; short `docs/IMPLEMENTATION_STATUS.md` entry. Verify: grep'd names resolve to real symbols (`$PY -c "import backend.coaching.evidence_scope"`), links intact.
- [ ] 6. Item-1 gate: full verification, push, stop-gate. `ruff check .` (baseline: passes); full suite (`$PY -m pytest -p no:cacheprovider`, expected 2753 + new tests passed, same 2 failures, 1 skipped); `sh .agents/tasks/refactor-baseline/run_offline_evals.sh /tmp/refactor-out after` then `$PY .agents/tasks/refactor-baseline/diff_outputs.py .agents/tasks/refactor-baseline /tmp/refactor-out before after` (exit 0); confirm wrong-skip 76/154, false-retrieve 7/141, recall@4 91/94, follow-ups 8/9 and 0/3 in `evaluate_retrieval.after.stdout.txt`. Copy `gate-decisions-after.json` to `.agents/tasks/refactor-baseline/` and commit it. `git push origin improvement/backend`. Write the item-1 section of the report. Item 2 starts only after this succeeds.

### Tests to add (item 1)
- T1 `tests/domain/test_evidence_scope.py::test_conflict_matrix`: parametrised through `decide_first_pass_scope` only. Phrases come from dataset rows (`scripts/evals/datasets/retrieval_gate_messages.synthetic.jsonl` categories `attachment_question`, `upload_question`, `stage_navigation`, `stage_meta_guidance`, `mixed_project_and_course`, `course_content`) and `tests/domain/test_mode_classification.py`. Pairs: Lecture Help x each of status/progression/workflow/attachment (Lecture Help wins, nothing cleared); Project Coaching x status/progression/course question; status x workflow, progression x workflow (telemetry cue only for the first); cleared x attachment-only (needs_retrieval True, no kept sources, no personal search, both cues); attachment-only x course question (no catalog, kept = attachments only, course image dropped); attachment-only x missing image; missing-image Q&A x information request / non-request / mixed with a text source; force_retrieval x (sources, no sources, cleared, course cue); course-cue x (no sources, upload selected = "upload plus no sources"); upload policy x (gate retrieve, no uploads, only course-library rows, only images, cleared, attachment-only, chit-chat, policy off); Laya eligible x (selected sources, interaction intent, frozen history, chit-chat, non-ambiguous intent), promoted -> `qa`, retrieve, catalog, upload rule off; `wants_source_need_check` truth table (8 cases, as in `test_needs_sources.py:433`).
- T2 import walk: `ast` of `evidence_scope.py` imports are a subset of the allowed list; plus a subprocess `python -c "import backend.coaching.evidence_scope, sys; print(sorted(m for m in sys.modules if m.split('.')[0] in {'boto3','botocore'} or m.startswith(('backend.persistence','backend.student_store','backend.sources','backend.source_library','backend.providers','backend.settings','backend.agentcore_provider','backend.bedrock_provider'))))"` prints `[]`.
- T3 telemetry order, section C rule.
- T5 `tests/scripts/test_gate_scope_equivalence.py`: for all 295 messages and 12 follow-up cases (and the 9 standalone rows), build `ScopeInputs` through the public adapter helper, call the module, map to scope name (`course`/`student_upload`/`both`/`none`), mode and retrieve, and assert equality with `.agents/tasks/refactor-baseline/gate-decisions-before.json` (assert the file exists; also assert `gate_messages_sha256` still matches `MESSAGES_PATH`); also assert the full `dataclasses.asdict(gate_decision(row))` equals the stored `decision` dict. T6: the three eval `evidence_scoped` approximations equal `course_intent_eligible` on all 295 rows.

## F. Item 2 plan (starts after E6)

### Current import graph among `scripts/evals` (T = top level, L = inside a function)
```
benchmark_agentcore_vs_converse -> evaluate_retrieval (T)
benchmark_course_intent         -> evaluate_combined_gate (L), evaluate_retrieval (L)
compare_turn_routes             -> evaluate_laya_turn_decisions as base (T), evaluate_retrieval (T)
evaluate_combined_gate          -> evaluate_retrieval (T)
evaluate_course_intent          -> evaluate_retrieval (L)
evaluate_course_intent_learn    -> evaluate_retrieval (T), evaluate_course_intent._p95_ms (T)
evaluate_laya_turn_decisions    -> evaluate_retrieval (T), compare_turn_routes (L), evaluate_passage_support.run (L)
evaluate_passage_support        -> evaluate_laya_turn_decisions (T), evaluate_retrieval (T), compare_turn_routes.interval/save (T)
no edges: evaluate_live_coach, evaluate_fast_chat_regression, fast_chat_quality_matrix, measure_stream_first_text
```
Cycles: `evaluate_laya_turn_decisions` <-> `compare_turn_routes` (one direction lazy) and `evaluate_laya_turn_decisions` -> `evaluate_passage_support` -> `evaluate_laya_turn_decisions`. `evaluate_retrieval` is imported by EIGHT scripts, not six. `evaluate_course_intent` and `benchmark_course_intent` are commands outside the brief's list of seven; the same rule applies to them. Names used from `evaluate_retrieval`: `gate_decision`, `GateDecision`, `load_materials/questions/messages/followups`, `*_PATH`, `eval_course_titles`, `rate_record`, `wrong_skip_rate`, `false_retrieve_rate`, `rank_hits`, `RankedHit`, `accepted_targets`, `OfflineCourseSearch`, `_block_network`, `_write_json_output`, `_git_run_metadata`, `evenly_spaced_indices`, `select_live_rows`, `build_live_request`, `check_live_model_request`, `live_model_settings`, `_live_eval_provider`, `live_failure_detail`, `exception_label`, `is_auth_or_access_error`, `LiveCallLimitExceeded`.
Other importers: tests (section D), baseline helpers, `docs/RETRIEVAL_EVAL.md` command lines (`python -m scripts.evals.<name>`; these must keep working). `scripts/` and `scripts/evals/` have no `__init__.py` (namespace packages); add `scripts/evals/lib/__init__.py` (docstring only). Commands that today insert `_PROJECT_ROOT` into `sys.path` (`evaluate_retrieval`, `evaluate_combined_gate`, `benchmark_agentcore_vs_converse`, `measure_stream_first_text`) keep that bootstrap before importing `scripts.evals.lib`; others keep their current invocation style (`-m`).

### Target layout
- `lib/datasets.py`: dataset paths and schema constants, `DatasetError`, `_read_jsonl`, `load_materials/questions/messages/followups`, `validate_*`, `eval_course_titles`, `evenly_spaced_indices` (evaluate_retrieval 395-575, 1906-1930).
- `lib/metrics.py`: `rate`, `rate_record`, `format_rate`, `wrong_skip_rate`, `false_retrieve_rate`, `empty_result_rate`, Wilson `interval` (from compare_turn_routes), `p95_ms` (from evaluate_course_intent `_p95_ms`).
- `lib/ranking.py`: `RankedHit`, `QuestionOutcome`, `rank_hits`, `accepted_targets`, `score_question`, `recall_at_k`, `page_recall_at_k`.
- `lib/offline.py`: `block_network`, `git_run_metadata`, `write_json_output(path, result, run=None)`, `save_json` (compare_turn_routes `save`), `extract_pdf_pages`, `OfflineCourseSearch`.
- `lib/gate.py`: `GateDecision`, `gate_decision` adapter, `scope_name` (also present in `evaluate_laya_turn_decisions.py:107` and `dump_gate_decisions.py`), `eval_upload_entries`.
- `lib/live_model.py`: the live-model helpers shared with `benchmark_agentcore_vs_converse` (`LiveCallLimitExceeded`, `LiveRunRefused`, `build_live_request`, `live_failure_detail`, `exception_label`, `is_auth_or_access_error`, `check_live_model_request`, `select_live_rows`, `live_model_settings`, `_live_eval_provider`). Anything a test patches takes the dependency as a parameter, with the command keeping the wrapper (section D).
- `lib/laya_states.py`: state serialisers and schemas used by two commands, no fitting: `DATA`, `ROUTE_QUESTIONS`, `EVIDENCE_QUESTION`, `read_training`, `normalized`, `route_state`, `evidence_state`, `decide`.
- `lib/routing_eval.py`: report building for routing, no model fitting: `scenarios`, `state`, `training`, `inputs`, `laya_predictor`, `observe`, `apply`, `summary`, `latency`, `evaluate`, `assess`, `provenance`. Fitting (`fit_laya`, `fit_setfit`, `compact_predictors`) stays in `compare_turn_routes.py`.
- `lib/passage_support.py`: `candidates`, `coverage`, `run`. Interpretation: `evaluate_laya_turn_decisions --track evidence` needs `run`, and the brief says passage metrics stay with the experiment that owns them. Moving them to a lib module named for that experiment, with `evaluate_passage_support` re-exporting, is the only way to drop the import without removing a CLI track. `benchmark_pages` (CrossEncoder) stays in the command. Flag this choice in the report.

Every moved name is re-exported from its old command module (same object), so `from scripts.evals.evaluate_retrieval import gate_decision` and `routes.apply` keep working.

### Commit order (each commit: focused tests + `$PY .agents/tasks/refactor-baseline/stub_snapshots.py /tmp/refactor-out after` + `diff_outputs.py`)
- [ ] 7. `lib/__init__.py`, `lib/datasets.py`, `lib/metrics.py`, `lib/ranking.py`; `evaluate_retrieval` re-exports. Verify: `tests/scripts/test_evaluate_retrieval.py` (103 tests) unchanged and passing; `evaluate_retrieval.after.json` identical to before (`run_offline_evals.sh` + `diff_outputs.py`).
- [ ] 8. `lib/offline.py` (+ `lib/gate.py`): `evaluate_retrieval` keeps `_block_network`, `_git_run_metadata`, `_write_json_output` as wrappers/aliases so its patched names still resolve in its own globals. Verify: same tests, plus `python -m scripts.evals.evaluate_retrieval --help` equals `help_evaluate_retrieval.before.stdout.txt`.
- [ ] 9. `evaluate_course_intent` + `evaluate_course_intent_learn` (p95 to `lib/metrics.py`; drop the cross-command import). Verify: `tests/scripts/test_evaluate_course_intent_learn.py` (4) and stub snapshot.
- [ ] 10. `lib/live_model.py` and `benchmark_agentcore_vs_converse` (keep module attribute `retrieval` bound to the lib module). Verify: `tests/scripts/test_benchmark_agentcore_vs_converse.py` (41), dry-run and refusal outputs and exit codes (0 and 2) equal to `.before` files.
- [ ] 11. `lib/laya_states.py`, `lib/routing_eval.py`, `lib/passage_support.py`; rewire `evaluate_laya_turn_decisions`, `compare_turn_routes`, `evaluate_passage_support` (removes both cycles). Verify: `tests/scripts/test_compare_turn_routes.py` (7), stub snapshot equal, `--help` outputs equal.
- [ ] 12. `evaluate_combined_gate` and `benchmark_course_intent`. STOP-AND-REPORT 1 and 2 apply here (section D). Do not edit the two tests. Send a `warning` via `send_message` and wait for the user's answer, then continue only with the answer applied. Verify: `test_evaluate_combined_gate.py` (21), `test_benchmark_course_intent.py` (10), `benchmark_course_intent_stub` JSON diff.
- [ ] 13. Add `tests/scripts/test_eval_command_independence.py`: `ast` walk (top-level and function-level `import`/`from` forms, including `from scripts.evals import X`) over every `scripts/evals/*.py`, fail if any imports another `scripts/evals/*.py` module (the `lib/` package is allowed, and `lib` must not import a command either). Second test: in a subprocess, import `scripts.evals.lib.routing_eval` and `scripts.evals.lib.passage_support` and assert `laya`, `vegaml`, `setfit`, `torch`, `sentence_transformers`, `fitz` are not in `sys.modules` (report code is testable without fitted models). Update `scripts/AGENTS.md` (lib row, rule that commands must not import commands) and `docs/RETRIEVAL_EVAL.md` where it names moved functions.
- [ ] 14. Final verification and report. Full suite (same 2 known failures), `ruff check .`, `run_offline_evals.sh /tmp/refactor-out after` and `diff_outputs.py` (exit 0; only `run.git_sha`, `git_dirty`, `generated_at_utc` and timing values differ, as in the baseline's own normalisation), `cmp` of exit codes (`exit-codes.before.tsv` vs after), `--help` of nine commands byte-equal, `python scripts/evals/<name>.py` and `python -m scripts.evals.<name>` both run for the commands that ran both ways at baseline. Write the report (decision points moved with old and new line numbers, before/after diffs, test counts, commit SHAs, risks). Commit with `git add -f`, push, stop for review.

## G. Risks
1. Mid-method state: Laya cutoff, `source_check_course_titles`, settings read, and post-hydration `retrieval_sources` stay in execution. Reading the upload setting before the first `decide` call instead of after the model call differs only if settings mutate during `score`; the plan reads it before each call.
2. Eval-versus-production differences resolved toward production (status+progression mode, raw versus final intent). No shipped row exercises them. Step 4 lists any difference found on the cross product; a difference on a shipped row stops the work.
3. Eval Laya eligibility is an approximation in three scripts (`searched=decision.retrieve`, `evidence_scoped` from raw rows). It stays; T6 proves it equals the module on all 295 rows. Unifying it would be an eval change.
4. `is_image` guessed from filename in the adapter. It cannot change scope outputs (images count as personal files, bytes assumed resolved), and T5 proves it on the data. Fallback: pass `is_image=False`.
5. Stop points: two existing tests patch `evaluate_retrieval._block_network` for another command's `main` (section D). Seam tests on `evaluate_retrieval` require wrappers to stay there; a missed seam shows up as a failing unchanged test, which is a stop-and-report.
6. `LiveCallLimitExceeded` and similar classes must remain a single class object across re-exports, or `pytest.raises` in `test_benchmark_agentcore_vs_converse.py:204` fails.
7. Moving `passage` functions to `lib/passage_support.py` is an interpretation of "stay with the experiment that owns them" (section F).
8. Default arguments bound at definition time (`load_messages(path=MESSAGES_PATH)`) must keep the same values after the move; `_PROJECT_ROOT` depth changes when files move into `lib/` (`parents[2]` becomes `parents[3]`).
9. The baseline JSON stores `asdict(GateDecision)`; adding a field there breaks the empty-diff acceptance.
10. Docs drift: `docs/RAG_ARCHITECTURE.md` names `execution.py` for the moved helpers; update in the same change (step 5).

## Digest

Verified at 9d43fe6 with `$PY` (Python 3.12 venv) and the mock env above: `$PY -m pytest -p no:cacheprovider tests/domain/test_needs_sources.py tests/domain/test_upload_retrieval_policy.py tests/domain/test_course_library_chat_context.py tests/domain/test_rag_fallback.py tests/scripts` gave 398 passed. Baseline (from `.agents/tasks/refactor-baseline/commands.md`): `ruff check .` passes; full suite 2753 passed, 2 failed (`tests/http/test_notebook_reader.py`, no `frontend/dist`), 1 skipped. Build/validation: `$PY -m pytest -p no:cacheprovider`, `ruff check .`, `$PY -m compileall -q backend scripts tests`. Offline eval: `sh .agents/tasks/refactor-baseline/run_offline_evals.sh OUT after`, `$PY .agents/tasks/refactor-baseline/diff_outputs.py .agents/tasks/refactor-baseline OUT before after`, `$PY .agents/tasks/refactor-baseline/dump_gate_decisions.py OUT/gate-decisions-after.json`.

| File | Block to change | Covering test |
|---|---|---|
| `backend/coaching/evidence_scope.py` (new) | `ScopeSource`, `ScopeInputs`, `ScopeDecision`, `decide_first_pass_scope`, moved helpers | `tests/domain/test_evidence_scope.py` (new: T1-T4) |
| `backend/coaching/execution.py` | helpers 172-376 (the block ends at `_wants_student_upload_retrieval`, which spans 354-389) (`_COURSE_CATALOG_RETRIEVAL_CUES`, `_wants_course_catalog_retrieval` 242, `_wants_source_need_check` 275, `searchable_student_uploads` 303, `is_chit_chat` 327, `local_course_intent_candidate` 342, `_wants_student_upload_retrieval` 354) become re-exports; body of `_prepare_authoritative_turn` 3055-3280 becomes `ScopeInputs` build, two-call protocol, snapshot replacements, ordered `record_field` calls; 3381 and 3400 read the decision | `tests/domain/test_needs_sources.py`, `test_rag_fallback.py`, `test_upload_retrieval_policy.py`, `test_course_library_chat_context.py`, `test_coach_turn_perf.py`, `test_mode_classification.py`, `test_progression_effect.py`, `test_retrieval_gate.py` (unchanged; 398-test focused run passes today) |
| `scripts/evals/evaluate_retrieval.py` | `GateDecision` 580-594 stays, `gate_decision` 604-682 becomes adapter; `_upload_retrieval_policy` 1087-1215; docstring "Mirrors" at 612 and module docstring "composed the same way" | `tests/scripts/test_evaluate_retrieval.py` (103 pass today), new `tests/scripts/test_gate_scope_equivalence.py` |
| `scripts/evals/evaluate_course_intent.py`, `evaluate_course_intent_learn.py`, `evaluate_combined_gate.py` | import of `local_course_intent_candidate` (34, 92, 144) | `test_evaluate_course_intent_learn.py`, `test_evaluate_combined_gate.py`, T6 |
| `docs/RAG_ARCHITECTURE.md`, `backend/AGENTS.md`, `docs/RETRIEVAL_EVAL.md`, `docs/IMPLEMENTATION_STATUS.md` | module paths and module table row | link/symbol check |
| `scripts/evals/lib/*` (new, item 2) | sections F layout | `tests/scripts/test_eval_command_independence.py` (new) plus all `tests/scripts` unchanged |
| the eight command modules in `scripts/evals` | import lines and moved bodies per section F, re-exports kept | `tests/scripts/*` per section D; stub snapshot and offline diffs |
| `scripts/AGENTS.md` | `lib/` row and the no-command-imports rule | doc check |
