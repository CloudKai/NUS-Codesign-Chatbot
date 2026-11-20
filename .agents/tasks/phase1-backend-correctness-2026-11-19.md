# Phase 1 report: backend correctness (2026-11-19)

Repo `CloudKai/NUS-Codesign-Chatbot`, branch `improvement/backend`. Base commit `399c29d`. Mock providers only, no live AWS or paid calls.

**Status:** items 1, 2 and 3 are done and pushed. Item 4 is blocked and needs your decision (section d). The "full mock suite passes" gate is met only relative to the baseline (section c).

## (a) Baseline (at 399c29d, before any change)

Setup: Python 3.12.13 venv at `/projects/sandbox/.venvs/nus-codesign-py312`, `pip install -r requirements-dev.txt` (pytest 9.0.3, ruff 0.11.13). PyPI was reachable. `agentcore_runtime/requirements.txt` was not installed (CI uses it for a separate job).

Commands, run from the repo root with the env vars from `mock-ci.yml`:

```
ruff check .
MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false AUTO_ADVANCE_STAGES=false APP_ENV=development PYTHONPYCACHEPREFIX=/tmp/co-design-pycache \
  python -m pytest -rfEs -p no:cacheprovider
```

`pyproject.toml` already adds `-q`. Do not add another `-q`, because that hides the count line.

| Run | Passed | Failed | Skipped |
|---|---|---|---|
| 1 | 2,314 | 2 | 1 |
| 2 | 2,313 | 3 | 1 |

Pre-existing failures:
1. `tests/http/test_notebook_reader.py::test_pilot_serves_only_built_public_assets`: `/pilot/` returns 404. Needs a built `frontend/dist`. Fails every run.
2. `tests/http/test_notebook_reader.py::test_default_workspace_and_streamlit_gate`: `/` returns 404. Same cause. CI builds the frontend first (`npm ci --ignore-scripts --prefix frontend && npm run build --prefix frontend`). `frontend/dist` is not gitignored, so I did not build it, to keep the tree clean.
3. `tests/domain/test_source_library.py::test_lecture_notes_folder_syncs_updates_and_removes_sources`: flaky. Failed in 3 of 4 baseline full runs and passed 6 of 6 when run alone. Failure is `assert 0 == 1` at line 189: the sync reported `unchanged=1` instead of `updated=1`. The original and rewritten note text are both 46 characters, so if change detection uses size and mtime, a rewrite in the same timestamp tick looks unchanged. This is a hypothesis; I did not read the sync code.

Skipped (1): `tests/domain/test_strands_first_cycle_middleware.py:16`, because `strands` is not installed. CI runs it in the `agentcore-runtime-compatibility` job.

Ruff baseline: exit 1 with 3 F401 (unused import) findings:
- `tests/domain/test_hmw_scaffold_gate.py`: `add_text_source`.
- `ui/services/runtime.py`: `UploadAdmissionError`.
- `backend/http/app.py`: `PROGRESS_LABELS`.

## (b) What changed, items 1 to 4

Commits (both author and committer CloudKai): `066b66b` (ruff cleanup) and `4b46822` (items 1 to 3).

### Item 1: reserved result slots (2 course + 2 student)
- **Split chosen:** 4 total slots, 2 course (Knowledge Base) + 2 student upload. New setting `FAST_CHAT_RETRIEVAL_COURSE_SLOTS` (default 2, bounds 1 to 8). The student share is `FAST_CHAT_RETRIEVAL_MAX_CHUNKS - course slots`.
- **Why:** the existing cap `FAST_CHAT_RETRIEVAL_MAX_CHUNKS=4` already limits the prompt. 2 + 2 is the even split inside that cap and matches the plan's "about 2 + 2". The total is unchanged, so prompt size and cost do not change.
- **Cause of the crowding:** `CompositeContextRetriever` appended up to 4 Knowledge Base chunks before the local chunks, then `backend/coaching/execution.py` re-bounded to the first 4. A full set of course hits left no room for uploads.
- **Rules:** both sides keep at least one slot when the total is 2 or more. A side that returns fewer hits releases its unused slots (the course side is offered spare slots first). Course chunks stay ahead of upload chunks in the prompt.
- **Known limits:** the 8,000-character prompt budget in `execution.py` still applies after the slot cut, so two very large course chunks could still squeeze the tail. Selected image marker chunks from the local retriever count as student slots. With `FAST_CHAT_RETRIEVAL_MAX_CHUNKS=1` the student side gets 0 slots (default is 4).

### Item 2: Knowledge Base candidates (12)
- **Count chosen:** request 12 candidates (`KNOWLEDGE_BASE_RETRIEVE_CANDIDATES`, default 12, bounded 12 to 16), validate each, rank by score (stable), keep the best 4.
- **Why 12:** it is 3 times the kept count and the low end of the 12 to 16 range. Retrieve latency is dominated by the managed search round trip, not the result count, and fewer candidates keep response size and validation work small. Operators can raise it to 16 with no code change.
- The adapter never sends fewer candidates than it keeps. Hits that fail the bucket, object-key or empty-text checks are dropped before the trim, so they never take a kept slot.

### Item 3: parallel retrieval
- The Knowledge Base call runs on a one-worker thread with the turn's context copied (`contextvars.copy_context`), so turn-perf fields land on the right turn. Local ranking runs on the calling thread. Exceptions from either side propagate as before. When only one side is needed the code runs inline. Retrieve admission and timeout logic in `bedrock_retrieve.py` is unchanged.
- Local ranking is pure Python, so the gain is overlap with the Knowledge Base network wait, not CPU parallelism.

### Item 4: single prompt source
- **Blocked. No file was changed.** See section (d).

### Ruff cleanup (commit 066b66b)
- Removed unused `PROGRESS_LABELS` from `backend/http/app.py` (still imported where used, in `streaming.py`) and unused `add_text_source` from `tests/domain/test_hmw_scaffold_gate.py`.
- Kept `UploadAdmissionError` in `ui/services/runtime.py` with `# noqa: F401`, because `ui/runtime.py` re-exports it and `ui/panels/sources.py` imports it through that alias.

### Files touched
`.env.example`, `backend/bedrock_retrieve.py`, `backend/retrieval.py`, `backend/settings.py`, `backend/http/app.py`, `ui/services/runtime.py`, `docs/PROMPT_ARCHITECTURE.md`, `docs/RAG_ARCHITECTURE.md`, `tests/domain/test_bedrock_retrieve.py`, `tests/domain/test_retrieval_slots.py` (new), `tests/domain/test_source_chunk_artifacts.py`, `tests/domain/test_hmw_scaffold_gate.py`.

## (c) Tests and final results

New file `tests/domain/test_retrieval_slots.py` (20 tests):
- **Item 1:** a student upload is not crowded out by course results, backfill in both directions (course short, student short), and settings overrides and bounds.
- **Item 2:** top 4 of 12 candidates, score ordering, all-invalid hits give an empty result, and the candidate count never drops below the kept count.
- **Item 3:** a two-way event rendezvous that passes only if both retrievals run at the same time, plus checks that context and errors propagate.

Two existing tests (`test_bedrock_retrieve.py`, `test_source_chunk_artifacts.py`) asserted `numberOfResults == 4`. They now assert 12, because the adapter requests 12 candidates and keeps 4.

Final run on HEAD `4b46822`, same commands and env as the baseline:
- `ruff check .`: **All checks passed**.
- pytest: **2,333 passed, 3 failed, 1 skipped** (143 s). The failures are the same 3 as the baseline: the two `test_notebook_reader.py` tests (need `frontend/dist`) and the flaky `test_source_library` test. The commit-time run of the same tree had 2,334 passed and 2 failed, because the flaky test passed. No new failures against the baseline.

The gate "full mock suite passes" is not literally met. Two failures are environmental (build `frontend/dist` or accept them). The flaky test needs a separate fix.

## (d) Blocked or assumed

**Item 4 (blocked, needs your decision).** The two prompt copies serve different purposes, so I did not merge them.

| Copy | Used by |
|---|---|
| `agentcore_runtime/prompts/` | The deployed AgentCore runtime (`agentcore_runtime/specialists/*`, `structured_coach.py`, `router.py`, `stage_judge.py`) |
| `backend/prompts/` | The FastAPI app: mock, OpenAI and Bedrock Converse providers, and token budgeting for AgentCore |

Evidence:
- `docs/PROMPT_ARCHITECTURE.md` lines 3 to 9 say AgentCore pedagogy is canonical in `agentcore_runtime/prompts/`. `backend/prompts/` remains the composer for mock, OpenAI and Bedrock Converse, and the token-budget stand-in for AgentCore planning. The doc says not to treat them as competing curricula. The `backend/prompts/__init__.py` docstring agrees.
- `agentcore_runtime/prompts` loader states it must not import the `backend` package, because the runtime deploys as its own package with its own requirements file and CI job. The `backend/prompts` loader imports `backend.student_journey.STAGE_BY_ID` and validates stage files against it.
- File sets differ. Only in `agentcore_runtime/prompts`: `fast_chat.md`, `qa.md`, `review.md`, `review_deep.md`, `review_incremental.md`, `router.md`, `shared_coaching.md`, `stage_judge.md`, `stages/ethics_critical.md`. Only in `backend/prompts`: `composer.py` (786 lines, builds the application brief and runtime rules), `shared/coaching.md`, `stages/deep_analysis.md`. The same-named stage files `concept_generation`, `design_specification` and `reflection` differ. `problem_identification.md` is identical.
- Stage naming differs: the runtime uses `ethics_critical`, the app uses `deep_analysis`.
- `backend/agentcore_provider.py`, `bedrock_provider.py`, `mock_provider.py`, `agentcore_harness_provider.py`, `providers.py` and `backend/coaching/execution.py` import `backend.prompts`. `agentcore_runtime/*` imports only its own prompts. `backend/agentcore_provider.py` (around line 1609) imports `agentcore_runtime.structured_coach.specialist_system_prompt` for budgeting. About 12 test files and `scripts/preview_prompt.py` reference `backend.prompts`.

Why it needs your decision: a single source would change what mock, OpenAI and Bedrock Converse send to their models, drop `composer.py`'s rule assembly, or make `backend` depend on the deployable runtime package. Options:
1. Keep both (today's documented design) and add a test that the shared stage files do not drift.
2. Make `backend/prompts` load pedagogy text from `agentcore_runtime/prompts` and keep only the composer logic there. This changes non-AgentCore provider output.
3. Retire the non-AgentCore providers' pedagogy copy entirely.

**Stuck file:** `phase1-stuck.md` does not exist. No piece was stuck after two attempts.

**Assumptions and open points:**
- The 2 + 2 split, the 12-candidate default and the 8,000-character prompt budget note are my choices, with reasons in (b).
- The flaky `test_source_library` test and the two `frontend/dist` tests are not fixed in Phase 1. The flaky cause is a hypothesis only.
- The `.agents/` directory is globally git-ignored (`/root/.config/git/ignore`), so this report and the other task files are on disk only, not in any commit.
- The Knowledge Base itself (data source path, metadata ingestion, filter mode `required`) is Phase 0 and needs your AWS account. Nothing here checked it. The new candidate count and slot split have not been run against a live Knowledge Base.

## (e) Docs updated
- `docs/RAG_ARCHITECTURE.md`: slot reservation, candidate over-fetch and validation, parallel retrieval.
- `docs/PROMPT_ARCHITECTURE.md`: one-line update.
- `.env.example`: `FAST_CHAT_RETRIEVAL_COURSE_SLOTS` and `KNOWLEDGE_BASE_RETRIEVE_CANDIDATES`.

## (f) Final review verdict
`phase1-review.json`: **APPROVED**, no findings (review notes in `phase1-review.md`). Non-blocking notes: with `FAST_CHAT_RETRIEVAL_MAX_CHUNKS=1` the student side gets 0 slots; the two `frontend/dist` failures are environmental.

## (g) Push
- Commits pushed (no force, no PR): `066b66b0b3dca0cd78141d705d52d60b19bbbb27` (chore: ruff cleanup) and `4b46822dc35d7714ac85ac7c91a7bd71fcfea2c4` (fix: items 1 to 3).
- Pushed range: `399c29d..4b46822` on `origin/improvement/backend`.
- Pushed head: `4b46822dc35d7714ac85ac7c91a7bd71fcfea2c4`.
- Pre-push check: both commits have author and committer `CloudKai <kaiming_01@live.com>`, with no Co-authored-by trailer and no "generated by" line.

## Addendum (Part A, after the user's decision): item 4 resolved with Option 1

The user chose Option 1 for item 4: keep both prompt copies and add a drift test. Section (d) above describes the state before that decision. This addendum replaces it for item 4, and it also corrects section (d) and (g) on two points: the `.agents/tasks/phase1-*` reports are now committed with `git add -f`, and the "reports are on disk only" assumption no longer holds.

### What changed
- Neither prompt copy was edited. `agentcore_runtime/prompts/` and `backend/prompts/` are unchanged, so no provider sends anything different to a model.
- New test `tests/domain/test_prompt_stage_drift.py` (5 cases, mock only, no network).
- `docs/PROMPT_ARCHITECTURE.md` now names the test and states what it pins.

### Measured state of the four same-named stage files (at 4b46822)
- `problem_identification.md`: byte-identical (199 lines in both).
- `concept_generation.md`, `design_specification.md`, `reflection.md`: compared paragraph by paragraph (blank-line separated, whitespace collapsed), every backend paragraph exists in the runtime copy. The runtime copy adds exactly two paragraphs in each file, "CORE FOCUS" and "READINESS SIGNALS". In `reflection.md` the optional holistic Facione paragraph also sits before CORE FOCUS in the runtime copy and at the end of the file in the backend copy, so the shared paragraphs are in a different order there. All other shared paragraphs are in the same order.

### What the test pins, and why
Choice: pin the known differences, not full-file equality and not a single shared-section check.
1. The set of stage files present in both folders must equal the four known names. A new same-named file forces a decision.
2. `problem_identification.md` must stay byte-identical.
3. For the other three files: no backend paragraph may be missing from the runtime copy; the runtime-only paragraphs must be exactly the six CORE FOCUS / READINESS SIGNALS blocks, pinned by the first 16 hex characters of the SHA-256 of each normalised paragraph; shared paragraphs must keep the same order, except `reflection.md`, which is listed as a known reorder (the test also fails if that order starts matching, so the allowance does not go stale).

Rationale: full equality would fail on the current tree, since three files already differ. A shared-sections-only check would let one copy change a shared paragraph or the runtime-only blocks without anyone noticing. Pinning the divergences by hash means any edit to a shared stage file in only one copy fails, while an identical edit in both copies passes. To accept an intended divergence, update the constants in the test in the same change. The runtime-only blocks are not required to be copied to the backend copy, because that would change what mock, OpenAI and Bedrock Converse send to their models (Option 1 forbids this).

Not covered: `shared_coaching.md` vs `shared/coaching.md`, and `ethics_critical.md` vs `deep_analysis.md`. These have different names and structure, so the same-name guard does not apply to them.

### Mutation checks (temporary edits, reverted with `git checkout`)
- Appending a line to `backend/prompts/stages/concept_generation.md`: the diverging-file test failed.
- Appending text to `agentcore_runtime/prompts/stages/problem_identification.md`: the byte-identical test failed.
- Editing the wording of the CORE FOCUS paragraph in `agentcore_runtime/prompts/stages/concept_generation.md`: the diverging-file test failed.
- The unmodified tree: all 5 cases pass.

### Status of item 4
Resolved by Option 1. Items 1 to 4 of Phase 1 are now all closed.
