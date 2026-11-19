# Retrieval evaluation

`scripts/evals/evaluate_retrieval.py` reports three numbers for course
retrieval: recall@4, wrong-skip rate and empty-result rate. It runs offline by
default.

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

- **Gate.** The script composes the repo's own rules-based retrieval gate
  (`resolve_mode_policy`, the attachment, stage-status, navigation and
  meta-guidance overrides, and `_wants_course_catalog_retrieval`) the way
  `backend/coaching/execution.py` does. See `gate_decision` in the script.
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

Item 1 added `definitional_question` to `_COURSE_CATALOG_RETRIEVAL_CUES`. All 16
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
production rule (`_wants_student_upload_retrieval`, imported, not copied) to
every gate row. The row's selected and attached files are projected into
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
