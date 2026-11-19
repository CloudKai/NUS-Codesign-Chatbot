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
  "`needs_sources` second chance" below.

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
model and an approved call limit. That run is not part of this item.

## Metric definitions

| Metric | Numerator | Denominator |
|---|---|---|
| recall@4 (material) | Questions where one of the top 4 results is in the expected material or in an `alt_expected` material. | All questions evaluated. |
| recall@4 (page) | Same, and the result page is one of the tagged pages of that material. A multi-page tag needs only one of its pages. | Questions evaluated. Reported only where results carry a page (offline). An empty result is a page miss. |
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
| `course_materials.json` | One entry per lecture PDF: `material_id`, `object_key`, `local_path`, `filename`, `group`, `source_id`, `pdf_pages`. |

The script validates all three files on load and stops with a `DatasetError`
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
  Page-level recall is `n/a` because Knowledge Base results carry no page.
- **Gate.** The gate numbers still come from the offline gate and make no call.
