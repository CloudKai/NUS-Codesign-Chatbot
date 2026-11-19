# Phase 2 report: measure retrieval

Repo `CloudKai/NUS-Codesign-Chatbot`, branch `improvement/backend`. Base for this phase is Phase 1's head `a40e4f0`. No live AWS, Knowledge Base, Bedrock, AgentCore or OpenAI call was made. Every test and eval below ran on mock providers or offline code.

## Summary

- Phase 2 adds 94 labelled retrieval questions, 295 **synthetic** gate messages, an eval script and tests for it, and a short doc.
- The offline run gives recall@4 of 95.7% (material) and 81.9% (page), a wrong-skip rate of 59.7%, and an empty-result rate of 0.0%.
- The wrong-skip rate is the main finding. The retrieval gate skips about 6 in 10 messages that should retrieve.
- The recall and empty-result numbers come from a lexical stand-in for the Knowledge Base. They do not describe the real Knowledge Base.
- The messages are synthetic, written by one author. They are not real student messages.
- Live Knowledge Base runs were not done. The command to approve is in "Live run for your approval".

## What was built

| Item | Path |
|---|---|
| Question set (94) | `scripts/evals/datasets/retrieval_questions.jsonl` |
| Gate message set (295, synthetic) | `scripts/evals/datasets/retrieval_gate_messages.synthetic.jsonl` |
| Materials manifest (10 PDFs) | `scripts/evals/datasets/course_materials.json` |
| Data docs | `scripts/evals/datasets/README.md` |
| Eval script | `scripts/evals/evaluate_retrieval.py` |
| Tests for the script and live-path refusal | `tests/scripts/test_evaluate_retrieval.py` (22 tests) |
| Data-file tests (earlier commits) | `tests/domain/test_retrieval_question_set.py`, `tests/domain/test_retrieval_gate_message_set.py` |
| How-to doc | `docs/RETRIEVAL_EVAL.md`, linked from `docs/README.md` and `docs/TESTING.md` |
| Flaky-test fix | `tests/domain/test_source_library.py` |

The data files sit in `datasets/`, not `data/`, because `.gitignore` ignores `data/`.

## Data formats

All files are UTF-8. The script validates them on load and stops with a `DatasetError` on a bad row.

**`retrieval_questions.jsonl`**: one JSON object per line, ids `rq001` to `rq094`.

| Field | Meaning |
|---|---|
| `id` | Unique id. |
| `question` | Student-style wording. |
| `expected_material` | Primary `material_id`, for example `lecture_week_10_storytelling`. It is the `course_material_id` the Knowledge Base filter uses. |
| `expected_pages` | 1-based PDF page indexes (not the printed slide number). Sorted, unique, non-empty. Several pages mean any one counts. |
| `alt_expected` | List of `{material, pages, evidence}` for other places that answer equally well. 19 of 94 questions have entries. |
| `evidence` | Verbatim snippet found on a tagged page. A test checks it with PyMuPDF. |
| `kind` | `definition`, `list`, `procedure`, `example`, `detail` or `logistics`. |
| `note` | Where the question came from. |

**`retrieval_gate_messages.synthetic.jsonl`**: one JSON object per line, ids `gm001` to `gm295`.

| Field | Meaning |
|---|---|
| `message` | The student message. |
| `stage` | One of the five Thinking Path stage ids. |
| `selected_sources`, `attachments` | Lists of `{title, filename}`. Selected files persist. Attachments belong to this message only. Course materials never appear here. |
| `history` | Up to 2 earlier turns, `{role, text}`. The gate ignores it. Course search uses it for anaphoric questions. |
| `expected_decision` | `retrieve` or `skip`. This is what the gate should do, not what it does. |
| `expected_scope` | `course`, `student_upload`, `both` or `none`. `none` exactly when the decision is `skip`. |
| `category` | One of 19 categories (list in `datasets/README.md`). |
| `certainty` | `clear` or `borderline`. |
| `follow_up`, `question_id`, `expected_material`, `rationale` | Follow-up flag, link to a question, expected material, reason for the label. |
| `synthetic` | Always `true`. |

**`course_materials.json`**: one entry per PDF with `material_id`, `object_key`, `local_path`, `filename`, `group`, `source_id` and `pdf_pages`. It maps a retrieval result (`source_id` or `title`) back to `material_id`.

**Counts.** 94 questions cover all 10 PDFs. The messages are 154 `retrieve` (107 course, 35 student upload, 12 both) and 141 `skip`. 227 rows are `clear` and 68 are `borderline`.

**Why these sizes.** 94 questions is the number the slide text supports inside the 60 to 100 target. Week 1 (27 of 32 pages) and Week 4 (48 of 83 pages) are mostly images with no extractable text, so they have only 3 and 8 questions. 295 messages keeps the 61 `course_content` and 11 `course_logistics` rows, which mirror the question topics, and gives most of the other 17 categories 10 or more rows.

## All 295 messages are synthetic

I wrote every message by hand to look like a student message. None is real, none comes from logs, and the wording is cleaner and more on-topic than real traffic. A single author labelled them with no second reviewer. Each row has `"synthetic": true`, the file name contains `synthetic`, the data README says so first, and a test fails if any row is not `true`. The `skip` share (48%) is higher than a real traffic mix, so do not read the counts as a traffic mix.

## How the gate was located

The gate is rules-based and calls no model. It runs in FastAPI before the Haiku `fast_chat` call, inside `CoachingExecution._prepare_authoritative_turn` (`backend/coaching/execution.py:2581`). Chat history is not an input, so follow-ups are judged on the message text alone.

| Step | Where | Behaviour |
|---|---|---|
| 1. Classifier | `execution.py:2832` calls `resolve_mode_policy` (`backend/coaching/mode_policy.py:411`), which calls `classify_retrieval_intent` (`backend/retrieval_gate.py:383`) and then `overlay_mode_policy` (`mode_policy.py:360`) | Retrieves on source cues (week or lecture numbers, "the course", material nouns, "according to", citation requests, a selected-file title match), on definitional questions, and on narrow summarise requests when a source is selected. Skips personal reasoning and everything else. |
| 2. Overrides | `execution.py:2843-2900`, `workflow_skips_retrieval` at `backend/coaching/workflow_navigation.py:683` | `lecture_help` forces retrieval. Stage status, stage navigation, meta-guidance and prior-stage review set retrieve to false and clear all sources. |
| 3. Attachments | `execution.py:2905`, `mode_policy.py:312` | A question about a fresh attachment is scoped to the attachments only and forces retrieval. |
| 4. Course catalog | `_wants_course_catalog_retrieval` (`execution.py:237`), `include_course_catalog` at `:2987`, cue set at `:168` | The course Knowledge Base is added only when a cue is in `_COURSE_CATALOG_RETRIEVAL_CUES`. |
| 5. Retrieval runs | `execution.py:3037` via `_retrieve_for_turn` (`:2343`) | Runs only if the final source list is non-empty. |
| 6. Fallback | `_maybe_rag_fallback` (`execution.py:2494`) | If the first pass skipped and the model returned `needs_source_retrieval`, it retrieves once and calls the model again. It needs selected personal sources, never adds the course catalog, and is not modelled in the eval. |

The script's `gate_decision` composes steps 1 to 5 offline, with no store, AWS or model.

**Two gaps found.**
- The cue `definitional_question` is not in `_COURSE_CATALOG_RETRIEVAL_CUES`. For "what is a creative matrix" the classifier says retrieve, but the catalog is not added. With no file selected, nothing is searched.
- The classifier decision is not the real decision. The eval scores the effective decision: retrieve if and only if at least one source is searched. It also prints the classifier-only number.

**Not covered.** The React lecture path (`/lecture/stream`) forces retrieval for every message and does not use the gate. Project mode and the legacy `/coach/turn/stream` use it. This set measures the gate path only.

## Metric definitions

| Metric | Numerator | Denominator |
|---|---|---|
| recall@4 (material) | Questions where one of the top 4 results is in the expected material or in an `alt_expected` material | All questions evaluated (94 offline) |
| recall@4 (page) | Same, and the result page is one of the tagged pages for that material. A multi-page tag needs only one of its pages. | Questions evaluated. Offline only, because only offline results carry a page. An empty result is a page miss. |
| wrong-skip rate | Messages labelled `retrieve` for which the gate searched no source | All 154 messages labelled `retrieve` |
| empty-result rate | Completed retrieval attempts that returned zero results | Completed attempts. Failed live calls are counted separately. |

- **Ties.** Results rank by score descending. Ties break by material order in the manifest, then by page number. The report prints how many questions have a score tie at the rank-4 cutoff (19 offline), so you can see how much the tie rule matters.
- **Multi-page tags.** One page is enough. Slide builds and repeated slides were tagged together when the questions were written.
- **Empty result offline.** The local retriever returns page beginnings when a query has no matching terms. The script discards those, so empty means no lexical match.
- **Two empty-result tracks.** The question track sends each question straight to course search. The gate track searches the messages whose gate decision includes the course catalog. Student-file searches cannot run because the messages hold file names, not file text. The report counts those passes (24) and does not search them.
- **Extras the script also prints.** The false-retrieve rate, wrong-skip with `borderline` rows removed, wrong-skip by category, and recall per material.

## Offline results

Run: `python scripts/evals/evaluate_retrieval.py --json-output /tmp/retrieval_eval.json` with the mock env vars. It takes about 17 seconds and blocks all socket connections. The output is the real output of the script on this commit.

**Retrieval (94 questions, offline lexical stand-in):**

| Metric | Result |
|---|---|
| recall@4, material | 90/94 (95.7%) |
| recall@4, page | 77/94 (81.9%) |
| empty-result rate | 0/94 (0.0%) |
| Questions with a score tie at the rank-4 cutoff | 19 |

Recall@4 by expected material: Week 2 14/14, Week 8 11/11, Week 9 15/15, Readings 1, 2 and 3 8/8, 5/5 and 8/8, Week 7 15/16, Week 4 7/8, Week 10 5/6, Week 1 2/3.

The 4 misses are rq003 ("How many people should be in a team?", expected Week 1; top 4 were all Reading 1), rq024 (persona sections, expected Week 4), rq031 (brainstorming rules, expected Week 7) and rq073 (storyboard examples, expected Week 10).

**Gate (295 synthetic messages):**

| Metric | Result |
|---|---|
| wrong-skip rate | 92/154 (59.7%) |
| wrong-skip rate, `clear` rows only | 67/113 (59.3%) |
| wrong-skip rate, classifier only (before the catalog step) | 85/154 (55.2%) |
| false-retrieve rate (extra) | 2/141 (1.4%) |
| empty-result rate, gate-passed course searches | 0/40 (0.0%) |

Wrong-skip by category: `course_content` 54/61, `course_logistics` 10/11, `informal_or_multilingual` 7/8, `follow_up` 7/9, `upload_question` 11/20, `course_with_unrelated_upload` 1/4, `upload_and_course` 1/12, `named_material` 1/13, `attachment_question` 0/13, `mixed_project_and_course` 0/3.

This matches the sanity check made when the messages were written (62 of 154 retrieved, 2 of 141 false retrieves).

**Reading the numbers.**
- The gate skips most course questions that do not use a cue word such as "week", "lecture" or "according to". Course questions that name a week, a lecture or a reading pass (`named_material` 1/13 skipped). The 2 false retrieves are "how big can my pdf be" (the word "pdf" is a cue) and a project message that says "from the lecture".
- The classifier-only number (55.2%) is lower than the effective one (59.7%) because two effects pull in opposite directions. Of the 154 `retrieve` messages, 17 pass the classifier but nothing is searched: 16 are definitional questions with no cue (for example "what is a creative matrix", "what is the card index method"), which is the catalog gap above, and 1 is "can you show the source for that" with no selected file. In the other direction, the attachment override forces retrieval for 10 messages the classifier alone skips.
- So the definitional-question gap alone accounts for 16 of the 92 wrong skips. Adding `definitional_question` to the catalog cues would turn those into searches. That is a Phase 3 change and was not made here.

## What the numbers do and do not prove

- **Retrieval numbers are for a stand-in, not the Knowledge Base.** The offline course search is `LocalChunkRetriever` (lexical, BM25-style) over PDF text I extracted with PyMuPDF, one chunk per page. The real Knowledge Base uses its own chunking, embeddings, metadata filter and reranking. Recall@4 and empty-result of 95.7% and 0% do not predict the real values. The 0% empty rate is close to structural: with 10 documents and title boosts, a lexical match nearly always exists. A real Knowledge Base with a metadata filter can return nothing, and only a live run shows how often.
- **Page-level recall exists only offline.** Knowledge Base results carry no page in `RetrievedChunk`. I did not check whether the Knowledge Base returns page metadata for these PDFs.
- **The offline search drops near-duplicate pages** in the same document, as production does for Knowledge Base chunks. A hit on an unlisted duplicate slide counts as a miss. Not every repeated slide is listed in `alt_expected`.
- **Questions come from slide text, not from student logs.** Their wording is cleaner than real traffic. Image-only slides are not used.
- **Gate numbers measure the rules against my labels.** They show the gate's rules miss uncued course questions. They do not give the real skip rate on student traffic, because the messages are synthetic, single-author, and the `skip` share is inflated.
- **The gate is deterministic.** Its result does not depend on the mock or live provider, so the gate part of the eval is valid offline. The labels are the weak part, not the execution.
- **Not modelled:** the second-call `needs_source_retrieval` fallback, image bytes, and `interaction_intent` other than normal chat.

## Flaky test: root cause

Test: `tests/domain/test_source_library.py::test_lecture_notes_folder_syncs_updates_and_removes_sources`.

- **Cause.** The sync in `backend/sources/library.py` (`_sync_lecture_notes_folder`, around line 1043) detects a changed file with `signature = f"{stat.st_size}:{stat.st_mtime_ns}"` and compares it with the stored `lecture_note_signature`. It never compares content. The test's two note texts are both 46 bytes, so only `mtime_ns` can signal the rewrite.
- **Evidence.** Timestamps on this host advance in about 10 ms steps (measured gaps of 9,999,974 and 9,999,976 ns on tmpfs). A back-to-back rewrite kept the same mtime in 1,997 of 2,000 tries. The test's two writes are about 5 ms apart, so they fall in the same tick about half the time. Failing run: both writes showed `size=46 mtime_ns=1795078010815037464`, 5.2 ms apart, result `unchanged=1`. Passing run: mtimes 10 ms apart. The original test failed 9 of 20 isolated runs and 3 of 4 baseline full-suite runs.
- **Fix applied (test only, commit `540a120`).** After the rewrite the test sets `os.utime(note, ns=(previous_mtime_ns + 1_000_000_000,) * 2)`. It passed 30 of 30 isolated runs. It passed in the full-suite run for this report.
- **Choice left to you.** The test fix is confined to the test and has no production effect. The sync-code gap remains: a same-size edit within one timestamp tick, or an mtime-preserving copy (`cp -p`, `rsync -t`) over a same-size file, is not picked up. A sync fix would add a content hash (for example sha256) when size and mtime match. It costs a file read per sync and changes sync behaviour. `course_material_fingerprint` in the same file uses the same size and mtime pair. I recommend keeping the test fix and changing the sync code only if lecture notes are really replaced by same-size files with preserved timestamps.

## Verification

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `tests/scripts/test_evaluate_retrieval.py` | 22 passed |
| Full mock suite (`pytest -p no:cacheprovider tests`, mock-ci env vars) | 2 failed, 2,369 passed, 1 skipped |
| Offline eval run | Completed, output above |
| Live path | Refusal checked on the command line and in tests. Not run. |

The 2 failures are the baseline ones: `tests/http/test_notebook_reader.py::test_pilot_serves_only_built_public_assets` and `::test_default_workspace_and_streamlit_gate`. Both need a built `frontend/dist`, which I did not build. The third baseline failure, the flaky sync test, passed in this run, so the count is 2, not 3. It is not a new failure and not a sign of a regression. The root cause above explains why it flipped, and the test fix removes the flake for the test's own rewrite.

One extra check, not committed: I ran `run_live` once with a fake in-process client (5 calls, canned responses) to confirm the live code wires up and parses results. It made no network call.

## Live run for your approval

I did not run this. It makes real Bedrock `Retrieve` calls and costs money, so run it only with your approval. It is off by default. It needs `--live-kb` and `--max-live-calls N` together (N from 1 to 100). Without both, the script prints `refused: ...`, exits with code 2 and makes no call. Tests never reach this path and check the refusal.

```bash
KNOWLEDGE_BASE_ID=<kb id> KNOWLEDGE_BASE_TYPE=managed \
KNOWLEDGE_BASE_METADATA_FILTER_MODE=required \
COURSE_MATERIALS_BUCKET=<course bucket> AWS_REGION=<region> \
  python scripts/evals/evaluate_retrieval.py --live-kb --max-live-calls 30 \
  --json-output /tmp/retrieval_eval_live.json
```

- **Call limit parameter:** `--max-live-calls N`. A wrapper around the client raises when the count reaches N.
- **Calls:** one `Retrieve` per question, no retries, no model call. The 94-question set needs at most 94 calls, so use `--max-live-calls 94` for the full set. Under 94, the script picks an evenly spaced, deterministic subset.
- **Needs:** the settings and AWS credentials from Phase 0 (Knowledge Base id and type, required filter mode, course bucket, region).
- **Reports:** material-level recall@4 and the empty-result rate on the questions evaluated, plus the number of failed calls. Page recall is `n/a`. The gate numbers stay offline.
- **I have not tested the live path against AWS.** Treat the first live run as a check of the script too.

## Assumptions and open points

- **Real student messages.** If you supply anonymised real messages, add them as a separate file without `synthetic` in the name and re-run. The script currently requires `synthetic: true` on the messages file it loads. Loosening that check is a small change.
- **Labels reflect my reading of the course.** Topics the lecture PDFs do not cover (ethics, informed consent, machine learning, "design thinking" and "stakeholder" as definitions) are labelled `skip`. Chinese and Indonesian course questions are labelled `retrieve`. 68 rows are `borderline`. Report results with and without them (59.7% against 59.3% here, so they do not move the headline).
- **Production path scope.** The gate numbers describe normal project chat. The lecture path skips the gate.
- **Gate composition is my reading of `execution.py`.** I composed steps 1 to 5 by hand and cross-checked them with an independent sanity run when the messages were written. It is a copy of the logic. If the backend gate changes, `gate_decision` must follow. A shared helper in the backend would remove the copy. I did not add one, as it was not asked for.
- **Private function import.** The script imports `_wants_course_catalog_retrieval`, a private function, because there is no public gate entry point.
- **Image-only slides.** If Knowledge Base ingestion does OCR or image parsing, more Week 1 and Week 4 questions can be added.
- **Blocked:** nothing. Nothing was skipped because of a blocker.

## Pushed commits

Filled in after push.
