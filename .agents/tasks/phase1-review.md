# Phase 1 review (399c29d...HEAD, commits 4b46822, 066b66b)

Verdict: APPROVED. No blockers.

## Evidence
- Authorship: both commits are `CloudKai <kaiming_01@live.com>` for author and committer. No Kiro or Co-authored-by text in the messages. Branch is ahead of origin by 2, so nothing is pushed.
- Item 1 (slots): `backend/retrieval.py` `split_result_slots` and `_merge_with_reserved_slots` give 2 course + 2 student of the 4-chunk cap, with backfill. `execution.py:2412` is the only consumer of the composite retriever and re-bounds to the same cap, so the merged list is not cut again to the course side's advantage. Setting `FAST_CHAT_RETRIEVAL_COURSE_SLOTS` is bounded 1 to 8. Tests: `test_student_uploads_are_not_crowded_out_by_course_results`, backfill both ways, overrides.
- Item 2 (candidates): `bedrock_retrieve.py` requests `KNOWLEDGE_BASE_RETRIEVE_CANDIDATES` (12 to 16, never below the kept count), sorts by score (stable), validates bucket, key and text, then trims through `bounded_retrieval_result(max_chunks=...)`. Invalid hits cannot take a kept slot because validation runs before the trim. `configured_context_retriever` passes both values. The two old `numberOfResults == 4` assertions are updated to 12 with a stated reason. Tests cover top-4 of 12, score ordering, all-invalid is empty, and the candidate floor.
- Item 3 (parallel): the KB call runs on a one-worker thread with `contextvars.copy_context()`. Local ranking runs on the caller. Errors propagate from `future.result()`. The test uses a two-way event rendezvous, so it passes only if both run at once, and it checks context propagation and error propagation. When only one side is needed the code runs inline, as before.
- Item 4: blocked and documented in `.agents/tasks/phase1-item4-finding.md`. The evidence matches `docs/PROMPT_ARCHITECTURE.md` and the file sets differ (composer, stage names `deep_analysis` and `ethics_critical`, loader import rules). No file was merged or changed for it. This is the instructed outcome, not a defect.
- Verification: commit message records ruff clean and pytest 2334 passed, 2 failed, 1 skipped. The 2 failures are the baseline `test_notebook_reader.py` cases that need `frontend/dist`. The skip is the missing `strands` package. The baseline flaky `test_source_library` test passed this run, which fits its known flakiness. 20 new tests in `tests/domain/test_retrieval_slots.py`. Compared with the baseline, no new failures.
- Ruff cleanup: `PROGRESS_LABELS` is unused in `backend/http/app.py` (it is still imported where used, in `streaming.py`). `add_text_source` is unused in the test. `UploadAdmissionError` is kept with `noqa` because `ui/runtime.py` aliases `ui.services.runtime` and `ui/panels/sources.py` imports it through that alias. This is correct.
- Docs: `RAG_ARCHITECTURE.md`, `PROMPT_ARCHITECTURE.md` and `.env.example` match the new settings and behaviour.

## Non-blocking notes (not findings)
- `FAST_CHAT_RETRIEVAL_MAX_CHUNKS=1` gives the student side 0 slots. Default is 4, and the choices file states the rule.
- `.agents/` is globally git-ignored, so the choices and finding files are on disk but not in the commits.
- The two baseline `frontend/dist` failures remain environmental. The "mock suite passes" gate holds only relative to the baseline.
