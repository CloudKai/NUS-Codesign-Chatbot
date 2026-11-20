# Head-to-head: Laya routing vs KB-score routing (2026-11-20)

Branch `improvement/backend`, head `758de0b` when the analysis ran. **Nothing live ran.** No AWS, Bedrock, AgentCore, Knowledge Base or other paid call, and no run that loads Laya weights. The two live inputs (the KB-score JSON and an all-rows Laya file) do not exist. **No arm can be declared the winner until both exist.** This report is a status of the build and of what can be said offline.

Labels follow the pre-registration: **measured** (computed by code from data in this repository), **bound** (a one-sided limit from a stated assumption), **missing** (no data). Message text appears nowhere in this report or in the outputs it describes. Only ids and category names are used.

## 1. Pre-registration and ordering

- Plan: `.agents/tasks/headtohead-prereg/plan.md`, commit `8c51cdd203b8a2795676b398cf6ca1b078b368df`, sha256 `59fd07ffc9c64ed657de59dfecadb75c3f37ef898225dd87850044f20c4c0b9c` (the file's sha256 at this report's time equals the value recorded by `compare_routing_arms` in its output, with `constants_match_code: true`).
- The plan text was not edited. **Dated amendments: none.**
- Ordering from `git log` (author dates, UTC):

| Commit | Time | What |
|---|---|---|
| `e9bebcb` | 2026-11-20T08:07:01Z | base, before any of this work |
| `8c51cdd` | 2026-11-20T09:22:52Z | **plan.md (pre-registration)** |
| `6459ba8` | 2026-11-20T09:28:12Z | first analysis code: `--live-kb-gate` |
| `f377a1c` | 2026-11-20T09:40:29Z | `compare_routing_arms` and the split, `T` and pass-rule code |
| `1f6acb6` | 2026-11-20T09:45:05Z | Laya host-noted all-rows run |
| `a1bd91e` | 2026-11-20T09:52:04Z | `--extra-messages` |
| `758de0b` | 2026-11-20T09:54:56Z | docs |
| offline run | 2026-11-20T09:55:21Z | `generated_at_utc` in `offline-results.json` (the `run` block names git sha `758de0b`, clean tree) |

The plan commit predates all analysis code and the only results. The plan records that no per-half figure was computed or read before it was written.

## 2. Status per arm

All four arms are `fail` or `cannot be determined yet`. None passes. Pass rule (fixed in the plan): holdout M1 <= 15%, M2 <= 10%, added p95 wait <= 1,000 ms; `pass` needs every criterion to hold under the pessimistic reading of each unknown.

| Arm | Status | Why |
|---|---|---|
| A existing gate | **fail** | Holdout M1 is 37/73 = 50.7%. The search-only proxy treats every KB search as evidence injected, which is the optimistic case for M1, so the real M1 can only be equal or higher. |
| B gate + Laya (current promotion rule) | **fail** for all three stored sources (multilingual, typed decisions, Learn) | Even at the ceiling reading (every unscored eligible row promoted) M1 stays above 15%: multilingual 34/73 = 46.6%, typed decisions 37/73 = 50.7%, Learn 12/73 = 16.4%. |
| C KB-score routing | **cannot be determined yet** | Needs the KB-score file. No `T_C` was chosen. |
| D hybrid | **fail** for all three stored sources, as a bound | D searches only where B searches, so its M1 cannot beat B's ceiling M1. It still needs the KB file to be measured. |

Selection (plan section 9): "No arm has passed yet; the undetermined arm (C) could still pass." Provisional. No full comparison is claimed.

A and B were already known to be far from the 15% M1 limit. The offline result does not rank them by a live measure. What remains open is whether C, and D with a measured `T`, can meet the rule, and that needs live data.

## 3. Split and coverage

Rule (plan section 2): calibration if `int(sha256(row_id), 16) % 2 == 0`, else holdout. One function, `scripts/evals/lib/prereg.py`.

| Half | Rows | `retrieve` | `skip` | Laya eligible |
|---|---|---|---|---|
| calibration | 153 | 81 | 72 | 69 |
| holdout | 142 | 73 | 69 | 78 |

Only the holdout half is reported. Calibration rows only choose `T`, and no `T` exists yet.

**Laya coverage is partial (caveat for every B figure).** Of 147 eligible rows, stored decisions cover 94 (multilingual, 0.8), 94 (typed decisions, 0.8) and 41 (Learn per-turn cutoffs 0.8563768 continuing and 0.6455846 first turn). The Learn file's own 84 rows come from an earlier fit and are not this split. B is shown as floor (unscored eligible rows not promoted), ceiling (all promoted) and scored-only (unscored eligible rows left out, which shrinks the row set to 113 or 86). On the stored files the gate decisions and eligibility agree with the code at this commit (`consistency_with_gate_at_this_commit.consistent: true` for all three). Stored Laya latency comes from a development laptop, not the target host.

## 4. Measured

Computed by code at `758de0b`, no KB file:

- The split and its sizes (section 3).
- Arm A's and arm B's search decisions from `backend/coaching/evidence_scope.py` (`decide_first_pass_scope`), and arm C's skip decisions: 44 of 295 rows are skipped by C. The first rule to fire is greeting 11, stage navigation 21, personal reasoning 12 (`skip_rules_arm_c` in the JSON).
- M3, searches added per 100 turns versus arm A, scored-only reading: B multilingual KB +2.65 and local +0.0 (113 rows); B typed decisions +0.0; B Learn +2.33 (86 rows). The floor and ceiling M3 values are bounds (section 5). Arm A is 0 by definition.
- M5 for A on the 142 holdout rows: $0.2042 per 1,000 turns at $1 per 1,000 searches (assumed price, not checked against an AWS page). This counts KB searches only.
- Stored Laya inference time, from the stored files: multilingual p50 169.64 ms, p95 211.05 ms, max 280.06 ms; typed decisions p50 392.21 ms, p95 450.31 ms, max 629.68 ms; Learn p50 900.73 ms, p95 932.41 ms, max 994.96 ms. Development laptop, serial.
- Exact McNemar tests (section 6) and Wilson intervals, as `bound` where they depend on the search-only proxy.

## 5. Bound

Everything below uses the search-only proxy: a KB search is counted as evidence injected. That is optimistic for M1 and pessimistic for M2. A failed or empty KB call would change it. Wilson 95% intervals are in square brackets. S marks fewer than 30 rows and VS fewer than 10.

### 5.1 Holdout M1 and M2, multilingual (primary source), all three readings

| Arm | M1 (73 `retrieve` rows, no evidence) | M2 (69 `skip` rows, evidence) | M3 KB / local per 100 turns |
|---|---|---|---|
| A | 37/73 = 50.7% [39.5, 61.8] | 3/69 = 4.3% [1.5, 12.0] | +0.0 / +0.0 |
| B floor | 34/73 = 46.6% [35.6, 57.9] | 3/69 = 4.3% [1.5, 12.0] | +2.11 / +0.0 |
| B ceiling | 34/73 = 46.6% [35.6, 57.9] | 32/69 = 46.4% [35.1, 58.0] | +22.54 / +0.0 |
| A scored-only (113 rows) | 37/73 = 50.7% [39.5, 61.8] | 3/40 = 7.5% [2.6, 19.9] | +0.0 / +0.0 |
| B scored-only (113 rows) | 34/73 = 46.6% [35.6, 57.9] | 3/40 = 7.5% [2.6, 19.9] | +2.65 / +0.0 (measured) |

### 5.2 Other stored Laya sources, B only (A is identical to 5.1)

| Source and reading | M1 | M2 | M3 KB per 100 turns |
|---|---|---|---|
| Typed decisions, floor | 37/73 = 50.7% [39.5, 61.8] | 3/69 = 4.3% [1.5, 12.0] | +0.0 |
| Typed decisions, ceiling | 37/73 = 50.7% [39.5, 61.8] | 32/69 = 46.4% [35.1, 58.0] | +20.42 |
| Typed decisions, scored-only (113 rows) | 37/73 = 50.7% [39.5, 61.8] | 3/40 = 7.5% [2.6, 19.9] | +0.0 |
| Learn, floor | 35/73 = 47.9% [36.9, 59.2] | 3/69 = 4.3% [1.5, 12.0] | +1.41 |
| Learn, ceiling | 12/73 = 16.4% [9.7, 26.6] | 36/69 = 52.2% [40.6, 63.5] | +40.85 |
| Learn, scored-only (86 rows) | 12/50 = 24.0% [14.3, 37.4] | 3/36 = 8.3% [2.9, 21.8] | +2.33 |

Under Learn scored-only, A is 14/50 = 28.0% [17.5, 41.7] on M1 and 3/36 = 8.3% [2.9, 21.8] on M2.

### 5.3 M4 and M5 (bounds)

- Added wait p95 in ms (the Laya inference time only; KB time is missing): multilingual floor 179.1 to 280.06 across the lower and upper imputation, typed decisions floor 419.68 to 629.68, Learn floor 909.02 to 994.96. For scored-only: 182.14, 424.77 and 924.48. These are within the 1,000 ms limit as Laya-only figures, but the KB search time is **missing**, so the wait criterion cannot be settled for B or D. Local-search time is missing for all arms.
- M5 per 1,000 turns (KB searches only, $1 per 1,000 searches assumed): A $0.2042; B multilingual floor $0.2253, ceiling $0.4296; typed decisions floor $0.2042, ceiling $0.4084; Learn floor $0.2183, ceiling $0.6127. Laya host memory is **missing**.

### 5.4 Per category, holdout (A, and B at the floor reading)

Only categories where the arm outcome applies are shown (M1 for `retrieve`-labelled rows, M2 for `skip`-labelled rows; `follow_up` has both). Typed decisions at the floor reading change no category compared with A. Ceiling and scored-only tables are in the regenerated output (section 11).

| Category | A | B multilingual floor | B Learn floor |
|---|---|---|---|
| ambiguous_generic | M2 1/5 = 20.0% [3.6, 62.5] VS | same | same |
| attachment_question | M1 0/4 = 0.0% [0.0, 49.0] VS | same | same |
| course_content | M1 21/35 = 60.0% [43.6, 74.5] | same | M1 19/35 = 54.3% [38.2, 69.5] |
| course_logistics | M1 5/5 = 100.0% [56.5, 100.0] VS | M1 4/5 = 80.0% [37.5, 96.4] VS | same as A |
| follow_up | M1 2/3 = 66.7% [20.8, 93.8] VS; M2 1/2 = 50.0% [9.4, 90.5] VS | same | same |
| greeting_thanks_chitchat | M2 0/16 = 0.0% [0.0, 19.4] S | same | same |
| informal_or_multilingual | M1 4/4 = 100.0% [51.0, 100.0] VS | M1 2/4 = 50.0% [15.0, 85.0] VS | same as A |
| mixed_project_and_course | M1 0/1 = 0.0% [0.0, 79.3] VS | same | same |
| named_material | M1 0/6 = 0.0% [0.0, 39.0] VS | same | same |
| not_in_course_material | M2 0/1 = 0.0% [0.0, 79.3] VS | same | same |
| out_of_scope | M2 0/4 = 0.0% [0.0, 49.0] VS | same | same |
| procedural_ui | M2 0/13 = 0.0% [0.0, 22.8] S | same | same |
| project_mentions_course | M2 1/3 = 33.3% [6.2, 79.2] VS | same | same |
| project_reasoning | M2 0/18 = 0.0% [0.0, 17.6] S | same | same |
| stage_meta_guidance | M2 0/4 = 0.0% [0.0, 49.0] VS | same | same |
| stage_navigation | M2 0/3 = 0.0% [0.0, 56.1] VS | same | same |
| upload_and_course | M1 1/5 = 20.0% [3.6, 62.5] VS | same | same |
| upload_question | M1 4/10 = 40.0% [16.8, 68.7] S | same | same |

Every category cell is a small sample except `course_content` (35 rows). Read the per-category figures as descriptive.

## 6. McNemar tests (exact, two-sided, holdout rows)

**Arms B and D only add searches to arm A, so "A is never better than B" on M1 is built in.** For B this holds on the `retrieve` rows. For D it holds for searches only, because `T` can withhold evidence that arm A would inject. A significant B-over-A result on the `retrieve` rows follows from construction. It is not evidence of Laya quality by itself. The M2 family and the all-rows family carry the information. No multiplicity correction is applied and the p-values are descriptive.

Discordant counts are shown as "first-only bad / second-only bad" where "bad" is the M1 or M2 outcome (or a mistake in the all-rows family). A is the first arm.

| Laya source, reading | Family | Rows | Discordant (A only bad / B only bad) | p |
|---|---|---|---|---|
| Multilingual, floor | `retrieve` rows (M1) | 73 | 3 / 0 | 0.2500 |
| Multilingual, floor | `skip` rows (M2) | 69 | 0 / 0 | 1.0000 |
| Multilingual, floor | all rows (mistakes) | 142 | 3 / 0 | 0.2500 |
| Typed decisions, floor | `retrieve` rows (M1) | 73 | 0 / 0 | 1.0000 |
| Typed decisions, floor | `skip` rows (M2) | 69 | 0 / 0 | 1.0000 |
| Typed decisions, floor | all rows (mistakes) | 142 | 0 / 0 | 1.0000 |
| Learn, floor | `retrieve` rows (M1) | 73 | 2 / 0 | 0.5000 |
| Learn, floor | `skip` rows (M2) | 69 | 0 / 0 | 1.0000 |
| Learn, floor | all rows (mistakes) | 142 | 2 / 0 | 0.5000 |

No A-versus-B difference reaches p < 0.05 at the floor reading, and with 3 or fewer discordant rows none could. All A-versus-B pairs are status `bound`. The ceiling and scored-only pairs are in the regenerated output.

The pairs A vs C, B vs C and C vs D are **missing**: they need the KB-score file.

## 7. Missing

- **KB-score file** (one Retrieve per gate message). It is required for arm C, arm D, `T_C` and `T_D`, KB elapsed ms (p50, p95), failed and empty call counts, and every figure that depends on whether a search returned evidence. Without it A and B are bounds.
- **All-rows Laya file** with the host noted. It is required for Laya on all 147 eligible rows (the stored files cover 94, 94 and 41), Laya RSS memory (M5), Laya latency on the target host, and a full B and D comparison.
- **Host details.** Instance type `<TYPE>`, vCPU `<N>`, RAM `<GB>`, arch `<arm64|x86_64>`. These are literal, unfilled placeholders. The operator has not supplied values, and none were invented. They are filled in only when the operator runs the host command.
- Local-search time (not measured by any harness).
- Real-message results (`--extra-messages`): no file was supplied. That section is empty and is never mixed into M1 or M2.
- The four model-weight licences (section 9, M6).

## 8. Exact live commands (documented, not run)

Full text, with the IAM and cost sections, is in `docs/RETRIEVAL_EVAL.md`, section "Head-to-head routing comparison (built, not run)". Run from the repository root with the project virtual environment.

```bash
# 1. KB scores: one Retrieve per gate message, all 295 (live, costs money, needs approval)
KNOWLEDGE_BASE_ID=<kb id> KNOWLEDGE_BASE_TYPE=managed \
KNOWLEDGE_BASE_METADATA_FILTER_MODE=required \
COURSE_MATERIALS_BUCKET=<course bucket> AWS_REGION=<region> \
  python scripts/evals/evaluate_retrieval.py --live-kb-gate --max-live-calls 295 \
  --json-output .agents/tasks/headtohead-prereg/kb-gate.json

# 2. Laya on all 295 rows, on the host to be reported (needs the weights; no AWS call)
python -m scripts.evals.benchmark_course_intent --checkpoint /path/to/laya-multilingual \
  --passes 3 --warmup 5 \
  --host-instance-type <TYPE> --host-vcpu <N> --host-ram-gb <GB> --host-arch <arm64|x86_64> \
  --json-output .agents/tasks/headtohead-prereg/laya-all-rows-multilingual.json
# Laya Learn: use  --checkpoint /path/to/vega --bundle /path/to/course-learner.zip  instead

# 3. Combined analysis (offline)
python -m scripts.evals.compare_routing_arms \
  --kb-gate .agents/tasks/headtohead-prereg/kb-gate.json \
  --laya-full .agents/tasks/headtohead-prereg/laya-all-rows-multilingual.json \
  --json-output .agents/tasks/headtohead-prereg/comparison.json \
  --markdown-output .agents/tasks/headtohead-prereg/comparison.md
# Laya Learn file: add  --laya-full-kind learn
```

`<TYPE>`, `<N>`, `<GB>` and `<arm64|x86_64>` are **unfilled until the operator runs command 2**. Command 2 refuses to start with a placeholder, a missing flag, or a non-positive vCPU or RAM value. The harness records the values as given and compares them with the machine, and a mismatch is recorded, not fatal.

`--live-kb-gate` refuses to run without `--max-live-calls N` (1 to 295), sends one attempt per message, stops on the first auth or access error, records the git sha and timestamp, and writes ids, scores, counts and timings only.

**IAM** (`docs/RETRIEVAL_EVAL.md`, "IAM for the live gate"): `bedrock:Retrieve` on `arn:aws:bedrock:<region>:<account-id>:knowledge-base/<KB-ID>`. `bedrock:RetrieveAndGenerate` is not needed. Status: verified against AWS documentation (the Service Authorization Reference and the Retrieve API page), **not tested on a real account**. The repo runbook `docs/deploy/AWS_STATELESS_EC2.md` grants the same action on the same resource form.

**Cost** (`docs/RETRIEVAL_EVAL.md`, "Cost estimate"): at most 295 Retrieve calls. At the user-supplied $1 per 1,000 calls that is $0.295, about $0.30. The $1 price is an assumption and is not checked against an AWS price page. The gate makes no model, Converse or S3 call. Worst-case wall time is about 49 minutes if every call hit the 10 s read timeout. Other AWS billing for a Retrieve is **unknown** (third-party pages disagree for managed and vector-store Knowledge Bases, and none was confirmed against AWS). The Laya host run makes no AWS call, and the host's own price is not estimated. The analysis command is offline and free.

## 9. M6 operational risk table (facts only)

Sources: the Phase 4 report `.agents/tasks/phase4-2026-11-19.md` (item 3), re-verified against the code at `758de0b`. Items marked "from Phase 4" rest on PyPI metadata the earlier phase read on 2026-11-19 and that I did not refetch (no network use in this task). Laya settings default to off: `backend/settings.py:384-389` (checkpoint and learner bundle default to the empty string).

| Factor | Facts | Evidence |
|---|---|---|
| New dependency | The `laya` package is imported lazily, only when a checkpoint is set (`from laya import Agent`, `from laya import Learner`). `requirements.txt`, `requirements-dev.txt` and `agentcore_runtime/requirements.txt` contain no laya, vegaml or torch entry (searched). From Phase 4: `laya 0.4.38` needs torch, transformers, safetensors, huggingface_hub, numpy, `vegaml>=0.17.0` and cryptography. The repo docs pin `laya==0.4.37` (single model) and `laya==0.4.38` with `vegaml==0.17.1` (Learn). Resolution against the 20 existing pins was never run: **unknown**. | `backend/course_intent.py:96`, `:151`; `docs/RETRIEVAL_EVAL.md:449`, `:468` |
| Memory | **Unknown.** No RSS figure exists in any file. `compose.prod.yaml` sets no memory limit (searched for `mem_limit`, `memory`, `deploy:`: none). The all-rows host run records RSS. From Phase 4: a 0.8B-parameter model at 16 bits is about 1.6 GB by arithmetic only, with no weight file measured. | `compose.prod.yaml:1-6` (the `app` service), `scripts/evals/benchmark_course_intent.py` (`memory` key) |
| Concurrency slot | One non-blocking lock per classifier. A busy slot returns `None` and the gate applies. The server runs one uvicorn worker, so there is one classifier and one slot per container. Stored contention run: 93 of 94 calls abstained as busy with 8 workers. | `backend/course_intent.py:99`, `:105` (multilingual), `:158`, `:164` (Learn); `scripts/start_prod.sh:69-71`; `compose.prod.yaml:80`; `.agents/tasks/phase3d-work/multilingual-concurrency8.json:9` |
| Startup failure | If a checkpoint is set and the directory, `model.safetensors`, the bundle or the `laya` package is missing, construction raises `ValueError` or `ImportError`. `OwnerResolver.__init__` builds the classifier, and `create_app` calls it with no try block, so API startup fails. The compose `app` service has `restart: unless-stopped`, so the container would restart in a loop (from reading the config, not run). | `backend/course_intent.py:94-96`; `backend/owner_context.py:71-78`; `backend/http/app.py:282`; `compose.prod.yaml:4` |
| Timeout | No timeout on Laya inference (searched `backend/course_intent.py` for "timeout": none). A hung `predict` keeps the lock, so that turn waits and later turns get no score (read from code, not tested). An exception from `score()` is caught and logged by type, and the turn continues. The call is synchronous in request preparation, only on turns that are course-intent eligible and have course titles. The KB search has a 10 s default timeout (bounded 2 to 30). | `backend/coaching/execution.py:3013-3027` (Phase 4 cited 3229-3256, which is stale at this commit); `backend/settings.py:308-310` |
| Licence status | Packages, from Phase 4 (PyPI metadata, 2026-11-19): `laya` 0.4.38 Apache-2.0, `vegaml` 0.17.1 Apache-2.0. **Model-weight licences: unknown** (four weights: laya-multilingual, laya-typed-decisions, `nandakishorm/vega-U`, `Qwen/Qwen3.5-0.8B`). Their Hugging Face pages returned 403 in Phase 4, and secondary sources only say Apache-2.0. A person must read each card before any deploy. | `.agents/tasks/phase4-2026-11-19.md` item 3, "Licences" |
| Packaging effort | **Unknown (not estimated).** Facts: the image installs only `requirements.txt`; `COPY . .` would copy any weights placed in the build context; the target is `linux/arm64` on `python:3.12-slim`. Whether arm64 resolution pulls CUDA packages was not tested. The dependency audit covers `requirements.txt` and `agentcore_runtime/requirements.txt` only, so a separate Laya requirements file would need a new path and job. No weight storage or delivery choice exists in the repo. From Phase 4: torch 2.15.0 cp312 wheels are 461 MiB (aarch64) and 514 MiB (x86_64). | `Dockerfile:3`, `:11`, `:29-31`, `:36`; `.github/workflows/dependency-audit.yml:10-13`, `:21`, `:36` |

Latency facts for context: stored Laya times in section 4 come from a development laptop. There is no latency figure for the target host. KB search latency has **no figure** (no live run).

## 10. The open point: arm C's three skip rules

Arm C skips the KB search only where the existing high-precision skip rules fire. All three are isolated from existing code with no new gate logic, so arm C is **evaluated, not marked "cannot be evaluated"**. The skip is the OR of the three. All scope decisions go through `backend/coaching/evidence_scope.py` (`decide_first_pass_scope`, line 348).

| Rule | Code | How arm C reads it | Rows (first rule to fire, 295 rows) |
|---|---|---|---|
| Greeting or acknowledgement | `is_chit_chat`, `backend/coaching/evidence_scope.py:281-294`, built on `is_greeting_or_acknowledgement` (`backend/retrieval.py:152`) and `looks_like_information_request` (`backend/coaching/mode_policy.py:296`) | `is_chit_chat(row["message"])` | 11 |
| Stage navigation | `scope_cleared`, `backend/coaching/evidence_scope.py:447-451`, from stage status, progression and `workflow_skips_retrieval` | `gate_decision(row).scope_cleared` | 21 |
| Personal reasoning | `_is_personal_reasoning`, `backend/retrieval_gate.py:338`; it returns `INTENT_HIGH_CONFIDENCE_PERSONAL` at `backend/retrieval_gate.py:429-432`, which reaches `ScopeDecision.classifier_intent` (`backend/coaching/evidence_scope.py:389`, `:553`) | `gate_decision(row).intent == "high_confidence_personal"` | 12 |

Implementation: `scripts/evals/lib/routing_arms.py:56-69` (attribution order greeting, navigation, personal; the skip is the OR) and `:94-96`. Total 44 of 295 rows are skipped by C.

Caveats (stated in the plan, section 4):
- Greeting is not a skip decision in production today. The gate skips greetings only because no cue matches. Arm C reuses the predicate as a rule. Its docstring lists known misses (`thx`, `haha nice`, `ok will try`) (`evidence_scope.py:281-294`). Those rows go to the KB, and `T` is the only protection.
- `is_chit_chat` does not check source cues, so a mixed message can be skipped by C where the gate would retrieve.
- `scope_cleared` also covers meta-guidance and prior-stage review, not only status and progression.
- Dataset rows carry no `explicit_mode`, so Lecture Help never triggers.
- Arm C keeps arm A's local-search flag, so a production arm C that searches more local files is not modelled.

What is missing for C is only the KB-score file and the `T_C` it would choose. C's M1 and M2 are not computable before that, and I did not compute C's M1 or M2 from rule attributions alone, since evidence injection depends on the KB score.

## 11. Reproduce the offline results

The outputs are git-ignored. They are `.agents/tasks/headtohead-prereg/offline-results.json` and `offline-results.md`, and they were written by:

```bash
python -m scripts.evals.compare_routing_arms \
  --json-output .agents/tasks/headtohead-prereg/offline-results.json \
  --markdown-output .agents/tasks/headtohead-prereg/offline-results.md
```

The command defaults to the stored Laya files in `.agents/tasks/phase3d-work`. Exit code 0. It blocks the network and writes no message text. `kb_file` in the JSON is `{"present": false}` and arms C and D are `missing`. The ceiling and scored-only per-category tables and pairs are in `offline-results.md`.

## 12. Tests and lint versus the baseline

Commands from the mock-CI environment (`MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false AUTO_ADVANCE_STAGES=false APP_ENV=development`, `-p no:cacheprovider`, Python 3.12 venv).

| | Baseline at `e9bebcb` | Now at `758de0b` |
|---|---|---|
| passed | 2905 | **3041** |
| failed | 2 | 2 |
| skipped | 1 | 1 |
| ruff (`ruff check --no-cache .`, 0.11.13) | All checks passed | All checks passed |

- **No new failure.** The same two tests fail now as in the baseline, both `assert 404 == 200` on `GET /` because `frontend/dist` is not built: `tests/http/test_notebook_reader.py::test_pilot_serves_only_built_public_assets` and `::test_default_workspace_and_streamlit_gate`. In the baseline they also failed when rerun alone, so they are stable and unrelated to this work. Phase 4 recorded 0 failures when `dist` is built.
- The one skip is the whole `tests/domain/test_strands_first_cycle_middleware.py` module (`strands` is not installed).
- Delta of +136 passed, all in `tests/scripts`: 287 passed at the baseline commit and 423 now. The four new test files hold 28 (live gate), 43 (compare), 18 (host note) and 35 (extra messages), which is 124. The other 12 are extra cases in `test_eval_command_boundaries.py` (39 became 41 collected checks) and other existing parametrised checks that discover new scripts and modules. No existing test file was edited. Only `tests/AGENTS.md` and the four new test files changed under `tests/`.
- Wall time of the full run was 140.5 s. No flaky test appeared.
- Nothing under `backend/`, `agentcore_runtime/` or `frontend/` changed between `e9bebcb` and `HEAD`. All settings stay at their defaults (off). No production routing changed, and no new gate rule was added.

## 13. Commits of this work

All authored and committed by `CloudKai <kaiming_01@live.com>` on both sides, with no Kiro or co-author text (checked with `git log --format='%h %an|%cn'`). All are on `improvement/backend`.

| SHA | Subject |
|---|---|
| `8c51cdd` | docs: pre-register head-to-head routing evaluation |
| `6459ba8` | feat(evals): live Knowledge Base gate run (built, not run) |
| `f377a1c` | feat(evals): compare_routing_arms with pre-registered split |
| `1f6acb6` | feat(evals): host-noted all-rows Laya run |
| `a1bd91e` | feat(evals): optional extra human-labelled messages |
| `758de0b` | docs: head-to-head routing comparison commands, IAM, cost, pre-registration |
| (this commit) | docs: head-to-head report; its sha is in the final hand-off message |

## 14. Risks

- **Selection bias in `T`.** `T` will be chosen on about half of 295 rows with point estimates, and KB scores are not calibrated across queries. It is an optimistic, empirical value for one Knowledge Base.
- **Search-only proxy.** Without the KB file, A and B M1 is optimistic and M2 pessimistic. The `fail` outcomes hold because the proxy is on the favourable side for M1.
- **Partial Laya coverage.** B is a bracket from stored, partial results on a different (laptop) host. Learn cutoffs were fitted on rows of this same message set, so Learn is secondary evidence only.
- **Synthetic set.** The 295 messages are synthetic. Pass or fail on them does not transfer to real students. The `--extra-messages` path exists for that and has not been used.
- **Eligibility model.** Eligibility follows the course-intent eval scripts. Production also treats an effective source id, interaction intent or frozen history as scope, which the harness does not model.
- **Local searches.** Any local search counts as evidence injected in every arm. That is optimistic for M1 and pessimistic for M2.
- **Small cells.** Per-category cells are mostly under 30 rows and many under 10. The McNemar discordant counts are 3 or fewer, so no A-versus-B p-value can reach 0.05 at the floor reading.
- **Untested IAM and unconfirmed price.** The IAM statement comes from AWS documentation and was not tested. The $1 per 1,000 price is an assumption, and other Retrieve billing is unknown.
- **Pre-existing failures.** Two `test_notebook_reader.py` tests fail without a built `frontend/dist`.

## 15. Decisions left for the user

1. **Run the KB gate?** Approve or decline the live run (up to 295 Retrieve calls, about $0.30 at the assumed price), the IAM grant for `bedrock:Retrieve`, the Knowledge Base id and type, and the region.
2. **Run the Laya all-rows host run?** Choose the host and supply `<TYPE>`, `<N>`, `<GB>` and `<arm64|x86_64>`, make the weights available, and pick the checkpoint or checkpoints (multilingual primary, Learn secondary).
3. **Laya weight licences.** Someone must read the four model cards. M6 stays `unknown` for weights until then.
4. **Startup behaviour and timeout** (open from Phase 4): fail startup or fall back to the gate on a missing checkpoint, and whether to add an inference timeout. No change was made here.
5. **Real messages.** Whether to supply anonymised, human-labelled messages for `--extra-messages`.
6. **Whether to enable anything.** Nothing is enabled. All settings stay default off, and this report changes no routing decision.

## 16. Amendments to the plan

None. The plan text is unchanged since `8c51cdd`.

## 17. Statement

Nothing live ran. No arm can be declared the winner until the two live files exist: the KB-score JSON from `--live-kb-gate`, and the full Laya all-rows file from `benchmark_course_intent` with the host noted. Until then, A and B fail the pre-registered M1 limit on the stored evidence, C cannot be determined, and D is bounded by B.
