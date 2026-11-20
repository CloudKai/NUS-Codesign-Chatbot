# Retrieval evaluation

`scripts/evals/evaluate_retrieval.py` reports three numbers for course
retrieval: recall@4, wrong-skip rate and empty-result rate. It runs offline by
default.

## Command layout (`scripts/evals/`)

Each eval command is an entry point. **No command imports another command**;
`tests/scripts/test_eval_command_boundaries.py` walks the imports with `ast` and
fails if one does. What commands share lives in `scripts/evals/lib/`, which holds
no `main` and starts no live call on import:

| Module | Holds |
|---|---|
| `paths` | Repo root and the fixed dataset file paths |
| `fixtures` | Course manifest, question and gate-message loading and validation, `eval_course_titles`, `read_training` |
| `metrics` | `rate`, `rate_record`, wrong-skip, false-retrieve and empty-result rates, `interval` (Wilson), `p95_ms`, `evenly_spaced_indices` |
| `output` | The `run` block (`_git_run_metadata`), `write_json_output`, `save` |
| `offline` | `block_network`, `OfflineCourseSearch`, `RankedHit`, `rank_hits`, `accepted_targets` |
| `gate` | `GateDecision`, `scope_inputs_for_row`, `gate_decision` (adapter over `evidence_scope`) |
| `live` | Live-run refusals and errors, `select_live_rows`, `LiveFastChatBridge`, `build_live_request`, failure labels. Builds no client |
| `turn_state` | Laya choice schemas, state text, `decide` |
| `route_scoring` | Routing splits, `observe`, `apply`, `evaluate`, `assess` (takes any `predict` callable, so no model is loaded) |
| `passage_scoring` | Passage `candidates`, `coverage`, `run` (takes an optional encoder or judge) |
| `prepared_rows` | `PreparedRow`, `prepare_rows` (gate once per message, Laya eligibility) |
| `prereg`, `routing_arms`, `arm_metrics`, `arm_report`, `paired_stats`, `kb_scores`, `kb_gate`, `laya_sources`, `intervals`, `extra_messages`, `extra_arms` | Head-to-head comparison: the pre-registered split, T choice and pass rule; arm search decisions; M1 to M5; exact McNemar; KB-score file loader and live gate recorder; stored and all-rows Laya loaders; optional extra messages. See "Head-to-head routing comparison" below |

Model fitting and model loading stay in the command that owns the experiment:
`fit_laya`, `fit_setfit`, `compact_predictors` in `compare_turn_routes`;
`benchmark_pages`, the cross-encoder and the judge in `evaluate_passage_support`;
the Learner fit in `evaluate_laya_turn_decisions` and `evaluate_course_intent_learn`.
The commands re-export the names they used to define (for example
`evaluate_retrieval.gate_decision`, `compare_turn_routes.observe`), so existing
imports keep working. CLI flags, JSON schemas and exit codes did not change.

## Run it offline

```bash
MOCK_OPENAI=true MODEL_PROVIDER=mock OPENAI_API_KEY= USE_LOCAL_API=false \
  python scripts/evals/evaluate_retrieval.py --json-output /tmp/retrieval_eval.json
```

The default path makes no network call, needs no keys and takes about 15
seconds. The script blocks socket connections in offline mode.

Every `--json-output` file, in all three modes (offline, `--live-kb`,
`--live-model`), has a `run` block: `git_sha` (`git rev-parse HEAD`),
`git_dirty` (true when tracked files have uncommitted changes; untracked files
are ignored) and `generated_at_utc` (`YYYY-MM-DDTHH:MM:SSZ`). The git fields
are `null` when git is not available. The offline and `--live-kb` modes share
one writer in `main()`; `--live-model` uses the same helper
(`_write_json_output`). The block is added to the file only, so the printed
report is unchanged. To compare two files, drop `run` first:

```bash
python -c "import json,sys;a,b=(json.load(open(p)) for p in sys.argv[1:]);[d.pop('run',None) for d in (a,b)];print(a==b)" before.json after.json
```

- **Gate.** `gate_decision` (in `scripts/evals/lib/gate.py`, re-exported by the
  script) is a thin adapter. It builds
  `ScopeInputs` from the dataset row (`scope_inputs_for_row`) and calls
  `backend.coaching.evidence_scope.decide_first_pass_scope`, the function
  `backend/coaching/execution.py` calls for a live turn, so the gate cannot
  drift from production. What a row cannot supply stays an explicit input at
  the value the gate always assumed: image bytes loaded, `force_retrieval`
  false, no locked course rows, no frozen Deep Review history. See
  `docs/RAG_ARCHITECTURE.md` (First-pass evidence scope) for the precedence.
- **Course search.** `LocalChunkRetriever` runs over the local lecture PDFs
  with one chunk per PDF page, so results carry a page number. This is a
  lexical stand-in for the Bedrock Knowledge Base. Offline numbers say
  nothing about Knowledge Base quality.
- **Not modelled by the gate numbers.** The second-call fallback
  (`needs_source_retrieval` and the opt-in `needs_sources`; both need a model)
  and image bytes. The report adds a separate block that applies three stub
  models of `needs_sources` on top of the gate. See
  "`needs_sources` second chance" below. A real model measures the same flag
  with `--live-model`; see "Run the `needs_sources` eval against the live
  model".
- **Upload retrieval policy.** The gate numbers are with
  `FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED` off (its default). A separate block,
  `gate.upload_retrieval_policy`, applies the policy rule to every row. See
  "Upload retrieval policy" below.

## Results history

The gate numbers below are for the 295 synthetic messages. Course search is the
offline lexical stand-in, so the recall and empty-result rows describe that
stand-in only. Re-run the script to reproduce each column.

| Metric | Phase 2 baseline | After item 1 (`definitional_question` cue) | After item 2, gate only (flag code, no model) | After item 0 (rq024 label fix) |
|---|---|---|---|---|
| recall@4, material (94 questions) | 90/94 (95.7%) | 90/94 (95.7%) | 90/94 (95.7%) | 91/94 (96.8%) |
| recall@4, page (94 questions) | 77/94 (81.9%) | 77/94 (81.9%) | 77/94 (81.9%) | 78/94 (83.0%) |
| wrong-skip rate | 92/154 (59.7%) | 76/154 (49.4%) | 76/154 (49.4%) | 76/154 (49.4%) |
| wrong-skip rate, clear rows only | 67/113 (59.3%) | 51/113 (45.1%) | 51/113 (45.1%) | 51/113 (45.1%) |
| false-retrieve rate | 2/141 (1.4%) | 7/141 (5.0%) | 7/141 (5.0%) | 7/141 (5.0%) |
| empty-result rate, questions track | 0/94 (0.0%) | 0/94 (0.0%) | 0/94 (0.0%) | 0/94 (0.0%) |
| empty-result rate, gate-passed course searches | 0/40 (0.0%) | 1/63 (1.6%) | 1/63 (1.6%) | 1/63 (1.6%) |

The item 0 column is a label change, not a retrieval improvement. Question
rq024 ("What sections should a persona have?") gained an `alt_expected` entry
for `reading_reading_2_engaging_personas` page 2, which lists what to include
when describing a persona (evidence: "A few fictional personal details to make
the persona a realistic character"). Search results did not change. The retrieved
reading was already a correct answer and is now counted as one. Recall@4 rises
by one question (material and page) and no other number moves, including the
gate numbers (wrong-skip and false-retrieve), which do not read the question
set.

Phase 3b item B (page numbers on citations) does not change retrieval, so
every number in the item 0 column is unchanged by it. The offline JSON report
has the same content as the one taken before the change.

The item 2 column is identical to item 1 by design. `needs_sources` does not
change the first-pass gate, so the gate numbers cannot show its effect. The
effect is a second chance after the first model call, which needs a model.

Item 1 added `definitional_question` to `_COURSE_CATALOG_RETRIEVAL_CUES` (now in `backend/coaching/evidence_scope.py`). All 16
known wrong skips of that kind now search the course catalog (for example "what
is a creative matrix"). The cost is 5 new false retrieves, all impersonal
"what is / explain / what does X mean" messages that are not course questions:
"what does the stage bar mean", "explain that more simply", "explain", "what is
the capital of Australia" and "what does stakeholder mean". Four of the five
are `borderline` rows. The capital question is `clear` and is also the one new
empty result. Recall@4 does not move, because it scores
each question sent straight to course search and never passes through the gate.

## `needs_sources` second chance (stub models, offline)

Item 2 adds an optional `needs_sources` field to the first Fast Chat call
(`FAST_CHAT_NEEDS_SOURCES_ENABLED`, default off; see
`docs/RAG_ARCHITECTURE.md`). The report's `needs_sources_stubs` block applies
three **stand-ins for the model** on top of the unchanged gate. A message is
**eligible** when the gate searched nothing and no override fixed its evidence
scope (stage status, navigation, meta-guidance, private attachment). A flagged
message is searched on the second pass (selected sources plus the course
catalog).

| Stub | Flags | Role |
|---|---|---|
| `oracle` | exactly the messages labelled `retrieve` | Best case: a perfect model. |
| `mock_rule` | eligible messages phrased as a question or information request, except first-person or project reasoning | The mock provider's deterministic rule. Crude. |
| `flag_all` | every eligible message | Worst case: a model that over-flags. |

Results on the 295 synthetic messages (189 are eligible, and all 76 current
wrong skips are eligible):

| Metric | Gate only | `oracle` | `mock_rule` | `flag_all` |
|---|---|---|---|---|
| wrong-skip rate | 76/154 (49.4%) | 0/154 (0.0%) | 19/154 (12.3%) | 0/154 (0.0%) |
| false-retrieve rate | 7/141 (5.0%) | 7/141 (5.0%) | 39/141 (27.7%) | 120/141 (85.1%) |
| empty-result rate, course searches | 1/63 (1.6%) | 2/139 (1.4%) | 7/152 (4.6%) | 18/252 (7.1%) |
| second model calls | 0 | 76 | 89 | 189 |

The eligible count (189) is an approximation. The eval's `second_chance`
flag mirrors the server stamp rule but leaves out three overrides that the
application applies: Lecture Help, forced retrieval and missing-image Q&A.
The real eligible count can differ slightly.

The flag is honoured only when the model returns a Q&A turn. A flagged
coaching turn is ignored and keeps its first reply, assessment and
recommendation (see `docs/RAG_ARCHITECTURE.md`). The stubs do not model the
returned mode, so `mock_rule` approximates "the model judged this a coaching
turn" with the project-reasoning exclusion. A real model that labels a
no-cue course question as coaching would not get the second chance, so the
real wrong-skip reduction can be smaller than the stub rows suggest.

What this proves: every current wrong skip is reachable by the second chance,
so the flag can in principle close the gap. The cost scales with how often the
model flags: each flagged message adds a Retrieve and a second model call. The
range runs from 76 calls (a perfect model) to 189 (flag everything).

What it does not prove: how a real Haiku call behaves. The stubs are not
models, the labels are synthetic and single-author, and the empty-result rate
uses the lexical stand-in for the Knowledge Base. The real flag rate, its
precision, the added latency and the cost need a measured run with the live
model and an approved call limit. The `--live-model` mode below is that run;
it has not been run yet.

## Upload retrieval policy (Phase 3c item 4, offline)

`FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED` (default off; rule in
`docs/RAG_ARCHITECTURE.md`, "Upload retrieval policy") searches the selected
student uploads when the gate skipped and the turn is not navigation or
chit-chat. The excerpt ranking is local (no Bedrock or Knowledge Base call);
loading the uploads can add one S3 GET per selected upload on a chunk-cache
miss, or every such turn on the extracted-text fallback. This block does not
measure those reads. The report's `gate.upload_retrieval_policy` block applies the
production rule (`wants_student_upload_retrieval` in
`backend/coaching/evidence_scope.py`, reached through
`decide_first_pass_scope` with the setting on, not copied) to every gate row. The row's selected and attached files are projected into
source dicts, with the image check taken from the filename extension (rows
hold only a title and a filename). The main gate numbers and
`needs_sources_stubs` stay computed with the policy off.

A row counts as retrieved when a source is searched, the gate's existing
definition. No file is searched offline: the gate rows hold file names, not
file text. So the block cannot say whether the search finds the right
passage, and a course-scope row that only searches an unrelated upload
(gm142, "what is dot voting") counts as fixed. The block lists those rows in
`fixed_wrong_skips_course_scope_only`.

Results on the 295 synthetic messages (script run). The policy fires on 18
rows, each with one upload:

| Category | Wrong-skip before → after | False-retrieve before → after | Rows fired | Extra prompt chars (estimate) |
|---|---|---|---|---|
| upload_question | 11 → 0 of 20 | n/a (no skip rows) | 11 | 43,184 |
| follow_up | 7 → 5 of 9 | 1 → 1 of 7 | 2 | 7,856 |
| upload_and_course | 1 → 0 of 12 | n/a | 1 | 3,928 |
| course_with_unrelated_upload | 1 → 0 of 4 (course scope only) | n/a | 1 | 3,928 |
| ambiguous_generic | n/a (no retrieve rows) | 1 → 4 of 9 | 3 | 11,778 |
| every other category | unchanged | unchanged | 0 | 0 |
| **Overall** | **76/154 (49.4%) → 61/154 (39.6%)** | **7/141 (5.0%) → 10/141 (7.1%)** | **18** | **70,674** |

- Upload question misses fixed: 11 of 11.
- Wrong skips fixed (15): gm098, gm099, gm101, gm102, gm103, gm104, gm107,
  gm108, gm109, gm111, gm114, gm137, gm142, gm267, gm268. gm142 is a course
  question with an unrelated upload: only the Knowledge Base can answer it,
  and the policy does not add the Knowledge Base.
- New false retrieves (3): gm276 "what do you think?", gm277 "?" and gm282
  "any feedback?", all `ambiguous_generic` with an upload selected. They get
  upload excerpts they do not need. The reply stays a coaching reply; no
  evidence-gap text is added, because that text is used only for Q&A turns
  and course gaps.
- `needs_sources` interaction: all 18 rows are eligible for the second chance
  today, and a policy turn is not sent the source check. With both settings
  on, 2 of them (gm137 `both`, gm142 `course`) lose the course-catalog second
  chance.

**Extra prompt characters are an estimate (upper bound).** For each fired
row the script builds the request production would send, then the same
request with `min(FAST_CHAT_RETRIEVAL_MAX_CHUNKS, 2 x uploads)` full-size
chunks (`LocalChunkRetriever` defaults: 1,800 characters, at most 2 per file)
with the row's real titles, formatted by `bounded_retrieval_result` within
`FAST_CHAT_RETRIEVAL_MAX_CHARS` (8,000). Both requests go through the
provider's payload builder (never invoked). The difference counts
`trusted_instructions` (the "Grounding mode" paragraph), the message text
(the excerpt block replaces the empty-context placeholder) and the compact
`runtime_context` JSON (allowed citation labels). Results: 3,916 to 3,928
characters per fired turn with one file (mean 3,926.3), about 980 tokens at 4
characters per token and about 1,310 at 3. With two or more files: 4 chunks,
about 7,650 characters (about 1,910 to 2,550 tokens). Averaged over all 295
rows: 240 characters per turn (70,674 / 295), about 60 to 80 tokens. Real
files can be shorter or match fewer chunks. The excerpts are per-turn
content, so none of it is cached.

## Follow-up cases (Phase 3b item C)

`retrieval_gate_followups.synthetic.jsonl` holds 12 short follow-up messages
(9 labelled `retrieve`, 3 labelled `skip`), each with the earlier turns it
depends on in `history`. The file is separate from the 295 gate messages, so
the 295-message numbers above are unchanged. Row format and validation are the
same as the gate messages (ids `gm296` to `gm307`). Each `retrieve` row links
through `question_id` to the standalone question that asks the same thing.
The offline run adds a `followups` block to the report and the JSON. The
`--followups PATH` option points it at another file.

**What query building does with history.** The gate reads the message only.
For course search, `BedrockKnowledgeBaseRetriever` sends
`contextual_course_query_text` (`backend/retrieval.py`) plus the Week/Lecture
alias expansion. That function adds the nearest substantive earlier **user**
message only when the current message has a course-source word ("lecture",
"reading", "source", ...), a reference such as "that" or "what I just said",
and a question form. Any other follow-up is sent as the bare message, and
assistant turns are never used. The local retriever used for student uploads
additionally weights the last two user turns, which the Knowledge Base path
does not do.

**Definition of "clearly fail"** (recorded in the item C notes before the cases
were added or measured). Rewriting is justified only if at least 5 of the 9
`retrieve` cases fail end to end **and** at least 5 of those failures are
attributable to the follow-up form. End to end means the gate searches the
course and the top 4 results for the built query hold the expected material.
A failure is attributable when the linked standalone question passes both
checks. The search gets only the built query text, as the Knowledge Base does.

Result (offline, lexical stand-in for the Knowledge Base):

| Measure | Result |
|---|---|
| Gate wrong-skip, `retrieve` follow-ups | 8/9 (88.9%) |
| Gate false-retrieve, `skip` follow-ups | 0/3 (0.0%) |
| Built query differs from the bare message (history used) | 1/9 (11.1%) |
| Built query finds the expected material in the top 4 | 6/9 (66.7%) |
| End to end (gate and query) | 1/9 (11.1%) |
| Standalone control passes (gate and query) | 4/9 (44.4%) |
| 5-and-5 rule | 8 failures, 3 attributable: **not clearly failing** |
| If a perfect `needs_sources` model recovered every gate miss (informational) | 6/9 pass, 2 attributable failures |

The cases do not clearly fail, so follow-up rewriting was not implemented. Five
of the 8 end-to-end failures also fail the standalone question at the gate
(no course-word cue: the known gap that `needs_sources` addresses), so
a rewriter would not fix them. The 3 attributable failures are gm296 "what is
it good for?", gm297 "what are the axes?" and gm303 "and the F-pattern?". Two
of them also have a query that misses the expected material.

Limits: 12 synthetic cases from one author; the offline search is lexical, so
the query check says whether the query text carries enough content for a
lexical match, not how the real Knowledge Base ranks it. Some passes are
lucky matches on one distinctive word ("authority", "focus"). The Knowledge
Base was not called.

## Metric definitions

| Metric | Numerator | Denominator |
|---|---|---|
| recall@4 (material) | Questions where one of the top 4 results is in the expected material or in an `alt_expected` material. | All questions evaluated. |
| recall@4 (page) | Same, and the result page is one of the tagged pages of that material. A multi-page tag needs only one of its pages. | Questions evaluated. Reported only for questions whose results carry a page (offline: all; live: those with at least one paged result). An empty result is a page miss. |
| wrong-skip rate | Messages labelled `retrieve` for which the gate searched no source. | All messages labelled `retrieve`. |
| empty-result rate | Completed retrieval attempts that returned zero results. | Completed attempts. Failed live calls are counted separately. |

Rules:

- **Ranking.** Results are ranked by score, highest first. Ties break by
  material order in `course_materials.json`, then page number. The report
  prints how many questions have a score tie at the rank-4 cutoff.
- **Effective gate decision.** The gate "retrieves" only when at least one
  source is searched: the course catalog or a selected or attached student
  file. The classifier saying "retrieve" is not enough. The report also prints
  the classifier-only wrong-skip rate to show the difference.
- **Empty result, offline.** A chunk with no lexical match (score 0) is not
  a result. The local retriever's fallback of returning page beginnings for a
  query with no matching terms is discarded.
- **Empty result, two tracks.** The questions track sends each question to
  course search directly (gate bypassed). The gate track searches only the
  messages whose gate decision includes the course catalog. Messages that
  search only student files are counted but not searched, because the data
  holds file names, not file text.
- **Extras.** The report also prints the false-retrieve rate (messages
  labelled `skip` that were searched), wrong-skip with `borderline` rows
  removed, wrong-skip by category, and recall per material.

## Data formats

All files are in `scripts/evals/datasets/`. Field tables and labelling rules
are in that folder's `README.md`.

| File | Content |
|---|---|
| `retrieval_questions.jsonl` | 94 questions. Fields: `id`, `question`, `expected_material`, `expected_pages` (1-based PDF pages), `alt_expected`, `evidence`, `kind`, `note`. |
| `retrieval_gate_messages.synthetic.jsonl` | 295 **synthetic** student messages. Fields: `id`, `message`, `stage`, `selected_sources`, `attachments`, `history`, `expected_decision` (`retrieve` or `skip`), `expected_scope`, `category`, `certainty`, `follow_up`, `question_id`, `expected_material`, `rationale`, `synthetic` (always `true`). |
| `retrieval_gate_followups.synthetic.jsonl` | 12 **synthetic** follow-up cases, same row format as the gate messages, ids `gm296` to `gm307`, each with prior turns in `history`. Reported apart from the 295 messages. See "Follow-up cases". |
| `course_materials.json` | One entry per lecture PDF: `material_id`, `object_key`, `local_path`, `filename`, `group`, `source_id`, `pdf_pages`. |

The script validates these files on load and stops with a `DatasetError`
if a row breaks the format. `tests/scripts/test_evaluate_retrieval.py`
checks the metric maths, the data files (60 to 100 questions, at least 200
messages, unique ids, synthetic marker, label vocabulary) and that the live
path refuses to run.

## Run it against the live Knowledge Base (opt-in, costs money)

Live mode is off by default. It runs only when **both** `--live-kb` and
`--max-live-calls N` are given, with N from 1 to 100. Without both, the script
prints `refused: ...`, exits with code 2 and makes no call. Pytest never uses
this path. Run it only with approval.

```bash
KNOWLEDGE_BASE_ID=<kb id> KNOWLEDGE_BASE_TYPE=managed \
KNOWLEDGE_BASE_METADATA_FILTER_MODE=required \
COURSE_MATERIALS_BUCKET=<course bucket> AWS_REGION=<region> \
  python scripts/evals/evaluate_retrieval.py --live-kb --max-live-calls 30 \
  --json-output /tmp/retrieval_eval_live.json
```

Use the same Knowledge Base settings as production. AWS credentials come from
the normal credential chain.

- **Calls.** One Bedrock `Retrieve` call per question, with no retries and no
  model call. A wrapper around the client raises when the count reaches
  `--max-live-calls`.
- **Subset.** With a limit below the number of questions, the script uses an
  evenly spaced, deterministic subset of the question file.
- **Reported.** Material-level recall@4 and empty-result rate on the questions
  evaluated. Failed calls (`unavailable`) are listed in `failed_attempts`.
  Page-level recall (`recall_at_4_page`) is filled for questions whose results
  carry a page and is `n/a` when none do. See "Page numbers from the Knowledge
  Base" below. The report also prints `page_coverage`: results with a page,
  and questions scored at page level.
- **Gate.** The gate numbers still come from the offline gate and make no call.
- **Run block.** The JSON file carries `run` (git SHA, dirty flag, UTC
  timestamp), as in offline mode. The row filters of `--live-model` do not
  apply here and are refused.

`--live-kb-gate` (one Retrieve per gate message, cap 295, for the head-to-head comparison)
is a separate mode with its own refusals; see "Head-to-head routing comparison" below.

## Page numbers from the Knowledge Base

Course citations show `S1 · Title, p. 4` when the Knowledge Base reports a
page, and `S1 · Title` when it does not. The eval convention for pages is the
1-based PDF page index (`expected_pages`), the same number a PDF viewer shows.

**Where the page comes from.** Each Retrieve result has a `metadata` map (a
string-to-JSON-value map in the
[KnowledgeBaseRetrievalResult reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_KnowledgeBaseRetrievalResult.html)).
The adapter reads one key, `x-amz-bedrock-kb-document-page-number`
(`backend/bedrock_retrieve.py`, `PAGE_NUMBER_METADATA_KEY` and `_result_page`).
The `location` field carries no page: `s3Location` holds only the S3 URI
([RetrievalResultS3Location](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_RetrievalResultS3Location.html)).

| Point | Status |
|---|---|
| `metadata` is returned on Retrieve results, as a string-to-JSON-value map | Documented (API reference above). |
| The attribute name `x-amz-bedrock-kb-document-page-number` exists, and a knowledge base that uses "no chunking" cannot show or filter on it | Documented, in [How content chunking works](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking-parsing.html). The same page says the chunker respects page boundaries for parsed content. |
| The value type (number or string) | Not documented. The parser accepts an int, an integral float and a digit string. Anything else (zero, negative, fraction, bool, text) means no page. |
| The number is 1-based and equals the PDF page index | **Assumed.** The docs do not say. The live eval is the check (below). If the numbers come back 0-based, set `KNOWLEDGE_BASE_PAGE_CITATIONS_ENABLED=false` rather than show a wrong page. A `0` value is dropped as no page. |
| This project's Knowledge Base returns the attribute for its PDFs | **Unverified.** The Knowledge Base is `MANAGED` (`KNOWLEDGE_BASE_TYPE=MANAGED`). An AWS re:Post answer (community, not official documentation) says the attribute is produced by the default parser and is missing when a managed parser such as Bedrock Data Automation is used, and an older re:Post answer says KBs did not store page numbers at all. Nobody has checked this Knowledge Base. If it returns none, every citation shows no page and nothing breaks. |
| One chunk maps to one page | Assumed from the chunking note above. A chunk that spans pages would report one number. |

**Citation text format.** `S1 · Title, p. 4`. The chip under an answer and the
evidence heading both use it (`citationText` in `frontend/src/stream.ts`). The
`[S1]` marker inside the reply text is unchanged. The page is not placed in the
model-facing excerpt header, so the model cannot write a page it was not given
or break the `[S#]` parser. A citation takes the page of the strongest chunk of
its source, which is the chunk whose excerpt the preview shows.

**When no page is available.** The citation shows no page text at all (no
"page unknown"). Saved citations from before this change have no page and
render as before.

**Switch.** `KNOWLEDGE_BASE_PAGE_CITATIONS_ENABLED` (default `true`) drops the
page when the adapter builds each chunk. It does not change which chunks are
returned, their order or their filtering. The live eval ignores the switch and
always reads the page, so it can measure the Knowledge Base while production
has pages hidden.

**Live page recall.** `--live-kb` now sets `recall_at_4_page`. A question is
scored at page level when at least one of its results carries a page. A hit
counts when its page is one of the tagged pages of an accepted material. A
question whose results carry no page is left out of the page denominator (it is
not a miss), so a Knowledge Base that returns no pages still reports `n/a`.
The report prints `page_coverage` (results with a page of all results, and
questions scored at page level). Read page recall together with coverage. If
recall@4 (material) is high and page recall is far lower on questions with
good coverage, suspect an off-by-one numbering before blaming retrieval.

## Local course-intent classifier

Laya is an opt-in FastAPI classifier for ambiguous chat turns with no existing
evidence route. It scores the current message against course topics and the
notebook's locked course titles before generation. Existing source selections
and workflow routes take precedence. When the score meets the configured
threshold, FastAPI uses the existing course retrieval and grounded Q&A path.
When the classifier is busy or inference fails, the original gate applies.

Install `laya==0.4.37` in a separate environment with the project
requirements and download a pinned Laya checkpoint to a local directory.
The following benchmark blocks sockets and scores the same 169 synthetic rows
as the Phase 3c wording comparison. It records per-row scores, baseline and
candidate error rates, model load time, inference p95, and busy abstentions.

```bash
python scripts/evals/evaluate_course_intent.py \
  --checkpoint /path/to/checkpoint --json-output /tmp/laya-routing.json
```

Use `--concurrency` to measure contention and `--threshold` to choose the
course-evidence cutoff. For a local FastAPI demo, point
`LOCAL_COURSE_INTENT_CHECKPOINT` at that directory and restart the API in the
environment where Laya is installed. The default threshold is 0.8. To disable
the classifier, clear the checkpoint setting and restart the API.

### Fit and evaluate Laya Learn

Use `laya==0.4.38` with `vegaml==0.17.1` in the experiment environment.
Download a pinned Vega checkpoint and put the matching local reader snapshot
at `backbone/` inside the checkpoint directory. For the default Vega-U reader,
use `nandakishorm/vega-U` with `Qwen/Qwen3.5-0.8B`. Both directories must
include their configuration and weights. The benchmark disables network I/O
and reads only the checked-in synthetic labels.

```bash
python -m scripts.evals.evaluate_course_intent_learn \
  --checkpoint /path/to/vega \
  --bundle-output /tmp/course-learner.zip \
  --json-output /tmp/course-learner-eval.json
```

The script groups linked questions and duplicate messages before splitting into
training, calibration, and holdout. The learner fits turns eligible for the local classifier. Each model's threshold is chosen on calibration rows under the
10% false-retrieve target. Holdout metrics include all routes and report whether
the loaded learner used its fitted head or the Vega engine.

For an opt-in FastAPI demo, set `LOCAL_COURSE_INTENT_CHECKPOINT` to the Vega
directory and `LOCAL_COURSE_INTENT_LEARNER_BUNDLE` to the generated ZIP.
Set `LOCAL_COURSE_INTENT_THRESHOLD` to the candidate cutoff under evaluation.
To use separate calibration for opening questions, set the threshold to the
reported `learn` value and `LOCAL_COURSE_INTENT_FIRST_TURN_THRESHOLD` to
`learn_first_turn`. This second cutoff applies until the first student turn
has been saved. Omitting it uses one cutoff everywhere.
The API loads a fixed bundle. Fitting and feedback are offline.

### Evaluate evidence scope, coach mode, and excerpt sufficiency

Run from the repository root with Python 3.12. Use two experiment environments
with the project requirements installed. The Laya environment uses the Vega
setup above. For the compact environment, install the following versions.
These dependencies belong to the offline evaluator.

```sh
python -m pip install setfit==1.1.3 sentence-transformers==3.4.1 transformers==4.57.6 \
  torch==2.8.0 datasets==5.0.1 onnx==1.23.2 onnxruntime==1.32.0 scikit-learn==1.9.1
```

Download the two public checkpoints before starting the evaluator. The measured
MiniLM encoder was `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
at `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. The reranker was
`cross-encoder/ms-marco-MiniLM-L-6-v2` at `233902d25c440f23af6f7d6e94d2946bac0bee0a`.
The measured Vega-U revision was `4d2050287982ca7a7bb0c22fd19a389f5f94474e`
with Qwen reader `2fc06364715b967f1860aea9cf38778875588b17`.

```sh
hf download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
  --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 --local-dir /tmp/route-mini \
  --exclude 'onnx/*' 'openvino/*' '*.bin' '*.h5' '*.ot'
hf download cross-encoder/ms-marco-MiniLM-L-6-v2 \
  --revision 233902d25c440f23af6f7d6e94d2946bac0bee0a --local-dir /tmp/route-ranker \
  --exclude 'onnx/*' 'openvino/*' '*.bin' '*.h5' '*.ot'
```

Set `LAYA_PY` and `COMPACT_PY` to the two Python executables and `VEGA` to the
local Vega directory containing its backbone. Choose a new experiment directory.
The four evaluation commands disable network connections.

```sh
RUN=artifacts/evals/turn-comparison-reproduction
"$LAYA_PY" -m scripts.evals.compare_turn_routes laya \
  --checkpoint "$VEGA" --output-dir "$RUN/laya"
"$COMPACT_PY" -m scripts.evals.compare_turn_routes compact \
  --checkpoint /tmp/route-mini --output-dir "$RUN/compact"
"$COMPACT_PY" -m scripts.evals.evaluate_passage_support rank \
  --checkpoint /tmp/route-ranker --output "$RUN/ranking.json"
"$LAYA_PY" -m scripts.evals.evaluate_passage_support judge \
  --checkpoint "$VEGA" --bundle artifacts/evals/laya-turn-decisions-sol/evidence.zip \
  --rank-report "$RUN/ranking.json" --output "$RUN/judge.json"
```

To recreate the earlier sufficiency bundle, run
`"$LAYA_PY" -m scripts.evals.evaluate_laya_turn_decisions --track evidence --checkpoint "$VEGA" --output-dir "$RUN/evidence"`
and use `"$RUN/evidence/evidence.zip"` in the judge command.

**Routing labels and policies.** Both models see the current message, selected
titles and up to four prior user/assistant messages. The 70 training turns
include 32 Sol-authored turns in eight matched families. Ten calibration turns
in two further families select the highest cutoff tied for best effective
accuracy for each head. A cutoff above one always defers to the gate. The
25 fresh turns in four other families have direct scope and response-mode
labels, assigned separately from Sol's training work before scoring. These
are synthetic, model-authored labels without human adjudication. The old 307
turns supply regression scope scores. Their inferred modes are excluded from
mode accuracy. [Datasets](../scripts/evals/datasets/)

The reference policy always serves the gate. The second policy allows an
override when a file is selected or a saved user message exists. Explicit
mode, workflow and attachment routes retain precedence. Unavailable sources
and below-cutoff scores fall back to the gate. The JSON records both heads'
raw probabilities and the effective decisions. The Laya routing experiment
uses the calibrated maximum probability. The sufficiency evaluation honors
Laya's own abstention decision.

SetFit contrastively tunes a shared encoder on joint scope/mode labels for
24 steps, then fits a logistic head. Native and ONNX sum joint probabilities
for each head. ONNX includes pooling and the linear head and uses the same
tokenizer. The latency probe measures eight warmed waves at one and eight
simultaneous requests, with one inference slot and immediate gate fallback
when busy. Read the busy counts alongside p50 and p95. The slice intervals
are descriptive 95% Wilson intervals per turn. Related turns within families
limit generalization.

Advance only on a fresh exact-scope gain, unnecessary searches below 10% of
gold skips, misses below 25% of gold retrievals, and preserved explicit scopes.
If both qualify, use lower single-request CPU p95 to select the shadow candidate.
The serving gate continues to answer students during any future shadow trial.

**Passages.** The lexical retriever supplies up to eight authorized PDF pages.
The cross-encoder reorders that same pool. The 94 course questions have
existing expected-page labels. Four additional questions have independent
fact-support annotations for 32 returned passages, including a mixed question
whose project source is missing. The evaluator checks document, page and
content hashes for the first 1,800 characters of each returned passage.
It scores individual passages and the union of facts in the first four.
The judge sees those same texts. Coverage and false-sufficient counts include
abstentions in their stated denominators. [Fact annotations](../scripts/evals/datasets/passage_fact_labels.json)

## Run the `needs_sources` eval against the live model (opt-in, costs money)

`--live-model` sends each gate message through the first Fast Chat call on the
real Haiku model, with the SOURCE CHECK rule on, and measures the real
`needs_sources` flag. It runs only when **both** `--live-model` and
`--max-live-calls N` are given, with N from 1 to 500. Without both, or with
`--live-kb` as well, or when the settings below are not a Haiku model on the
`bedrock` provider, the script prints `refused: ...`, exits with code 2 and
makes no call. Pytest never uses this path (it uses a stub client). Run it only
with approval.

```bash
COACHING_MODEL_PROVIDER=bedrock \
COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0 \
AGENTCORE_MODEL_REGION=us-west-2 \
  python scripts/evals/evaluate_retrieval.py --live-model --max-live-calls 295 \
  --json-output /tmp/needs_sources_live.json
```

The three variables are the values in `.env.example`. If the shell already
exports them (or `.env` does), only the script call is needed. AWS credentials
come from the normal credential chain.

**What is sent.** For each message the script builds the `CoachRequest` that
`_prepare_authoritative_turn` would stamp (stage, selected sources and
attachments as ids and titles, mode policy, `retrieval_required`,
`allow_model_knowledge`, history) and passes it to
`AgentCoreCoachProvider._invoke_payload`. That is the production code that
composes the runtime rules (including the SOURCE CHECK paragraph), plans the
history and builds the Converse messages. The script then makes the call the
AgentCore runtime makes: system prompt from
`agentcore_runtime.structured_coach.specialist_system_prompt` (static fast-chat
prefix, runtime rules, output contract), the same Converse messages, and the
`FastChatTurnOutput` schema as one forced tool (`toolChoice: any`). The reply is
parsed with `parse_fast_chat_turn_output` and checked by
`backend.agentcore_provider._validated_fast_chat`, so mode enforcement,
`out_of_scope` and the rule that only a Q&A turn honours the flag are the
production code.

**Differences from production.** AgentCore Runtime is not invoked (the provider
gets a client that raises if it is used). The call goes to `bedrock-runtime`
`converse` directly because Strands is a runtime-only dependency. There is no
guardrail, no prompt-cache point and no structured-output recovery turn: a reply
without a valid tool call is recorded as a failure. There are no SDK retries.
The tool schema is the Pydantic schema with `$ref` entries inlined; Strands'
own conversion is not available here, so the first run also checks that Bedrock
accepts the schema.

**Which rows are sent.** All gate messages, or the rows the filters select (see
"Choose rows" below), sequentially, one call each, up to `--max-live-calls`.
Below the selected row count the script sends an evenly spaced, deterministic
subset of the selected rows. History is the `history` field of the row (16 follow-up
rows have two turns). No retrieved excerpts are attached to any row. Production
stamps the SOURCE CHECK rule only on rows the gate searched nothing for. The eval
turns it on for every row so each row has a flag, but only **eligible** rows
(the same `second_chance` rule as `needs_sources_stubs`) can change a metric. The
flag on a row the gate already searched is reported in the raw flag rate only.

**Metrics.** Composition is the one in `needs_sources_stubs`: a message counts as
retrieved when the gate searched a source, or when it is eligible and the
honoured flag is true. The honoured flag is the raw flag on a Q&A turn that is
not `out_of_scope`. A raw flag on a coaching turn is not honoured; the report
counts those (`raw_flags_not_honoured`, `flag_ignored`). Rows whose call failed
are not scored in `overall` and `by_category`; failures are counted per
category. `overall_failed_in_denominator` keeps every sent row in the
denominator in two readings (see "Failed calls" below).

| Reported | Meaning |
|---|---|
| flag rate (eligible, honoured) | Honoured flags divided by eligible rows. |
| flag rate (raw, all rows sent) | Raw flags divided by all scored rows. |
| wrong-skip, gate only / with model | On the same scored rows. |
| false-retrieve, gate only / with model | Also for clear rows only. A `skip`-labelled eligible message with a true flag is one false retrieve and one extra call, and is listed in `false_flags`. |
| extra model calls | Honoured flags on eligible rows. Each one is a second model call in production. |
| per category | The same fields for each `category`, with messages sent and failed. |
| `missed_flags` | Retrieve-labelled eligible rows the model did not flag (the remaining wrong skips). |

A stub client that uses the mock provider's rule reproduces the offline
`mock_rule` row exactly (19/154 wrong skips, 39/141 false retrieves, 89 extra
calls); a test pins that, so the live composition and the offline maths agree.

**Failure handling and exit codes.** The script stops after the first auth or
access error (access denied, expired or invalid credentials, missing
credentials) because every later call would fail the same way. It prints the
exception class and AWS error code of the first failure of any kind (never the
message body) and saves it as `first_failure`. Exit code 0: the run completed.
Exit 1: every call failed. Exit 3: it stopped early on an auth or access error
after at least one success. Exit 2: refused before any call.

**IAM.** The caller needs `bedrock:InvokeModel` (the Converse API is authorised
by that action). The model id in settings is a global cross-Region inference
profile (`global.` prefix), so an inference-profile ARN is required, plus the
foundation-model ARNs AWS lists for global profiles. For
`global.anthropic.claude-haiku-4-5-20251001-v1:0` called in `us-west-2`:

- `arn:aws:bedrock:us-west-2:<ACCOUNT>:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0`
- `arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`
  (condition `bedrock:InferenceProfileArn` equal to the profile ARN above)
- `arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`
  (same condition, `aws:RequestedRegion` equal to `unspecified`)

See the three-statement policy in the AWS page
[Global cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html).
The script makes no other AWS call.

**Cost.** One Haiku call per message. Each call sends the fast-chat system prompt
(18,600 to 30,300 characters depending on the stage), the message, history and
the tool schema: 22,700 to 34,500 characters in all, so roughly 5,700 to 8,600
input tokens at 4 characters per token. It returns roughly 100 to 300 output
tokens. At 295 calls that is about 2.1 million input tokens (measured offline by
building all 295 requests) and under 0.1 million output tokens. At Haiku 4.5 list prices (about $1 per million input
and $5 per million output tokens) that is a few dollars. The hard ceiling is
295 calls at the 16,000-token input limit and the 4,000-token output cap, about
$11. The report prints the real token totals. The run is sequential, about
2 to 5 seconds per call, so 10 to 25 minutes. The second calls that a flag
would trigger in production are not made; they are counted only.

### Failed calls: detail and denominators

Each failed row stores `error` (exception class and AWS code) and
`failure_detail`, which holds structural facts only, never message, reply or
tool input text:

| `kind` | Meaning |
|---|---|
| `no_tool_call` | The reply had no `FastChatTurnOutput` tool call. Also stores `stop_reason` (Bedrock `stopReason`) and `text_blocks` (count). |
| `tool_input_invalid` | The tool input failed `parse_fast_chat_turn_output`. Also stores `stop_reason` and `errors`: pydantic `loc`, `type` and its static `msg` per error (input values excluded). A coaching reply without `recommendation` shows as `type: value_error` with an empty `loc`. |
| `fast_chat_contract` | `adapt_fast_chat_turn_payload` rejected the wire payload; `reason` is its fixed token. |
| `contract_rejected` | `_validated_fast_chat` rejected it; `category` is the provider category. |
| `other` | Anything else, for example an AWS error (see `error`). |

Successful rows store `stop_reason` too. `failures_by_kind` counts kinds overall
and per category.

`overall_failed_in_denominator` reports wrong-skip and false-retrieve over
**all** sent rows, in two readings:

- `failed_as_gate_only`: a failed call raises no flag, so the gate decision
  stands. This is what production would do with the flag if the student retried
  and the retry had no flag.
- `failed_as_error`: a failed `retrieve` row counts as a wrong skip and a failed
  `skip` row counts as a false retrieve (the strictest reading).

Before Phase 3c the live report had only the scored-row figures, so with 11
failed `skip` rows the false-retrieve denominator was 141 − 11 = 130.

### Production vs eval when the first call has no valid structured output

Production (file references at Phase 3c item 1):

1. The runtime forces tool use on cycle 1 for `fast_chat`
   (`_install_first_cycle_structured_output`, `agentcore_runtime/main.py:381`).
   Strands gets the repair prompt `"Please use the output tool now."`
   (`STRUCTURED_OUTPUT_REPAIR_PROMPT`, `agentcore_runtime/structured_coach.py:76`)
   and `limits={"turns": 2}` (`FAST_CHAT_INVOKE_LIMITS`, `:90`), so one
   generation plus at most one recovery turn (`main.py:510-520`, call at
   `main.py:625-629`). Throttling retries are separate
   (`FAST_CHAT_MODEL_RETRY`, `max_attempts=2`, `structured_coach.py:241-243`).
   Strands is not installed in the backend venv, so this recovery is described
   from the code and its docstrings, not executed here.
2. If the result still does not parse, `structured_from_agent_result` fails
   closed (`structured_coach.py:1242-1291`) and the runtime returns
   `{"ok": false, "error": true, "category": "structured_output_failure"}`
   (`main.py:653-689`, `harness_error_payload` at `structured_coach.py:937`).
3. The backend maps that envelope to a transient `structured_output_failure`
   (`_raise_if_harness_error_envelope`, `backend/agentcore_provider.py:377-403`)
   and `_assess_fast_chat` makes one fresh stateless re-invoke if the turn's
   two-invoke budget allows (`agentcore_provider.py:2107-2133`,
   `FAST_CHAT_MAX_PROVIDER_INVOCATIONS_PER_TURN = 2`, `backend/settings.py:75`).
   A reply that parses at the runtime but fails `_validated_fast_chat` is not
   retried (`_is_transient_structured_output_failure`, `:302-311`).
4. When both invokes fail the student gets a 503 with category
   `structured_output_failure` (`backend/coaching/streaming.py:29-31`; non-stream
   body `backend/http/app.py:117-122`). No assistant turn is saved. The React
   pilot shows "The answer was not confirmed saved. Your question is kept. Check
   saved answer before retrying." (`frontend/src/Conversation.tsx:217`);
   Streamlit shows "The coach couldn't complete that reply. Please try again."
   (`ui/panels/chat.py:328-329`). No `needs_sources` second call runs.

The eval makes one Converse call with `toolChoice: any`, no recovery turn, no
fresh re-invoke and no SDK retry (`total_max_attempts: 1`). Production allows up
to two generations per invoke and two invokes per turn before the student sees
the error. An eval parse failure therefore marks a first generation that
production would try to recover. The eval failure rate is an upper bound on the
student-facing rate, not a measure of it.

### Choose rows

The filters make a small live run possible. They apply in this order:

1. `--ids ID[,ID...]` and `--categories CATEGORY[,CATEGORY...]` (each
   comma-separated, may be repeated). With neither, all rows are kept. With one
   or both, a row is kept when its id **or** its category is listed (union).
   An unknown id, an unknown category (not in `MESSAGE_CATEGORIES`) or an empty
   list is refused.
2. `--expected-decision retrieve|skip` keeps only rows with that label.
3. `--skip-sample N` adds N `skip` rows not already selected, chosen with
   `evenly_spaced_indices` over the remaining `skip` rows in file order, so the
   same command always picks the same rows. Fewer are added when the pool is
   smaller.
4. The result is put back in file order. An empty selection is refused.
5. `--max-live-calls` applies last: below the selected count the script sends
   an evenly spaced subset of the selected rows (`floor(N / 2)` rows in compare
   mode).

Refusals exit 2 before the Bedrock client is built. All four flags need
`--live-model`; with the offline mode or `--live-kb` they are refused. The JSON
`selection` block records the arguments (`ids`, `categories`,
`expected_decision`, `skip_sample`, `compare_source_check`) and the counts
(`messages_in_set`, `rows_selected`, `rows_after_cap`). `rows_after_cap` is the
number of rows the cap allows; `calls.messages_attempted` is the number
actually tried (lower if the run stopped early). The report prints the same as
one `selection:` line (`-` means the filter was not given).

Examples on the 295 gate rows (counted by `select_live_rows` in the tests):

| Filter | Rows |
|---|---|
| `--categories greeting_thanks_chitchat --ids gm279` | 34 (gm146 to gm178, gm279) |
| `--categories course_content,course_logistics,informal_or_multilingual,upload_question,follow_up --expected-decision retrieve --skip-sample 60` | 169 (109 `retrieve` + 60 `skip`) |

### Cost of a live-model run (estimate)

Estimated cost = calls × (input tokens × input price + output tokens × output
price). The token figures are the averages the user reported from the
Phase 3b live run, about 7,100 input and 300 output tokens per call; greeting
rows and rows with history may differ. Prices used: Haiku 4.5 at $1.00 per
million input tokens and $5.00 per million output tokens for the `global.`
profile, from third-party price pages
([usage.ai](https://instances.usage.ai/ai/claude-haiku-4-5),
[TypingMind calculator](https://custom.typingmind.com/tools/estimate-llm-usage-costs/amazon-bedrock/anthropic-claude-haiku-4-5-20251001-v1-0)).
Regional (EU, AU, JP) profiles are listed at $1.10 and $5.50
([TypingMind EU](https://custom.typingmind.com/tools/estimate-llm-usage-costs/amazon-bedrock/eu-anthropic-claude-haiku-4-5-20251001-v1-0)).
Confirm on the AWS Bedrock pricing page before relying on these. Per call:
7,100 × $1/M + 300 × $5/M = $0.0071 + $0.0015 = $0.0086.

| Run | Calls | Estimate ($1 / $5) | Estimate ($1.10 / $5.50) |
|---|---|---|---|
| Smoke test (`--max-live-calls 5`) | 5 | $0.04 | $0.05 |
| Phase 3c item 1, greetings + gm279, SOURCE CHECK on and off | 68 | $0.58 | $0.64 |
| Phase 3c item 3 subset (169 rows, one call each) | 169 | $1.45 | $1.60 |
| Phase 3c item 3 subset with the course titles on (about 199 to 265 more input tokens per call) | 169 | $1.49 to $1.50 | $1.64 to $1.65 |
| Full gate set | 295 | $2.54 | $2.79 |

The report prints the real token totals (`tokens.input`, `tokens.output`), so
the real cost of a run can be checked afterwards.

### Compare SOURCE CHECK on vs off for chosen rows

`--compare-source-check` sends each chosen row twice, back to
back: once with `source_need_check=True` (the SOURCE CHECK paragraph in the
runtime rules) and once with `source_need_check=False` (production with
`FAST_CHAT_NEEDS_SOURCES_ENABLED` off; the flag is never honoured). The cached
fast-chat prompt and output contract are the same in both arms. Both flags need
`--live-model`; without it they are refused.

**Cap rule.** `--max-live-calls` counts model calls, applied after the row
filters.
Each row costs 2 calls, so the script sends `floor(N / 2)` rows (evenly spaced,
as in the plain mode) and the call counter stops at N. N below 2 is refused.
Fail-fast is unchanged: the run stops after the first auth or access error in
either arm.

The JSON has `mode: live_model_compare`, `arms.source_check_on` and
`arms.source_check_off` (each a full live-model summary with its `rows`),
`pairs` (per id, each arm's `status`, `mode` and `failure_detail`), and
`failed_on_only`, `failed_off_only`, `failed_both` id lists. `calls` adds
`messages_selected` and `calls_per_message: 2`; `selection` records the
filters. The filters also work without `--compare-source-check` (one call per
row).

**Phase 3c item 1 command (not run; costs money).** The 33
`greeting_thanks_chitchat` rows (gm146 to gm178, which contain the 10 reported
parse failures gm148 to gm172) plus gm279 (`ambiguous_generic`): 34 rows, 68
calls. `--categories greeting_thanks_chitchat --ids gm279` selects exactly the
same 34 rows as listing the 34 ids (a test pins this).

```bash
COACHING_MODEL_PROVIDER=bedrock \
COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0 \
AGENTCORE_MODEL_REGION=us-west-2 \
  python scripts/evals/evaluate_retrieval.py \
  --live-model --compare-source-check \
  --categories greeting_thanks_chitchat --ids gm279 \
  --max-live-calls 68 \
  --json-output .agents/tasks/phase3c-work/live-item1-greetings-on-off.json
```

Estimated cost 68 × $0.0086 ≈ $0.58 (see "Cost of a live-model run" above).

### Course titles in the SOURCE CHECK rule (Phase 3c item 3)

`FAST_CHAT_SOURCE_CHECK_TITLES_ENABLED` (default **false**) adds a COURSE
MATERIAL TITLES block after the SOURCE CHECK paragraph, on turns that already
carry the SOURCE CHECK (so only with `FAST_CHAT_NEEDS_SOURCES_ENABLED` on in
production). The block lists the course's Lecture Notes and Readings titles
and says that a question about a concept, framework, method or term covered by
them needs sources (needs_sources true, mode qa, out_of_scope false), while
navigation, UI help, greetings and thanks, and the student's own project
reasoning do not. The old SOURCE CHECK paragraph is unchanged. Production
builds the titles from the notebook's locked course sources (see
`docs/RAG_ARCHITECTURE.md`); the eval builds them from `course_materials.json`
through the same helper (`eval_course_titles` → `source_check_course_titles`).

With the setting on, `--live-model` adds the block to every row it sends with
the SOURCE CHECK (in compare mode the off arm gets neither) and writes
`source_check_titles: {enabled, count, block_chars}` to the JSON; the report
prints one `source check titles:` line.

Size, measured with the 10 manifest titles (script run): the block is 793
characters (794 with its line break), about 199 tokens at 4 characters per
token (`agentcore_runtime/prompt_cache.py`) and 265 at the planner's 3
(`backend/context_planner.estimate_tokens`). It lands in the per-turn runtime
rules after the fast-chat cache point, not in the cached prefix (pinned by
tests). Runtime rules with SOURCE CHECK on: 1,230 to 4,712 characters before,
2,024 to 5,498 after, across the 295 rows; on the 189 eligible rows every row
gets the full list. The block is fitted into `MAX_RUNTIME_CHARS` (5,500) by
dropping titles from the end; gm126 and gm127 (attachment questions the gate
already searches, so production never stamps them) keep 9 of the 10 titles.

**Offline comparison.** The three stub models (`oracle`, `mock_rule`,
`flag_all`) never read the prompt, so the old and the new wording give the
same stub bounds by construction (the offline JSON is unchanged). Only a live
run can measure whether the titles change the model's flag rate.

**Phase 3c item 3 command (not run; costs money).** The five categories that
hold the reported 63 live misses, filtered to `retrieve` labels, plus a
deterministic 60-row skip sample: 169 rows, 169 calls.

```bash
FAST_CHAT_SOURCE_CHECK_TITLES_ENABLED=true \
COACHING_MODEL_PROVIDER=bedrock \
COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0 \
AGENTCORE_MODEL_REGION=us-west-2 \
  python scripts/evals/evaluate_retrieval.py \
  --live-model \
  --categories course_content,course_logistics,informal_or_multilingual,upload_question,follow_up \
  --expected-decision retrieve --skip-sample 60 \
  --max-live-calls 169 \
  --json-output .agents/tasks/phase3c-work/live-item3-titles.json
```

The same command without `FAST_CHAT_SOURCE_CHECK_TITLES_ENABLED=true` (and
another `--json-output`) is the old-wording baseline on the same 169 rows.
The per-row Phase 3b live output is not available, so the subset cannot be
exactly "the 63 misses": the 109 `retrieve` rows hold 73 of the 76 offline
gate wrong skips (the other 3 are in `named_material`,
`upload_and_course` and `course_with_unrelated_upload`) and 36 rows the gate
already searches.


## Recorded results (Phase 4 item 0)

This section records outcomes that were already measured. Nothing here was
re-run. Marks: **(file)** is a figure stored in the named JSON file;
**(computed)** was computed in Phase 4 item 0 from counts or rows in those
files (Wilson 95% interval, z = 1.96, or a row-level count) and is not stored
in any file; **(docs)** appears only in the earlier status text and no
committed file holds it. The JSON files live in `.agents/tasks/` (git-ignored
globally and committed with `git add -f`). Every interval below is
**(computed)**; none of the files contains an interval.

### Phase 3c live gate results (Haiku 4.5, first Fast Chat call)

Both runs used the same 169 rows (109 labelled `retrieve`, 60 labelled
`skip`), one call per row, the SOURCE CHECK rule on, the five categories
`course_content`, `course_logistics`, `informal_or_multilingual`,
`upload_question` and `follow_up` for `retrieve`, and `--skip-sample 60`. Both
ran at git SHA `61ff634863170f3d7c698e92e3d62cb7c90dbcd0` with a clean tree
(`run.git_dirty: false`), model
`global.anthropic.claude-haiku-4-5-20251001-v1:0` in `us-west-2`.

| Run | File | UTC timestamp (file) | Calls made / ok / failed (file) | Tokens in / out (file) |
|---|---|---|---|---|
| Baseline wording | `phase3c-work/live-item3-baseline.json` | 2026-11-19T14:44:19Z | 169 / 166 / 3 | 1,198,802 / 52,750 |
| Source-check titles (10 titles, 793 characters) | `phase3c-work/live-item3-titles.json` | 2026-11-19T14:36:07Z | 169 / 167 / 2 | 1,237,027 / 50,870 |

All 5 failed calls are `skip` rows in `greeting_thanks_chitchat`, kind
`tool_input_invalid`, with the error "coaching mode requires recommendation stay
or advance" (file). Baseline failures: gm148, gm150, gm164. Titles failures:
gm153, gm164 (rows in each file). No `retrieve` row failed in either run.

| Metric | Gate only | Baseline wording | Titles wording |
|---|---|---|---|
| Wrong skip, over the 109 `retrieve` rows (file) | 73/109 = 67.0% [57.7, 75.1] | 62/109 = 56.9% [47.5, 65.8] | 51/109 = 46.8% [37.7, 56.1] |
| False retrieve, scored rows only (file) | 2/60 gate-only reading | 2/57 = 3.5% [1.0, 11.9] | 2/58 = 3.4% [1.0, 11.7] |
| False retrieve, failed calls in the denominator, `failed_as_gate_only` (file) | 2/60 = 3.3% [0.9, 11.4] | 2/60 | 2/60 |
| False retrieve, failed calls in the denominator, `failed_as_error` (file) | not applicable | 5/60 = 8.3% [3.6, 18.1] | 4/60 = 6.7% [2.6, 15.9] |

Denominator rules (from `definition` in the files and "Failed calls: detail and
denominators" above). The headline figures 62/109, 51/109, 2/57 and 2/58
leave failed calls out of `overall`. `failed_as_gate_only` keeps every failed
row in the denominator and lets the gate decision stand. `failed_as_error`
counts a failed `retrieve` row as a wrong skip and a failed `skip` row as a
false retrieve. Because all failed rows are `skip` rows, the wrong-skip
denominator is 109 in every reading, and only the false-retrieve denominator
moves (57 or 58 scored, 60 with failures). The Phase 3c target of "failed calls
counted in the denominator" is met by the `failed_as_error` row: 4/60 and 5/60.
Neither run reaches the 25% wrong-skip target.

By category, wrong skip with the model, baseline then titles (file):
`course_content` 35/61 then 25/61, `course_logistics` 4/11 then 6/11,
`informal_or_multilingual` 7/8 then 5/8, `follow_up` 5/9 then 4/9,
`upload_question` 11/20 then 11/20 (no change; 0/20 flagged in both).
The `course_logistics` rows got worse with titles (counts are small:
Wilson 95% for 4/11 is 15.2 to 64.6 and for 6/11 is 28.0 to 78.7, computed).

Reading the comparison. The two intervals for 62/109 and 51/109 overlap, and
the runs are single, unseeded model calls. A row-level pairing of the two files
(computed): 13 `retrieve` rows are missed only with the baseline wording and 2
only with the titles wording. The flag raised no false flags in either run
(`false_flags` is empty in both files).

### Greeting on/off run (Phase 3c item 1)

File `phase3c-work/live-item1-greetings-on-off.json`, mode
`live_model_compare`, git SHA `61ff634863170f3d7c698e92e3d62cb7c90dbcd0`, UTC
timestamp 2026-11-19T14:28:16Z, same Haiku model. Selection: the 33
`greeting_thanks_chitchat` rows plus gm279 (34 messages, 68 calls). Tokens in
and out: 474,584 and 16,653.

| Quantity (file) | Value |
|---|---|
| Calls made / ok / failed | 68 / 51 / 17 |
| Failed calls with SOURCE CHECK on | 9 of 34 |
| Failed calls with SOURCE CHECK off | 8 of 34 |
| Failed in both arms (same message) | 4: gm148, gm150, gm151, gm173 |
| Failed only with the rule off | 4: gm147, gm149, gm156, gm170 |
| Failed only with the rule on | 5: gm152, gm153, gm154, gm158, gm164 |
| Distinct messages with a failure in either arm (computed from `pairs`) | 13 of 34 |
| Failure kind and message | All 17: `tool_input_invalid`, "coaching mode requires recommendation stay or advance" |

The 17 failures are 17 failed calls across the two arms (9 on plus 8 off), on
13 distinct messages. They are not 17 messages. The failure rate with the rule
on (9/34 = 26.5% [14.6, 43.1], computed) and off (8/34 = 23.5% [12.4, 40.0],
computed) overlap, so the SOURCE CHECK rule is not shown to cause the failure.
With failed calls counted as errors, the false-retrieve rate on these rows is
9/34 with the rule on and 8/34 with it off (file, `failed_as_error`); with the
gate result standing it is 0/34 in both arms. All 34 rows are `skip` rows, so
there is no wrong-skip figure.

### Coaching reply with no recommendation (Phase 4 item 1)

The 17 failed calls are coaching replies whose `recommendation` was missing. The
model-facing tool schema requires it, but Claude Haiku omitted it on greeting
and thanks messages. `FastChatTurnOutput` now records `stay` for a coaching
reply whose recommendation is absent, null or blank (never `advance`), marks it
with `recommendation_defaulted`, and the backend writes the perf field
`fast_chat_recommendation_defaulted` (true only when it happened). An unknown
token such as `maybe` still fails. A Q&A reply and an explicit `advance` are
unchanged. The live eval counts defaulted rows in each outcome and in
`recommendation_defaulted: {count, ids}`, so the re-run shows how many of the 13
messages now pass and how many were defaulted. The change lives in the runtime
package, so it only reaches production after the AgentCore runtime is republished.
Deploy the backend that reads `recommendation_defaulted` (commit fd7a6e2) before or
together with that republish: an older backend ignores the marker, and in Free mode a
defaulted `stay` could then open a "Next" proposal (the student still has to confirm).
Reverting the backend alone reintroduces this.

### Laya production readiness (Phase 4 item 3)

Report only. Every command below is offline: sockets are blocked and
`HF_HUB_OFFLINE=1`. `laya`, `vegaml` and all weights are absent from this sandbox, so
the real-model commands were not run here; the stand-in run only checks the harness.

**Memory and per-turn latency harness**
(`scripts/evals/benchmark_course_intent.py`). It scores the 147 gate rows that are
eligible for Laya, with each row's real turn context and the course titles, then
reports load time, resident and peak resident memory (before load, after load, after
warm-up, after the passes), the first-call time, and p50, p95, p99 and max per call. The
classifier runs inline before generation, so one call's time is what it adds to a turn.

```bash
# Harness check, no model (marks real_model false). Run here on 2026-11-19.
python -m scripts.evals.benchmark_course_intent --stub-ms 5 --passes 3 --warmup 5 \
  --json-output /tmp/laya-harness-stub.json

# Laya (laya==0.4.37 or 0.4.38 installed; local checkpoint; serial)
python -m scripts.evals.benchmark_course_intent --checkpoint /path/to/laya-multilingual \
  --passes 3 --warmup 5 --host-instance-type <TYPE> --host-vcpu <N> --host-ram-gb <GB> --host-arch <arm64|x86_64> \
  --json-output /tmp/laya-resources.json

# Laya Learn (laya==0.4.38 and vegaml==0.17.1; Vega checkpoint with backbone/ and a bundle)
python -m scripts.evals.benchmark_course_intent --checkpoint /path/to/vega \
  --bundle /path/to/course-learner.zip --passes 3 --warmup 5 \
  --host-instance-type <TYPE> --host-vcpu <N> --host-ram-gb <GB> --host-arch <arm64|x86_64> \
  --json-output /tmp/laya-learn-resources.json

# Contention: eight threads against the single inference slot
python -m scripts.evals.benchmark_course_intent --checkpoint /path/to/laya-multilingual \
  --passes 1 --warmup 5 --concurrency 8 \
  --host-instance-type <TYPE> --host-vcpu <N> --host-ram-gb <GB> --host-arch <arm64|x86_64> \
  --json-output /tmp/laya-concurrency8.json
```

**Host notes (required with `--checkpoint`).** `--host-instance-type`, `--host-vcpu`,
`--host-ram-gb` and `--host-arch` (`arm64` or `x86_64`) are the operator's description of
the machine. The harness records them as given in a `host_note` block next to what the
process observed (`platform.machine()`, `os.cpu_count()`). A mismatch is recorded, never
fixed, and nothing is filled in from the machine. A real-model run refuses without all
four, and a value that is still a `<...>` placeholder is refused. With `--stub-ms` they
are optional. **This changes an existing command:** a `--checkpoint` run without the four
flags used to start and now exits 2, so older invocations need the flags added.

**All-rows run for the head-to-head comparison.** The stored Laya decisions cover only
94, 94 and 41 of the 147 eligible rows, so the comparison reports a floor, a ceiling and
a scored-only reading. To replace them with one exact reading, run the multilingual
checkpoint on the host whose figures are to be reported (fill in the four host values;
not run here):

```bash
python -m scripts.evals.benchmark_course_intent --checkpoint /path/to/laya-multilingual \
  --passes 3 --warmup 5 --host-instance-type <TYPE> --host-vcpu <N> --host-ram-gb <GB> --host-arch <arm64|x86_64> \
  --json-output .agents/tasks/headtohead-prereg/laya-all-rows-multilingual.json
# Laya Learn: use  --checkpoint /path/to/vega --bundle /path/to/course-learner.zip  instead
```

The result has the harness's existing keys plus `host_note` and `rows`: one object for
each of the 295 gate messages with `id`, `first_turn`, `status` (`scored`, `busy`,
`error` or `not_eligible`), `score` and `ms`. The row values come from the first timed
pass. Memory (`memory.peak_rss_mib`, `memory.load_delta_rss_mib`) and latency are in the
same file. Then:

```bash
python -m scripts.evals.compare_routing_arms --kb-gate .agents/tasks/headtohead-prereg/kb-gate.json \
  --laya-full .agents/tasks/headtohead-prereg/laya-all-rows-multilingual.json \
  --json-output .agents/tasks/headtohead-prereg/comparison.json
# Laya Learn file: add  --laya-full-kind learn
```

`compare_routing_arms` also refuses a `--kb-gate` file (and an `--extra-kb-gate` file)
whose recorded `kb_settings` do not match the plan: `candidates` 12, `max_results` 4 and
`filter_mode` `required`, or a file with no `kb_settings` block. It applies the unchanged
cutoffs (0.8, or the Learn per-turn cutoffs) and refuses a stub file, an unknown id, or a file missing any eligible row.
Until such a file exists, no all-rows Laya comparison has been made.

Run it on the intended production host (the output records platform, CPU count,
package versions and torch threads) and compare `memory.peak_rss_mib` with the container
limit; compose sets no memory limit today. A figure from another machine is not a
production figure.

**Stand-in run in this sandbox** (script run, Linux x86_64, 8 CPUs, Python 3.12.13; the
stand-in sleeps 5 ms, so the latency says nothing about Laya): 147 eligible rows of 295,
10 course titles, process RSS 64.6 MiB, peak 64.7 MiB, p95 5.24 ms per call. With eight
threads the stand-in's single slot gave 146 of 147 calls no score, the same pattern
Phase 3d recorded for real Laya (93/94).

### Extra messages (optional, separate from the 295)

`--extra-messages FILE` lets an operator check anonymised, human-labelled messages next
to the synthetic set. The file is JSONL (one object per line, UTF-8, at most 295 rows).
Required fields: `id` (a short token such as `ex001`, not `gm###`), `message`, `label`
(`retrieve` or `skip`) and `synthetic` (a JSON boolean). Optional fields:
`history_summary` (becomes one earlier user turn), `selected_source` and `attachment`
(booleans; each adds one source with no title or filename), `stage` (default
`problem_identification`) and `category` (a gate category, default `uncategorised`).

- **Default refuses real messages.** A row whose `synthetic` is not `true` is refused
  (exit 2) by both commands. `--allow-non-synthetic` accepts `synthetic: false`; the
  record and the report are then marked `real_messages`. A missing or non-boolean
  marker is refused with or without the flag.
- **Live gate.** `evaluate_retrieval.py --live-kb-gate --max-live-calls N --extra-messages FILE`
  sends only the extra rows (the 295 are a separate run), under the same cap of 1 to 295.
  The record has `mode: live_kb_gate_extra`, `set: extra_messages` and the same row
  fields as the gate record. Both new flags are refused (exit 2, before any client)
  without `--live-kb-gate`.
- **Comparison.** `compare_routing_arms --extra-messages FILE [--extra-kb-gate KB.json]
  [--allow-non-synthetic]` adds an `extra_messages` JSON key and a Markdown section.
  Extra rows are never split, never used to choose T, never in M1, M2, a paired test or a
  pass rule. Arms A and C are reported per row (id, category, label, search flags,
  evidence), using the T_C frozen on the 295. Arms B and D are `missing` (no Laya
  decisions exist for extra rows). Without `--extra-kb-gate` the evidence columns are
  `missing`. Without `--extra-messages`, output is unchanged.
- **Privacy.** Message and history text is read into memory only. It is not written to
  JSON, Markdown, stdout, stderr or logs; outputs hold ids, categories, labels, scores,
  counts and timings. Validation errors name a line number, a field and the id (when it
  is a safe token), never a value. The text of the live gate request goes to the
  Knowledge Base, as for any chat turn. Ids are the operator's responsibility: keep them
  anonymous.

```bash
# not run here
KNOWLEDGE_BASE_ID=<kb id> COURSE_MATERIALS_BUCKET=<bucket> AWS_REGION=<region> \
  python scripts/evals/evaluate_retrieval.py --live-kb-gate --max-live-calls <N> \
  --extra-messages extra.jsonl --json-output .agents/tasks/headtohead-prereg/kb-gate-extra.json
python -m scripts.evals.compare_routing_arms --kb-gate .agents/tasks/headtohead-prereg/kb-gate.json \
  --extra-messages extra.jsonl --extra-kb-gate .agents/tasks/headtohead-prereg/kb-gate-extra.json \
  --json-output .agents/tasks/headtohead-prereg/comparison.json
```

### Laya results

All Laya figures come from the Phase 3d result files in
`.agents/tasks/phase3d-work/` and the Laya sections of
`docs/IMPLEMENTATION_STATUS.md`. The files store the counts and the rate
rounded to four decimals; the intervals are computed. The Laya cutoffs were
calibrated offline on separate rows (see "Fit and evaluate Laya Learn"); the
holdout and Phase 3c rows were examined more than once, so the figures are
development-set evidence, not a clean test.

Phase 3c rows (n = 169: 109 `retrieve`, 60 `skip`), threshold 0.8, serial
unless noted:

| Setup | File | Wrong skip (file counts) | False retrieve (file counts) | p95 inference (file) |
|---|---|---|---|---|
| Existing gate | `multilingual.json` `baseline` (same in the other three files) | 73/109 = 67.0% [57.7, 75.1] | 2/60 = 3.3% [0.9, 11.4] | not applicable |
| Laya typed-decisions | `typed-decisions.json` | 73/109 = 67.0% [57.7, 75.1] | 2/60 | 450.31 ms |
| Laya multilingual | `multilingual.json` | 62/109 = 56.9% [47.5, 65.8] | 2/60 | 211.05 ms |
| Laya multilingual, concurrency 8 | `multilingual-concurrency8.json` | 73/109 = 67.0% [57.7, 75.1] | 2/60 | 349.55 ms |

Row-level counts for the multilingual run (computed from `rows`): 11 rows the
gate skipped were promoted to retrieval, all labelled `retrieve`; none was a
`skip` row (the file also records `promoted_outside_course_scope: 0`). In the
concurrency 8 run the single inference slot ran 1 inference and abstained on 93
busy requests (file), 94 eligible in total, so Laya changed nothing there. The
status text also says a retrospective threshold sweep "still missed at least
42/109"; no committed file contains that sweep **(docs)**.

Held-out synthetic rows (n = 84: 51 `retrieve`, 33 `skip`; 150 train, 61
calibration; 76 trained examples), source `course-intent-by-turn.json` unless
stated:

| Setup | Wrong skip | False retrieve |
|---|---|---|
| Existing gate (file `baseline`) | 24/51 = 47.1% [34.1, 60.5] | 2/33 = 6.1% [1.7, 19.6] |
| Frozen Vega (file `vega`) | 24/51 | 2/33 |
| Laya Learn, one cutoff 0.8564 (file `learn`; also `report.json`) | 18/51 = 35.3% [23.6, 49.0] | 2/33 |
| Laya Learn, first-turn cutoff 0.6456 then 0.8564 (file `learn_by_turn`) | 15/51 = 29.4% [18.7, 43.0] | 2/33 |
| Laya Learn, 121 shorter-turn examples (`course-intent-compact-v2.json` `learn`) | 22/51 = 43.1% [30.5, 56.7] | 2/33 |

p95 inference: 932.41 ms for the Learn run in `course-intent-by-turn.json`
and 1,089.94 ms in `report.json` (both file). All 41 eligible holdout turns used
the fitted head (file `head_predictions: 41`).

Additional rows, source `course-intent-by-turn-extra.json` and
`course-intent-followups-v2.json` (file counts):

| Set | Single cutoff | Per-turn cutoffs |
|---|---|---|
| 19 course questions with IDs absent from the gate corpus (all `retrieve`) | 2/19 = 10.5% [2.9, 31.4] | 1/19 = 5.3% [0.9, 24.6] |
| 12 follow-ups, wrong skip over 9 `retrieve` | 1/9 = 11.1% [2.0, 43.5] | 1/9 |
| 12 follow-ups, false retrieve over 3 `skip` | 0/3 = 0.0% [0.0, 56.1] | 0/3 |

`course-intent-followups-v2.json` holds a `previous` and a `revised` run on the
same follow-ups: 1/9 and 4/9 missed (44.4% [18.9, 73.3] for 4/9, computed).
With 9 and 3 rows the intervals are too wide to rank these setups.

### Combined gate evaluation (Phase 4 item 2)

`scripts/evals/evaluate_combined_gate.py` runs three arms over all 295 gate
messages, offline, with no network, no AWS and no model call. It is a new script
that takes the gate, loaders and rate helpers from `scripts/evals/lib`. It
is separate because the Laya arm needs stored or optional-dependency inputs that
the main offline report does not, and `evaluate_retrieval.py` is already large.

| Arm | What it is |
|---|---|
| (a) | The existing rules-based gate. |
| (b) | Arm (a) plus the local course-intent classifier (Laya). An ambiguous turn the gate skipped is promoted to course retrieval when the score meets the cutoff. |
| (c) | Arm (b) plus the SOURCE CHECK rule with course titles. The wording effect is a **stub model bound, not a measurement**: `oracle` flags exactly the rows labelled `retrieve`, `mock_rule` is the repo's keyword rule, `flag_all` flags every turn that carries the rule. Only a live run measures wording. |

```bash
python -m scripts.evals.evaluate_combined_gate \
  --json-output .agents/tasks/phase4-work/item2-combined-gate.json
# optional re-run with local weights (needs laya, not installed in this sandbox):
python -m scripts.evals.evaluate_combined_gate --checkpoint /path/to/checkpoint \
  [--bundle /path/to/bundle.zip] [--threshold 0.8] [--first-turn-threshold X]
```

**Cutoffs.** The existing cutoffs were used and not tuned on these rows: the 0.8
default, and for Laya Learn the two cutoffs (0.8564 and 0.6456) that were
selected earlier on the calibration split. The script reads them from the stored
files or the setting and never fits or searches a cutoff. The files do not
record how the 0.8 default was first chosen, and the Phase 3c rows were
examined more than once (see "Laya results"), so these are development-set
figures, not a clean test.

**Laya arm: from stored results, not re-run.** The `laya` and `vegaml` packages
are not installed in this sandbox, and no `model.safetensors`, `vega_config.json`
or bundle file exists on it, so the classifier cannot run here. The script falls
back to the stored per-row decisions in `.agents/tasks/phase3d-work/`. Those
files do contain per-row decisions: `multilingual.json` and
`typed-decisions.json` store `promoted` per row (169 rows), and
`course-intent-by-turn.json` stores a Learn score and a first-turn flag per row
(this script uses only its 84 `holdout_rows`; the calibration rows chose the
cutoffs and the training rows were fitted on). `multilingual-concurrency8.json`
is not used because 93 of its 94 inferences were busy abstentions.

**Coverage.** 147 of the 295 rows are eligible for Laya (ambiguous intent, no
evidence scope, nothing searched, not chit-chat); the other 148 are never
scored, so arm (b) equals arm (a) on them by construction. The stored files
hold a decision for 94 of the 147 eligible rows (the two 0.8 runs) or 41 (Learn).
The rest cannot be evaluated here, so every number is reported in three modes:

- `floor`: unscored eligible rows are not promoted (the least Laya can do), all 295 rows.
- `ceiling`: unscored eligible rows are all promoted (the most Laya can do), all 295 rows. This is a bound, not a result; its false-retrieve figures are what promoting every eligible row would cost.
- `scored_only`: unscored eligible rows are left out, so every kept row has an exact decision. The kept set is not a random sample (for Learn it drops all training and calibration rows).

Checks the script records: the gate at this commit reproduces every stored
`baseline_retrieve` and every stored eligibility flag (no mismatch in 169, 169
and 84 rows), and the composed arm (b) reproduces each file's own summary
(62/109 and 2/60 for multilingual, 73/109 and 2/60 for typed-decisions, 15/51
and 2/33 for Learn).

**Extra calls and tokens.** "Extra searches" counts rows searched in the arm but
not by the gate. "Extra model calls" counts stub flags on rows that carry the
rule, one second call each. Laya adds only local CPU inference (no tokens, no
AWS). Token figures are estimates: rule plus titles are 798 + 794 characters per
turn that carries the rule; excerpts are an upper bound (the 8,000-character
`FAST_CHAT_RETRIEVAL_MAX_CHARS` cap per newly searched turn); each second call
uses the user-reported mean of 7,100 input and 300 output tokens. The JSON holds
the per-category token estimates.

**Marks.** Every figure below is **script run** from
`.agents/tasks/phase4-work/item2-combined-gate.json` (git SHA `21d19ce`, clean
tree, 2026-11-19T16:48:40Z). Intervals are Wilson 95%. `S` marks a denominator
under 30 rows and `VS` one under 10 (a rule of thumb chosen for this report).
Most categories are small; read them as counts, not rates.

**Arm (a), the existing gate, by category (script run, all 295 rows)**

| Category | Retrieve rows | Wrong skip | Skip rows | False retrieve |
|---|---|---|---|---|
| ambiguous_generic | 0 | n/a | 9 | 1/9 = 11.1% [2.0, 43.5] VS |
| attachment_question | 13 | 0/13 = 0.0% [0.0, 22.8] S | 0 | n/a |
| course_content | 61 | 38/61 = 62.3% [49.8, 73.4] | 0 | n/a |
| course_logistics | 11 | 10/11 = 90.9% [62.3, 98.4] S | 0 | n/a |
| course_with_unrelated_upload | 4 | 1/4 = 25.0% [4.6, 69.9] VS | 0 | n/a |
| follow_up | 9 | 7/9 = 77.8% [45.3, 93.7] VS | 7 | 1/7 = 14.3% [2.6, 51.3] VS |
| greeting_thanks_chitchat | 0 | n/a | 33 | 0/33 = 0.0% [0.0, 10.4] |
| informal_or_multilingual | 8 | 7/8 = 87.5% [52.9, 97.8] VS | 0 | n/a |
| mixed_project_and_course | 3 | 0/3 = 0.0% [0.0, 56.1] VS | 0 | n/a |
| named_material | 13 | 1/13 = 7.7% [1.4, 33.3] S | 0 | n/a |
| not_in_course_material | 0 | n/a | 4 | 1/4 = 25.0% [4.6, 69.9] VS |
| out_of_scope | 0 | n/a | 7 | 1/7 = 14.3% [2.6, 51.3] VS |
| procedural_ui | 0 | n/a | 20 | 2/20 = 10.0% [2.8, 30.1] S |
| project_mentions_course | 0 | n/a | 9 | 1/9 = 11.1% [2.0, 43.5] VS |
| project_reasoning | 0 | n/a | 31 | 0/31 = 0.0% [0.0, 11.0] |
| stage_meta_guidance | 0 | n/a | 10 | 0/10 = 0.0% [0.0, 27.8] S |
| stage_navigation | 0 | n/a | 11 | 0/11 = 0.0% [0.0, 25.9] S |
| upload_and_course | 12 | 1/12 = 8.3% [1.5, 35.4] S | 0 | n/a |
| upload_question | 20 | 11/20 = 55.0% [34.2, 74.2] S | 0 | n/a |
| **all rows** | 154 | 76/154 = 49.4% [41.6, 57.2] | 141 | 7/141 = 5.0% [2.4, 9.9] |

**Overall, per Laya source and mode** (script run; rows in brackets)

| Laya source | Mode (rows) | Arm | Wrong skip | False retrieve | Extra searches | Extra model calls (stub) | Rule stamped on turns |
|---|---|---|---|---|---|---|---|
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | `floor` (295) | (a) gate | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `floor` (295) | (b) gate + Laya | 67/154 = 43.5% [35.9, 51.4] | 7/141 = 5.0% [2.4, 9.9] | 9 | 0 | 0 |
|  | `floor` (295) | (c) stub `flag_all` | 0/154 = 0.0% [0.0, 2.4] | 120/141 = 85.1% [78.3, 90.0] | 189 | 180 | 180 |
|  | `floor` (295) | (c) stub `mock_rule` | 18/154 = 11.7% [7.5, 17.7] | 39/141 = 27.7% [20.9, 35.6] | 90 | 81 | 180 |
|  | `floor` (295) | (c) stub `oracle` | 0/154 = 0.0% [0.0, 2.4] | 7/141 = 5.0% [2.4, 9.9] | 76 | 67 | 180 |
|  | `ceiling` (295) | (a) gate | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `ceiling` (295) | (b) gate + Laya | 27/154 = 17.5% [12.3, 24.3] | 73/141 = 51.8% [43.6, 59.9] | 115 | 0 | 0 |
|  | `ceiling` (295) | (c) stub `flag_all` | 0/154 = 0.0% [0.0, 2.4] | 120/141 = 85.1% [78.3, 90.0] | 189 | 74 | 74 |
|  | `ceiling` (295) | (c) stub `mock_rule` | 9/154 = 5.8% [3.1, 10.7] | 84/141 = 59.6% [51.3, 67.3] | 144 | 29 | 74 |
|  | `ceiling` (295) | (c) stub `oracle` | 0/154 = 0.0% [0.0, 2.4] | 73/141 = 51.8% [43.6, 59.9] | 142 | 27 | 74 |
|  | `scored_only` (189) | (a) gate | 36/114 = 31.6% [23.8, 40.6] | 7/75 = 9.3% [4.6, 18.0] | 0 | 0 | 0 |
|  | `scored_only` (189) | (b) gate + Laya | 27/114 = 23.7% [16.8, 32.3] | 7/75 = 9.3% [4.6, 18.0] | 9 | 0 | 0 |
|  | `scored_only` (189) | (c) stub `flag_all` | 0/114 = 0.0% [0.0, 3.3] | 54/75 = 72.0% [61.0, 80.9] | 83 | 74 | 74 |
|  | `scored_only` (189) | (c) stub `mock_rule` | 9/114 = 7.9% [4.2, 14.3] | 18/75 = 24.0% [15.8, 34.8] | 38 | 29 | 74 |
|  | `scored_only` (189) | (c) stub `oracle` | 0/114 = 0.0% [0.0, 3.3] | 7/75 = 9.3% [4.6, 18.0] | 36 | 27 | 74 |
| Laya multilingual, cutoff 0.8 | `floor` (295) | (a) gate | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `floor` (295) | (b) gate + Laya | 65/154 = 42.2% [34.7, 50.1] | 7/141 = 5.0% [2.4, 9.9] | 11 | 0 | 0 |
|  | `floor` (295) | (c) stub `flag_all` | 0/154 = 0.0% [0.0, 2.4] | 120/141 = 85.1% [78.3, 90.0] | 189 | 178 | 178 |
|  | `floor` (295) | (c) stub `mock_rule` | 16/154 = 10.4% [6.5, 16.2] | 39/141 = 27.7% [20.9, 35.6] | 92 | 81 | 178 |
|  | `floor` (295) | (c) stub `oracle` | 0/154 = 0.0% [0.0, 2.4] | 7/141 = 5.0% [2.4, 9.9] | 76 | 65 | 178 |
|  | `ceiling` (295) | (a) gate | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `ceiling` (295) | (b) gate + Laya | 64/154 = 41.6% [34.1, 49.5] | 59/141 = 41.8% [34.0, 50.1] | 64 | 0 | 0 |
|  | `ceiling` (295) | (c) stub `flag_all` | 0/154 = 0.0% [0.0, 2.4] | 120/141 = 85.1% [78.3, 90.0] | 189 | 125 | 125 |
|  | `ceiling` (295) | (c) stub `mock_rule` | 15/154 = 9.7% [6.0, 15.4] | 76/141 = 53.9% [45.7, 61.9] | 130 | 66 | 125 |
|  | `ceiling` (295) | (c) stub `oracle` | 0/154 = 0.0% [0.0, 2.4] | 59/141 = 41.8% [34.0, 50.1] | 128 | 64 | 125 |
|  | `scored_only` (242) | (a) gate | 75/153 = 49.0% [41.2, 56.9] | 7/89 = 7.9% [3.9, 15.4] | 0 | 0 | 0 |
|  | `scored_only` (242) | (b) gate + Laya | 64/153 = 41.8% [34.3, 49.8] | 7/89 = 7.9% [3.9, 15.4] | 11 | 0 | 0 |
|  | `scored_only` (242) | (c) stub `flag_all` | 0/153 = 0.0% [0.0, 2.5] | 68/89 = 76.4% [66.6, 84.0] | 136 | 125 | 125 |
|  | `scored_only` (242) | (c) stub `mock_rule` | 15/153 = 9.8% [6.0, 15.6] | 24/89 = 27.0% [18.8, 37.0] | 77 | 66 | 125 |
|  | `scored_only` (242) | (c) stub `oracle` | 0/153 = 0.0% [0.0, 2.5] | 7/89 = 7.9% [3.9, 15.4] | 75 | 64 | 125 |
| Laya typed-decisions, cutoff 0.8 | `floor` (295) | (a) gate | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `floor` (295) | (b) gate + Laya | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `floor` (295) | (c) stub `flag_all` | 0/154 = 0.0% [0.0, 2.4] | 120/141 = 85.1% [78.3, 90.0] | 189 | 189 | 189 |
|  | `floor` (295) | (c) stub `mock_rule` | 19/154 = 12.3% [8.0, 18.5] | 39/141 = 27.7% [20.9, 35.6] | 89 | 89 | 189 |
|  | `floor` (295) | (c) stub `oracle` | 0/154 = 0.0% [0.0, 2.4] | 7/141 = 5.0% [2.4, 9.9] | 76 | 76 | 189 |
|  | `ceiling` (295) | (a) gate | 76/154 = 49.4% [41.6, 57.2] | 7/141 = 5.0% [2.4, 9.9] | 0 | 0 | 0 |
|  | `ceiling` (295) | (b) gate + Laya | 75/154 = 48.7% [40.9, 56.5] | 59/141 = 41.8% [34.0, 50.1] | 53 | 0 | 0 |
|  | `ceiling` (295) | (c) stub `flag_all` | 0/154 = 0.0% [0.0, 2.4] | 120/141 = 85.1% [78.3, 90.0] | 189 | 136 | 136 |
|  | `ceiling` (295) | (c) stub `mock_rule` | 18/154 = 11.7% [7.5, 17.7] | 76/141 = 53.9% [45.7, 61.9] | 127 | 74 | 136 |
|  | `ceiling` (295) | (c) stub `oracle` | 0/154 = 0.0% [0.0, 2.4] | 59/141 = 41.8% [34.0, 50.1] | 128 | 75 | 136 |
|  | `scored_only` (242) | (a) gate | 75/153 = 49.0% [41.2, 56.9] | 7/89 = 7.9% [3.9, 15.4] | 0 | 0 | 0 |
|  | `scored_only` (242) | (b) gate + Laya | 75/153 = 49.0% [41.2, 56.9] | 7/89 = 7.9% [3.9, 15.4] | 0 | 0 | 0 |
|  | `scored_only` (242) | (c) stub `flag_all` | 0/153 = 0.0% [0.0, 2.5] | 68/89 = 76.4% [66.6, 84.0] | 136 | 136 | 136 |
|  | `scored_only` (242) | (c) stub `mock_rule` | 18/153 = 11.8% [7.6, 17.8] | 24/89 = 27.0% [18.8, 37.0] | 74 | 74 | 136 |
|  | `scored_only` (242) | (c) stub `oracle` | 0/153 = 0.0% [0.0, 2.5] | 7/89 = 7.9% [3.9, 15.4] | 75 | 75 | 136 |

**Arm (b) by category, only where Laya changes a row in either bracket**

| Laya source | Category | Metric | (a) gate | (b) floor | (b) ceiling | Extra searches floor / ceiling |
|---|---|---|---|---|---|---|
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | ambiguous_generic | false retrieve | 1/9 = 11.1% [2.0, 43.5] VS | 1/9 = 11.1% [2.0, 43.5] VS | 4/9 = 44.4% [18.9, 73.3] VS | 0 / 3 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | course_content | wrong skip | 38/61 = 62.3% [49.8, 73.4] | 32/61 = 52.5% [40.2, 64.5] | 7/61 = 11.5% [5.7, 21.8] | 6 / 31 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | course_logistics | wrong skip | 10/11 = 90.9% [62.3, 98.4] S | 8/11 = 72.7% [43.4, 90.2] S | 0/11 = 0.0% [0.0, 25.9] S | 2 / 10 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | follow_up | wrong skip | 7/9 = 77.8% [45.3, 93.7] VS | 7/9 = 77.8% [45.3, 93.7] VS | 4/9 = 44.4% [18.9, 73.3] VS | 0 / 8 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | follow_up | false retrieve | 1/7 = 14.3% [2.6, 51.3] VS | 1/7 = 14.3% [2.6, 51.3] VS | 6/7 = 85.7% [48.7, 97.4] VS | 0 / 8 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | greeting_thanks_chitchat | false retrieve | 0/33 = 0.0% [0.0, 10.4] | 0/33 = 0.0% [0.0, 10.4] | 15/33 = 45.5% [29.8, 62.0] | 0 / 15 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | informal_or_multilingual | wrong skip | 7/8 = 87.5% [52.9, 97.8] VS | 6/8 = 75.0% [40.9, 92.8] VS | 3/8 = 37.5% [13.7, 69.4] VS | 1 / 4 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | named_material | wrong skip | 1/13 = 7.7% [1.4, 33.3] S | 1/13 = 7.7% [1.4, 33.3] S | 0/13 = 0.0% [0.0, 22.8] S | 0 / 1 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | not_in_course_material | false retrieve | 1/4 = 25.0% [4.6, 69.9] VS | 1/4 = 25.0% [4.6, 69.9] VS | 3/4 = 75.0% [30.1, 95.4] VS | 0 / 2 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | out_of_scope | false retrieve | 1/7 = 14.3% [2.6, 51.3] VS | 1/7 = 14.3% [2.6, 51.3] VS | 7/7 = 100.0% [64.6, 100.0] VS | 0 / 6 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | procedural_ui | false retrieve | 2/20 = 10.0% [2.8, 30.1] S | 2/20 = 10.0% [2.8, 30.1] S | 14/20 = 70.0% [48.1, 85.5] S | 0 / 12 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | project_mentions_course | false retrieve | 1/9 = 11.1% [2.0, 43.5] VS | 1/9 = 11.1% [2.0, 43.5] VS | 7/9 = 77.8% [45.3, 93.7] VS | 0 / 6 |
| Laya Learn, per-turn cutoffs 0.8564 / 0.6456 | project_reasoning | false retrieve | 0/31 = 0.0% [0.0, 11.0] | 0/31 = 0.0% [0.0, 11.0] | 17/31 = 54.8% [37.8, 70.8] | 0 / 17 |
| Laya multilingual, cutoff 0.8 | ambiguous_generic | false retrieve | 1/9 = 11.1% [2.0, 43.5] VS | 1/9 = 11.1% [2.0, 43.5] VS | 3/9 = 33.3% [12.1, 64.6] VS | 0 / 2 |
| Laya multilingual, cutoff 0.8 | course_content | wrong skip | 38/61 = 62.3% [49.8, 73.4] | 33/61 = 54.1% [41.7, 66.0] | 33/61 = 54.1% [41.7, 66.0] | 5 / 5 |
| Laya multilingual, cutoff 0.8 | course_logistics | wrong skip | 10/11 = 90.9% [62.3, 98.4] S | 7/11 = 63.6% [35.4, 84.8] S | 7/11 = 63.6% [35.4, 84.8] S | 3 / 3 |
| Laya multilingual, cutoff 0.8 | follow_up | false retrieve | 1/7 = 14.3% [2.6, 51.3] VS | 1/7 = 14.3% [2.6, 51.3] VS | 4/7 = 57.1% [25.1, 84.2] VS | 0 / 3 |
| Laya multilingual, cutoff 0.8 | greeting_thanks_chitchat | false retrieve | 0/33 = 0.0% [0.0, 10.4] | 0/33 = 0.0% [0.0, 10.4] | 12/33 = 36.4% [22.2, 53.4] | 0 / 12 |
| Laya multilingual, cutoff 0.8 | informal_or_multilingual | wrong skip | 7/8 = 87.5% [52.9, 97.8] VS | 4/8 = 50.0% [21.5, 78.5] VS | 4/8 = 50.0% [21.5, 78.5] VS | 3 / 3 |
| Laya multilingual, cutoff 0.8 | named_material | wrong skip | 1/13 = 7.7% [1.4, 33.3] S | 1/13 = 7.7% [1.4, 33.3] S | 0/13 = 0.0% [0.0, 22.8] S | 0 / 1 |
| Laya multilingual, cutoff 0.8 | not_in_course_material | false retrieve | 1/4 = 25.0% [4.6, 69.9] VS | 1/4 = 25.0% [4.6, 69.9] VS | 2/4 = 50.0% [15.0, 85.0] VS | 0 / 1 |
| Laya multilingual, cutoff 0.8 | out_of_scope | false retrieve | 1/7 = 14.3% [2.6, 51.3] VS | 1/7 = 14.3% [2.6, 51.3] VS | 5/7 = 71.4% [35.9, 91.8] VS | 0 / 4 |
| Laya multilingual, cutoff 0.8 | procedural_ui | false retrieve | 2/20 = 10.0% [2.8, 30.1] S | 2/20 = 10.0% [2.8, 30.1] S | 14/20 = 70.0% [48.1, 85.5] S | 0 / 12 |
| Laya multilingual, cutoff 0.8 | project_mentions_course | false retrieve | 1/9 = 11.1% [2.0, 43.5] VS | 1/9 = 11.1% [2.0, 43.5] VS | 5/9 = 55.6% [26.7, 81.1] VS | 0 / 4 |
| Laya multilingual, cutoff 0.8 | project_reasoning | false retrieve | 0/31 = 0.0% [0.0, 11.0] | 0/31 = 0.0% [0.0, 11.0] | 14/31 = 45.2% [29.2, 62.2] | 0 / 14 |
| Laya typed-decisions, cutoff 0.8 | ambiguous_generic | false retrieve | 1/9 = 11.1% [2.0, 43.5] VS | 1/9 = 11.1% [2.0, 43.5] VS | 3/9 = 33.3% [12.1, 64.6] VS | 0 / 2 |
| Laya typed-decisions, cutoff 0.8 | follow_up | false retrieve | 1/7 = 14.3% [2.6, 51.3] VS | 1/7 = 14.3% [2.6, 51.3] VS | 4/7 = 57.1% [25.1, 84.2] VS | 0 / 3 |
| Laya typed-decisions, cutoff 0.8 | greeting_thanks_chitchat | false retrieve | 0/33 = 0.0% [0.0, 10.4] | 0/33 = 0.0% [0.0, 10.4] | 12/33 = 36.4% [22.2, 53.4] | 0 / 12 |
| Laya typed-decisions, cutoff 0.8 | named_material | wrong skip | 1/13 = 7.7% [1.4, 33.3] S | 1/13 = 7.7% [1.4, 33.3] S | 0/13 = 0.0% [0.0, 22.8] S | 0 / 1 |
| Laya typed-decisions, cutoff 0.8 | not_in_course_material | false retrieve | 1/4 = 25.0% [4.6, 69.9] VS | 1/4 = 25.0% [4.6, 69.9] VS | 2/4 = 50.0% [15.0, 85.0] VS | 0 / 1 |
| Laya typed-decisions, cutoff 0.8 | out_of_scope | false retrieve | 1/7 = 14.3% [2.6, 51.3] VS | 1/7 = 14.3% [2.6, 51.3] VS | 5/7 = 71.4% [35.9, 91.8] VS | 0 / 4 |
| Laya typed-decisions, cutoff 0.8 | procedural_ui | false retrieve | 2/20 = 10.0% [2.8, 30.1] S | 2/20 = 10.0% [2.8, 30.1] S | 14/20 = 70.0% [48.1, 85.5] S | 0 / 12 |
| Laya typed-decisions, cutoff 0.8 | project_mentions_course | false retrieve | 1/9 = 11.1% [2.0, 43.5] VS | 1/9 = 11.1% [2.0, 43.5] VS | 5/9 = 55.6% [26.7, 81.1] VS | 0 / 4 |
| Laya typed-decisions, cutoff 0.8 | project_reasoning | false retrieve | 0/31 = 0.0% [0.0, 11.0] | 0/31 = 0.0% [0.0, 11.0] | 14/31 = 45.2% [29.2, 62.2] | 0 / 14 |

Reading the results (script run unless noted):

- Gate alone: wrong skip 76/154 = 49.4% [41.6, 57.2] and false retrieve 7/141 = 5.0% [2.4, 9.9]. These match the earlier offline numbers.
- Laya multilingual at 0.8 turns 11 wrong skips into retrievals (65/154 = 42.2% [34.7, 50.1] in the `floor` reading) with no new false retrieve on the scored rows. The intervals for arm (a) and arm (b) overlap, so the 295-row data do not show a clear difference. Laya typed-decisions promotes nothing.
- Laya Learn lowers misses from 36/114 to 27/114 on the exact-decision rows (23.7% [16.8, 32.3]) with false retrieves unchanged at 7/75. That subset excludes the 106 eligible rows that were trained on, used for calibration or never scored, so it does not describe the full set. Over all 295 rows with unscored rows left unpromoted it is 67/154 = 43.5% [35.9, 51.4].
- No reading that uses stored Laya decisions on all 295 rows reaches the 25% wrong-skip target while keeping false retrieves under 10%. The `ceiling` reading of Laya Learn reaches 27/154 = 17.5% [12.3, 24.3] only with 73/141 = 51.8% false retrieves, so it is a bound and not an operating point.
- Stub bounds for arm (c) on top of Laya: `oracle` reaches 0 wrong skips and keeps false retrieves at the gate's 7/141 by definition, so it is the best case. `mock_rule` gives 16/154 and 39/141 (27.7% [20.9, 35.6]) and `flag_all` gives 0/154 and 120/141 (85.1% [78.3, 90.0]). The real model sits somewhere in this range. The phase 3c live run (62/109 wrong skip baseline, 51/109 with titles, in the Recorded results above) is the only measurement of wording.
- Laya cuts extra model calls from the stub arm by 11 (`oracle` 76 to 65 second calls on the multilingual floor) because promoted rows no longer carry the rule, at the cost of the same 11 first-pass searches.

### Product rule: course concept questions require a course citation

**Product rule (not implemented as stated).** A question about a course
concept, framework or method requires a citation to a course excerpt. If no
supporting excerpt is found, the coach says that it could not verify the course
definition. It may then add a general explanation, clearly labelled as general
and not from the course materials.

This is a requirement for future work. The code check on `3060a17` found these
parts and gaps:

- Partly present: on a turn that searched the course catalogue and got no
  excerpt, `backend/prompts/composer.py` (the `gap_note` branch, near line 364)
  tells the model to say it "could not retrieve a validated excerpt from the
  selected course material" and not to invent a summary. Tests pin this text
  (`tests/domain/test_prompt_architecture.py`, `test_qa_grounding.py`).
- Different from the rule: that text says "could not retrieve a validated
  excerpt", not "could not verify the course definition", and it does not allow
  a general explanation. `allow_model_knowledge` is false for course-catalogue
  turns (`backend/coaching/execution.py`, near line 3392), and
  `agentcore_runtime/prompts/qa.md` rule 5 allows broader knowledge only when
  the runtime rules permit it.
- Not present: nothing requires a citation when the gate skips retrieval. A
  course concept question the gate skips (the wrong skips above) reaches the
  model with no course excerpt and no rule that forces a "could not verify"
  statement. On turns with no selected source and no course catalogue,
  `allow_model_knowledge` is true and the composer says only "Broader knowledge
  is allowed when sources do not answer the question", with no label
  requirement. A label instruction exists in `backend/chat_service.py` ("clearly
  distinguish it from source-supported claims"); this check did not trace
  whether that module serves the current coach path.
- Not present: no validator rejects an answer to a course concept question that
  has no citation. A text search of `backend/`, `agentcore_runtime/`, `ui/` and
  `frontend/src/` for "could not verify" and "general explanation" finds no
  match in the coach prompts or reply handling.

Related open decision (not implemented): labelling answers on course Q&A turns
where no search ran as general, not from course materials.

## Head-to-head routing comparison (built, not run)

Compares four ways of deciding whether a turn gets course evidence, on the same 295
gate messages: **A** the existing gate, **B** gate plus Laya (current promotion rule,
unchanged cutoffs), **C** Knowledge Base score routing (skip only where an existing
skip rule fires, otherwise search, inject evidence if the top validated score is at
least T) and **D** gate plus Laya decide whether to search, KB score decides whether
evidence is injected. Scope decisions come from `backend/coaching/evidence_scope.py`;
no gate rule or setting was added.

**State.** The three commands below are built and covered by mock tests only. **Nothing
live has run:** no Knowledge Base call, no AWS call, no Laya weights. The KB-score file
(`kb-gate.json`) and the all-rows Laya file (`laya-all-rows-*.json`) do not exist, so no
arm can be declared the winner. Without them, arms C and D are `missing`, A and B use a
search-only bound, and no arm can reach `pass`. A run that reports a full comparison
needs both files, produced on the host named in the report.

**No production change.** Everything is under `scripts/evals/`, `tests/scripts/` and
docs. `backend/`, `agentcore_runtime/` and `frontend/` are untouched, and every setting
stays at its default (off). Nothing here changes routing in the app.

### Pre-registration

The rules were written and committed before any per-half figure was computed:
`.agents/tasks/headtohead-prereg/plan.md` (git-ignored folder, committed with
`git add -f`, commit `8c51cdd`; sha256
`59fd07ffc9c64ed657de59dfecadb75c3f37ef898225dd87850044f20c4c0b9c`). **Its text is never
edited.** A correction is appended as a dated, post-hoc amendment at the end of the file,
and the report says so. `compare_routing_arms` records the file's sha256 and commit in its
output, and refuses to run if the constants block in section 14 of the plan differs from
`scripts/evals/lib/prereg.py` (a test checks the same).

- **Split.** One function in `scripts/evals/lib/prereg.py`. With
  `h = int(sha256(row_id.encode("utf-8")).hexdigest(), 16)`, a row is calibration if
  `h % 2 == 0` and holdout otherwise. No salt, no stratification; sizes are whatever the
  rule gives. Calibration rows are used only to choose T. Every reported metric, paired
  test and pass decision uses holdout rows.
- **How T is chosen** (arms C and D, `T_C` and `T_D`, by code, no override flag).
  Candidates are the distinct top validated scores on calibration rows where the arm
  searched the KB and got at least one validated hit, plus `+inf` (never inject KB
  evidence). Among candidates with calibration M2 at most 10%, take the lowest
  calibration M1. Ties: lower calibration M2, then the highest T. If none has M2 at most
  10%, the arm has "no feasible T" and fails. T is written to the output and applied
  unchanged to the holdout rows. A partial KB file gives `missing` and no T. Laya
  cutoffs are read from files and never fitted: 0.8 for the multilingual checkpoint, and
  0.8563768 (continuing) and 0.6455846 (first turn) for Laya Learn, which is secondary
  because it was fitted on 150 rows of this set.
- **Evidence injected.** A and B: a KB search ran, did not fail, and has at least one
  validated hit. C and D: the same, and top validated score at least T. Any local search
  of student uploads also counts as injected (optimistic for M1, pessimistic for M2).
- **Metrics (holdout rows, Wilson 95%, samples under 30 marked small).** M1: `retrieve`
  rows with no evidence injected. M2: `skip` rows with evidence injected. M3: searches
  added per 100 turns versus A, KB and local counted separately. M4: added wait per turn
  (Laya inference ms plus KB ms, p50 and p95; local-search time is `missing`). M5: cost
  per 1,000 turns at $1 per 1,000 KB searches, and Laya host memory. M6 (operational risk
  table, facts only, with file and line evidence) is written in the report, not computed
  by the command.
- **Paired tests.** Exact two-sided McNemar on holdout rows for A vs B, A vs C, B vs C
  and C vs D, in three families (`retrieve` rows, `skip` rows, all-row mistakes), with
  both discordant counts. B and D only add searches to A, so "A is never better than B"
  on M1 is built in; the output repeats this next to the p-values.
- **Pass rule (fixed).** An arm passes if holdout M1 is at most 15%, M2 at most 10% and
  added p95 wait at most 1,000 ms. The states are `pass` (holds under the pessimistic
  reading of every unknown), `fail` (breaks under the optimistic reading, or no feasible
  T) and `cannot be determined yet` (anything with missing KB, wait or Laya data). If
  several arms pass, the order of moving parts is A, C, B, D, and a later arm replaces the
  champion only if its M1 is lower and the McNemar test on `retrieve` rows gives
  `p < 0.05`. If none passes, the report says so. The rule is not relaxed afterwards.
- **Laya coverage.** Stored decisions cover 94 of 147 eligible rows (multilingual) and 41
  (Learn). They are reported as floor, ceiling and scored-only until an all-rows file is
  supplied with `--laya-full`.

### Exact commands (not run)

Fill in the host values for the machine the final figures are for; the harness refuses
placeholders. AWS credentials come from the normal chain.

```bash
# 1. KB scores: one Retrieve per gate message, all 295 (needs approval; costs money).
KNOWLEDGE_BASE_ID=<kb id> KNOWLEDGE_BASE_TYPE=managed \
KNOWLEDGE_BASE_METADATA_FILTER_MODE=required \
COURSE_MATERIALS_BUCKET=<course bucket> AWS_REGION=<region> \
  python scripts/evals/evaluate_retrieval.py --live-kb-gate --max-live-calls 295 \
  --json-output .agents/tasks/headtohead-prereg/kb-gate.json

# 2. Laya on all 295 rows, on the host to be reported (needs laya and the weights).
python -m scripts.evals.benchmark_course_intent --checkpoint /path/to/laya-multilingual \
  --passes 3 --warmup 5 \
  --host-instance-type <TYPE> --host-vcpu <N> --host-ram-gb <GB> --host-arch <arm64|x86_64> \
  --json-output .agents/tasks/headtohead-prereg/laya-all-rows-multilingual.json
# Laya Learn: use  --checkpoint /path/to/vega --bundle /path/to/course-learner.zip  instead.

# 3. Analysis (offline, blocks the network, writes no message text).
python -m scripts.evals.compare_routing_arms \
  --kb-gate .agents/tasks/headtohead-prereg/kb-gate.json \
  --laya-full .agents/tasks/headtohead-prereg/laya-all-rows-multilingual.json \
  --json-output .agents/tasks/headtohead-prereg/comparison.json \
  --markdown-output .agents/tasks/headtohead-prereg/comparison.md
# Laya Learn file: add  --laya-full-kind learn
```

Result files stay in the git-ignored `.agents/` folder; commit them only with
`git add -f` and only if they hold no private data. Do not commit build output.

**`--live-kb-gate`.** Off by default. It requires `--max-live-calls N` with N from 1 to
295 (below 295 it sends an evenly spaced subset). It exits 2, before any client exists,
if N is missing or out of range, if `KNOWLEDGE_BASE_ID` or `COURSE_MATERIALS_BUCKET` is
unset, or if it is combined with `--live-kb`, `--live-model`, `--ids`, `--categories`,
`--expected-decision`, `--skip-sample` or `--compare-source-check`. Exit codes: 0 ran, 1
no call was answered, 2 refused, 3 stopped on the first auth or access error. Each call
goes through `BedrockKnowledgeBaseRetriever` with the production filter on
`course_material_id`, 12 candidates, at most 4 validated chunks, one attempt and the
production timeouts (10 s read). The record (`mode: live_kb_gate`) has, per message id,
the top validated score, result count, status (`ok`, `empty`, `unavailable`), failure
category, elapsed ms, raw hit count and exception class, plus the KB settings (no KB id,
bucket or account), git SHA, dirty flag and UTC time. It holds ids and categories only.

**`compare_routing_arms`.** Flags: `--kb-gate`, `--laya-results-dir` (default
`.agents/tasks/phase3d-work`), `--laya-full`, `--laya-full-kind {multilingual,learn}`,
`--plan`, `--json-output`, `--markdown-output`, and the extra-message flags below. Exit
0 means the report was written; 2 means refused (bad KB file, a Laya full-run file that
is a stub, incomplete or has unknown ids, or a plan whose constants differ from the
code). Every figure carries a status label: `measured`, `bound`, `missing`, or
`synthetic_test_data` for a KB file marked `synthetic_test_fixture: true` (the report then
opens with a "not a result" banner).

**`benchmark_course_intent` host run.** The host flags, the per-row `rows` output and
the refusal rules are described under "Laya production readiness" above. A `--stub-ms`
file is marked `real_model: false` and `--laya-full` refuses it.

### Extra messages: privacy and the `synthetic` flag

The optional `--extra-messages FILE` (on `evaluate_retrieval.py --live-kb-gate` and on
`compare_routing_arms`) is described in "Extra messages (optional, separate from the 295)"
under "Laya production readiness" above. The points that matter for this comparison:

- Extra rows are never split, never used to choose T, and never part of M1, M2, a paired
  test or a pass rule. They are descriptive, scored under the T frozen on the 295, and
  reported in a separate `extra_messages` section.
- Message and history text stays in memory. It is not written to JSON, Markdown, stdout,
  stderr or logs. Errors name a line, a field and a safe id, never a value. The text does
  go to the Knowledge Base in the live request, as in any chat turn. Keep ids anonymous.
- A row must carry `"synthetic": true`. A row with `false` is refused (exit 2) unless the
  operator passes `--allow-non-synthetic`, which marks the record and the report
  `real_messages`. A missing or non-boolean marker is always refused.

### IAM for the live gate

The live gate needs one action, `bedrock:Retrieve`, on the Knowledge Base resource:

```json
{
  "Effect": "Allow",
  "Action": "bedrock:Retrieve",
  "Resource": "arn:aws:bedrock:<region>:<account-id>:knowledge-base/<KB-ID>"
}
```

**Verified against AWS documentation (fetched when this section was written).** The
[Service Authorization Reference for Amazon Bedrock](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrock.html)
lists the `Retrieve` action (access level Read, SDK client `bedrock-agent-runtime`) with the
required resource type `knowledge-base`, whose ARN is
`arn:${Partition}:bedrock:${Region}:${Account}:knowledge-base/${KnowledgeBaseId}`, and the
condition key `aws:ResourceTag/${TagKey}`. The
[Retrieve API page](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html)
shows the call as `POST /knowledgebases/{knowledgeBaseId}/retrieve` and accepts either the
10-character id or a `knowledge-base` ARN as the identifier. That page does not state the
IAM policy; the policy form comes from the authorization reference. This repo's runbook
grants the same action and resource form to the EC2 role
(`docs/deploy/AWS_STATELESS_EC2.md`, "Bedrock Knowledge Base Retrieve"). Not tested
against a real account. Grant it to a short-lived operator identity and remove it
afterwards. Do not grant `bedrock:RetrieveAndGenerate`; the gate never calls it.

### Cost estimate (estimate, not a measurement)

- **Live gate.** At most 295 `Retrieve` calls. At the price the user supplied, $1 per
  1,000 Retrieve calls (an assumption, not checked against an AWS price page): 295 x $1 /
  1,000 = $0.295, so about $0.30 at most. The cap stops the run at N calls; each call is
  made once, with no retry.
- **What else the gate calls, from the code.** Nothing: no model call, no Converse, no
  S3 call, no `GetKnowledgeBase`. Wall time: if every call hit the 10 s read timeout, at
  most 295 x 10 s, about 49 minutes; the run stops sooner on the first auth error.
- **Billed by AWS for a Retrieve, beyond the $1 assumption.** Unknown. Third-party pages
  describe a managed Knowledge Base as billed per search with embeddings and reranking
  included, and a vector-store Knowledge Base as billed for its embedding model and vector
  store; I did not confirm either against an AWS pricing page, and the repo does not say
  which applies. Check the AWS bill for the Knowledge Base type in use.
- **Laya host run.** No AWS call (sockets are blocked and `HF_HUB_OFFLINE=1`). The cost is
  host time on the instance the operator chooses; its price is not estimated here.
- **Analysis command.** Offline; no cost.
- **Not priced:** CloudWatch or CloudTrail, data transfer, and the host's own cost.

## AgentCore vs direct Bedrock Converse benchmark (Phase 4 item 5, built, not run)

`scripts/evals/benchmark_agentcore_vs_converse.py` sends the same 50 fixed turns
through two paths and records latency, tokens, parse failures and an estimated
cost. It is a paid live tool. **It has not been run.** No AWS, Bedrock or
AgentCore call was made while building it; its tests (`tests/scripts/test_benchmark_agentcore_vs_converse.py`,
41 tests, script run) use stub clients and fail if a real client is built. It
lives beside `evaluate_retrieval.py` and reuses that script's gate, request
builder, Converse bridge, failure labels and run metadata through `scripts/evals/lib`
(`gate`, `live`, `output`). This document is the
home for it because the turns and the Fast Chat call come from the retrieval eval.

### The 50 turns (decision recorded)

Choice: derive them from the existing gate dataset, not a new file.
`select_benchmark_turns` takes `evenly_spaced_indices(295, 50)` over
`retrieval_gate_messages.synthetic.jsonl` in file order (row `i * 295 // 50`).
Every row is marked `synthetic: true`. The id list is pinned by SHA-256
(`TURN_IDS_SHA256`, first 12 characters `a79b9d5a5c9f`); the script refuses to
run if the dataset ever yields a different list. Deterministic: no random seed,
no clock, no network.

Composition (script run): 18 of the 19 categories (none from `not_in_course_material`);
11 `course_content`, 6 `greeting_thanks_chitchat`, 5 `project_reasoning`, the rest 1 to 3 each;
27 labelled `retrieve` and 23 `skip`. Three turns carry history, three carry
attachments, five have selected sources (script run). The set is not a sample of
real student traffic; it is a fixed, repeatable mix of turn shapes.

Both paths get the turn as `evaluate_retrieval --live-model` builds it, with
`source_need_check` off (production with `FAST_CHAT_NEEDS_SOURCES_ENABLED` off) and
no retrieved excerpts attached.

### Exact paths compared

| | AgentCore path | Direct Converse path |
|---|---|---|
| Call | `bedrock-agentcore` `invoke_agent_runtime(agentRuntimeArn=AGENTCORE_RUNTIME_ARN, qualifier=AGENTCORE_QUALIFIER, runtimeSessionId=stateless-<uuid>, payload=<Fast Chat payload JSON>, accept=application/json)` | `bedrock-runtime` `converse(modelId=COACHING_MODEL_ID, ...)`, or `converse_stream` with `--converse-stream` |
| Prompt and history | Built inside the runtime from the payload (`agent_system_prompt`) | The same payload through `LiveFastChatBridge.request_kwargs`; system prompt from `agent_system_prompt`, so the prefix cache point appears exactly when `FAST_CHAT_PROMPT_CACHE_ENABLED` is true in the benchmark process |
| Structured output | Strands agent, forced `FastChatTurnOutput` tool, up to 2 generations | Forced `toolChoice: {"any": {}}` with the same inlined `FastChatTurnOutput` schema, one generation |
| Extras | Bedrock guardrail on the output, event loop, recovery turn | None |
| Check | `_payload_from_runtime_response` then `_validated_fast_chat` | `LiveFastChatBridge.invoke` then `_validated_fast_chat` |
| Retries | `total_max_attempts` 1 | `total_max_attempts` 1 |

The differences in the last rows are the thing being priced, so they stay.
Both calls go to the model in `COACHING_MODEL_ID` only if the runtime is
configured with the same model; the result records the runtime's reported model id
(`runtime_model_ids_seen`) so a mismatch is visible.

What the numbers mean:

- `total_ms`: from just before the call to the complete response body, before
  local validation. Client-side wall time, including network and any runtime cold start.
- `first_text_ms`: equals `total_ms` for both paths by default, and the row says
  so (`first_text_basis`). The runtime returns one JSON object and a non-streaming
  Converse call returns one response, so neither can show text early (Phase 4
  item 4). `--converse-stream` makes the Converse arm report the time of the first
  `response_text` fragment. The AgentCore arm cannot. The runtime also reports
  its own `model_first_reply_text_ms`, recorded as `runtime_first_reply_text_ms`
  (inside the runtime, excludes network and cold start).
- Tokens: what each path reports. AgentCore: `model_input_tokens`,
  `model_output_tokens`, `cache_read_input_tokens`, `cache_write_input_tokens`
  from the runtime payload. Converse: `usage.inputTokens`, `outputTokens`,
  `cacheReadInputTokens`, `cacheWriteInputTokens`. A missing figure is `null`
  and the row is not priced; it is never counted as zero.
- Parse failure: no valid `FastChatTurnOutput` tool call, or a reply the Fast Chat
  contract rejects. Any other failed call (throttling, timeout, access) is a
  call failure. Failed calls still count against the cap.
- Order: even turns send AgentCore first, odd turns Converse first, so a prompt
  cache written by one path does not always benefit the same path. Both paths use
  the same model and prefix, so the second call of a turn can read what the first
  wrote. Cached-token comparisons are indicative, not clean.

### How `--max-live-calls` counts

One counter is shared by both paths and counts every call, successful or not.
Each turn costs 2 calls. A cap of N sends `N // 2` turns, evenly spaced over the
50 (`turns_for_limit`), so a pair is never split and an odd leftover call is not
used. N must be 1 to 100; the script also refuses N=1 because one turn needs 2.

| `--max-live-calls` | Turns | Calls |
|---|---|---|
| 2 | 1 | 2 (one AgentCore, one Converse) |
| 10 | 5 | 10 |
| 40 | 20 | 40 |
| 100 | 50 (the full set) | 100 (50 per path) |

The cap counts invokes, not model calls: the AgentCore runtime can make a second
model call inside one invoke (recovery turn). That second call is not capped by
the script; it appears in the reported tokens and in `runtime_cycle_count`.

### Safety rules

- Without `--max-live-calls`, or without `--live-benchmark`, the script prints
  `refused: ...` and exits 2 before any client is built. `--max-live-calls` outside
  1 to 100 also exits 2.
- It also refuses (exit 2, before any client) when `COACHING_MODEL_PROVIDER` is not
  `bedrock`, `COACHING_MODEL_ID` is not a Haiku model, the region is empty,
  `AGENTCORE_RUNTIME_ARN` is missing or not a `runtime/` ARN, or `AWS_REGION` differs
  from the region in that ARN.
- It stops after the first auth or access error in either path, records the first
  failure's exception class (and AWS error code), the exit code and a `run` block
  (git SHA, dirty flag, UTC timestamp). No message, reply or tool-input text is
  stored or printed in errors.
- Exit codes: 0 ran, 1 every call failed, 2 refused, 3 stopped early on an auth or
  access error. `--dry-run` (still needs `--max-live-calls`) prints the turn ids and
  the call count, builds no client.

### Exact commands

Run from the repo root with a Python environment that has `boto3`, the credentials
of an identity that holds the IAM below, and the production settings in the
environment (`COACHING_MODEL_PROVIDER=bedrock`, `COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`,
`AGENTCORE_RUNTIME_ARN`, `AGENTCORE_QUALIFIER`, `AWS_REGION=us-west-2`,
`AGENTCORE_MODEL_REGION=us-west-2`). Set `FAST_CHAT_PROMPT_CACHE_ENABLED` to the same
value as the deployed runtime. Do not run these without approval.

```sh
# 1. Free check of the plan: no client, no call.
python scripts/evals/benchmark_agentcore_vs_converse.py --dry-run --max-live-calls 100

# 2. Smoke: 1 turn, 2 calls (one per path).
python scripts/evals/benchmark_agentcore_vs_converse.py --live-benchmark \
  --max-live-calls 2 --json-output .agents/tasks/phase4-work/bench-smoke.json

# 3. Full set: 50 turns, 100 calls.
python scripts/evals/benchmark_agentcore_vs_converse.py --live-benchmark \
  --max-live-calls 100 --json-output .agents/tasks/phase4-work/bench-full.json

# 4. Same, with a measured first-text time on the Converse arm (needs the extra IAM action).
python scripts/evals/benchmark_agentcore_vs_converse.py --live-benchmark --converse-stream \
  --max-live-calls 100 --json-output .agents/tasks/phase4-work/bench-full-stream.json
```

### IAM required, per path

Not tested against a real account. Both paths use the credentials of whoever runs
the script; the runtime role's own grants do not apply to the caller.

**AgentCore path.** Action `bedrock-agentcore:InvokeAgentRuntime`. The AWS service
authorization reference lists two resource types for this action, `runtime`
(`arn:${Partition}:bedrock-agentcore:${Region}:${Account}:runtime/${RuntimeId}`) and
`runtime-endpoint` (`.../runtime/${RuntimeId}/runtime-endpoint/${Name}`). Grant both,
with the endpoint the qualifier names (`DEFAULT` here). The repo's own deployment
notes say the same ("runtime ... and its `DEFAULT` endpoint",
`docs/deploy/AWS_STATELESS_EC2.md` IAM section; `docs/SECURITY_BOUNDARIES.md`).

```json
{
  "Effect": "Allow",
  "Action": "bedrock-agentcore:InvokeAgentRuntime",
  "Resource": [
    "arn:aws:bedrock-agentcore:us-west-2:<ACCOUNT>:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7",
    "arn:aws:bedrock-agentcore:us-west-2:<ACCOUNT>:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7/runtime-endpoint/DEFAULT"
  ]
}
```

Per `docs/SECURITY_BOUNDARIES.md`, this action is a privileged generation backdoor
(the runtime dispatches on `phase`); give it only to a short-lived operator
identity, and remove it afterwards. The script sends `phase=fast_chat` only.
Sources: [Service authorization reference, Amazon Bedrock AgentCore](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html),
[InvokeAgentRuntime API](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html).

**Converse path.** Action `bedrock:InvokeModel` (it authorises `Converse`;
[Converse API guide](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html)).
The model id is a global cross-Region inference profile, so it needs the
three-resource form from the Phase 3c report section 9.3 (which cites the
[global cross-Region inference page](https://docs.aws.amazon.com/bedrock/latest/userguide/global-cross-region-inference.html)):

1. `arn:aws:bedrock:us-west-2:<ACCOUNT>:inference-profile/global.anthropic.claude-haiku-4-5-20251001-v1:0`
2. `arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`, with condition `bedrock:InferenceProfileArn` equal to resource 1 (and `aws:RequestedRegion` = `us-west-2`)
3. `arn:aws:bedrock:::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0`, with condition `bedrock:InferenceProfileArn` equal to resource 1 and `aws:RequestedRegion` = `unspecified`

With `--converse-stream`, add `bedrock:InvokeModelWithResponseStream` on the same
three resources (AWS: ConverseStream needs that action, Converse needs `InvokeModel`).

### Cost estimate (estimate, not a measurement)

Prices (estimate; confirm on the [AWS Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/),
which did not render when I looked): Claude Haiku 4.5 on the `global.` profile
$1.00 per million input and $5.00 per million output tokens, from third-party
pages ([Usage AI](https://instances.usage.ai/ai/claude-haiku-4-5),
[TypingMind](https://custom.typingmind.com/tools/estimate-llm-usage-costs/amazon-bedrock/anthropic-claude-haiku-4-5-20251001-v1-0));
cache read at 0.1x and cache write at 1.25x the input rate (assumed from Anthropic's published ratios;
a [Requesty page](https://www.requesty.ai/models/bedrock/claude-haiku-4-5-eu-west-3) shows a $0.11
cache read for the $1.10 regional price, which fits 0.1x). AWS says only that cached tokens are billed at
separate rates ([prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)).
AgentCore Runtime compute: the example on the [AgentCore pricing page](https://aws.amazon.com/bedrock/agentcore/pricing/)
uses $0.1276 per vCPU-hour and $0.0169 per GB-hour. The script's price constants are
`PRICE_USD_PER_MTOK`; its output labels every cost an estimate and prices model tokens only.

Tokens per call: about 7,100 input and 300 output (user-reported from the Phase 3b live
run). Cross-check (script run, characters / 4, offline, no call): the 50 turns average
about 6,900 estimated input tokens (median 6,500, range from 22,929 to 34,427 characters
of system prompt, history and tool schema).

Hand arithmetic, no cache hits: 7,100 x $1.00 / 1e6 + 300 x $5.00 / 1e6 = $0.0071 + $0.0015 = $0.0086 per call.

| Run | Calls | Model tokens, no cache | Notes |
|---|---|---|---|
| Smoke (cap 2) | 2 | about $0.017 | 1 turn |
| Full (cap 100) | 100 | about $0.86 | 50 per path |
| Full, runtime makes a second model call on every invoke | 100 (plus 50 uncapped) | about $1.29 | upper bound; recovery turn is rare |
| Full, prefix cache hits on all but the first call | 100 | about $0.34 | needs the cache point on in both arms; static prefix is about 23,100 characters (about 5,800 estimated tokens, script run), above the 4,096-token Haiku 4.5 minimum ([prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)) |
| AgentCore Runtime compute, 50 invokes | 50 | about $0.02 | assumes 10 s of wall time at 1 vCPU and 2 GB per invoke (an assumption, not measured) |

Not priced: the guardrail the runtime applies, CloudWatch, data transfer. Expected total
for the full run: about $0.9 (range $0.3 to $1.3), all hand arithmetic from the figures above.

Wall time is not estimated: no latency was measured. The worst case is 100 calls x
the 110-second read timeout, about 3 hours, if every call hung.

### Risks

- The two paths are not identical by design (guardrail, event loop, recovery turn); a
  latency or token gap is the sum of those, not one cause.
- Cache state is shared between the paths and across turns inside the 5-minute TTL,
  so cached-token and latency differences are partly an order effect (order alternates).
- 50 turns on one day describe one sample of the service, not a distribution; a
  single cold start or throttle can move a median at n=50.
- The runtime must be configured with the same model id as `COACHING_MODEL_ID` for the
  comparison to mean anything; check `runtime_model_ids_seen`.
- First-text latency is measurable on the Converse arm only with `--converse-stream`;
  there is no AgentCore equivalent while the runtime returns one JSON object.
