# Phase 3b item C: follow-up cases and the "clearly fail" definition

Branch `improvement/backend`. Base `27e54ae` (item B). No `review-c.json` existed, so this is the first round.

This section was written and committed **before** any follow-up case existed in the repository and before any measurement. The commit order is the audit trail: this definition first, then the cases, then the measurement.

## What is being decided

Whether to implement follow-up rewriting (turning a short follow-up such as "how many dots does each person get?" into a self-contained course query using chat history). The brief says: implement only if the new follow-up cases clearly fail.

## Case set to be added (fixed now)

- 12 short follow-up cases, all `synthetic: true`, each with the prior turn(s) it depends on in the existing `history` field.
- 9 are labelled `retrieve` (course follow-ups). 3 are labelled `skip` (follow-ups that need no course search).
- Each `retrieve` case sets `question_id` to the standalone question in `retrieval_questions.jsonl` that expresses the same information need, and `expected_material` to that question's material. The standalone question is the attribution control (see below).
- Existing rows are not edited. The 295-message numbers must stay comparable, so the new cases are reported as a separate block.

## What is measured

For every new case, two things, using the production code and not a copy of its decisions where that is possible:

1. **Gate decision.** `gate_decision(row)` in `scripts/evals/evaluate_retrieval.py`, which composes the repo's rules-based gate. It reads the message only. History is not an input to the gate (`backend/coaching/execution.py`, `_prepare_authoritative_turn`). Gate result for a `retrieve` case: the gate searches the course catalog on the first pass. For a `skip` case: the gate searches nothing.
2. **Query actually built from history.** The query text that `BedrockKnowledgeBaseRetriever` sends in the Retrieve call, captured from an injected recording client (no network). It is produced by `contextual_course_query_text` and `expand_session_query_text` in `backend/retrieval.py`, bounded by `FAST_CHAT_PROJECT_CONTEXT_CHARS`. The history is passed the way production passes it (`recent_messages`, role plus content).
3. **Retrieval with that query.** The captured query text is sent to the offline lexical course search (`OfflineCourseSearch`) as the message with **no** history. The Knowledge Base takes only the query text, so the stand-in must not see history that the Knowledge Base would not see. The existing offline search adds recent user turns as extra weights (`_query_weights` in `backend/retrieval.py`). That is a local-retriever behaviour the Knowledge Base adapter does not have, so it is **not** used for the verdict. It is reported for contrast.

The offline search is a lexical stand-in for the Knowledge Base. Its hits describe the stand-in, not the real Knowledge Base. The verdict below is therefore about the query text, with the stand-in as a proxy for whether that text carries enough content to find the right material.

## Per-case outcomes

For a `retrieve` case:

- **gate_ok**: the gate searched the course on the first pass.
- **query_ok**: with the built query, one of the top 4 offline results is in `expected_material`.
- **end_to_end_pass**: `gate_ok` and `query_ok`.
- **standalone_ok** (control): the linked standalone question passes the gate as a normal message (course searched) and its top 4 contain `expected_material`.
- A failure is **attributable to the follow-up form** only if `standalone_ok` is true. If the standalone version fails too, the cause is the known no-cue gate gap or the stand-in search, not the follow-up form, and rewriting would not help.

For a `skip` case: **gate_ok** means the gate searched nothing. These cases check that a follow-up the gate already skips is not turned into a search. They cannot trigger rewriting.

## Definition of "clearly fail" (threshold)

Implement follow-up rewriting only if **both** hold:

1. **At least 5 of the 9 `retrieve` cases (a majority) fail end to end** (`gate_ok` false or `query_ok` false), and
2. **At least 5 of those failures are attributable** (`standalone_ok` true for the case).

Anything else means the cases do **not** clearly fail, and nothing is implemented. The report then states the per-case results and stops. In particular:

- Gate-only failures with a passing standalone control count toward the threshold (a follow-up the gate skips while the standalone question is searched is a follow-up-form failure). Gate-only failures whose standalone control also fails do not.
- A case where the second chance (`needs_sources`, off by default) would recover the search is still counted as a gate failure under the default configuration. The `needs_sources` flag handles gate misses without a rewriter and is already shipped behind a setting, so the notes record separately how many gate failures have a recoverable second chance. That count is informational and does not change the threshold.
- `skip` cases never count toward the threshold.
- The threshold is fixed here. It will not be changed after the numbers are seen. If the result sits exactly on the line, that is reported as such, and the decision follows the rule as written (5 of 9 triggers; 4 of 9 does not).

## Why this threshold

- A majority of a small synthetic set is the lowest bar that is more than noise from one or two odd phrasings. With 9 cases, 4 failures could come from two or three unusual rows.
- Requiring the standalone control to pass stops the item from fixing a different problem. The no-cue gate gap (92 wrong skips in Phase 2) is already addressed by `needs_sources`. A rewriter would be the wrong tool for that gap.
- Rewriting changes what the retrieval query says and adds code with a cost (a model call or more rules), so it needs evidence that today's query building cannot find the right material from the follow-up.

## Limits stated up front

- 12 cases written by one author. They are synthetic and carry the author's idea of how students ask.
- The offline search is lexical. A real Knowledge Base uses embeddings and may handle some short follow-ups better or worse. A negative result here does not prove the live Knowledge Base is fine, and a positive one does not prove it fails. A live check is not part of this item and was not run.

---

# Results (written after the measurement)

Everything above this line was committed in `929f0c0` before any case or number existed. Everything below was written after.

## Commit order (audit trail)

1. `929f0c0` definition and threshold (this file, above the line).
2. `58b54b5` the 12 cases (`scripts/evals/datasets/retrieval_gate_followups.synthetic.jsonl`). The cases were written from `retrieval_questions.jsonl` (labels and evidence), not from any gate or search output. One message (gm298) was reworded once before this commit because its first wording read oddly. No measurement existed yet.
3. The measurement code, tests and docs, in the item commit `Phase 3b item C: ...`.

## Choice: new file, not new rows

New rows in `retrieval_gate_messages.synthetic.jsonl` would change every headline number of the 295-message set (wrong-skip, false-retrieve, category split, the `needs_sources` stub block) and the tests that assert 295, 76 and 7. A new file `retrieval_gate_followups.synthetic.jsonl` keeps those numbers identical by construction. The row format is the same, so `validate_messages` is reused (with `min_count=1`) and the ids continue at `gm296`. `load_followups` adds three checks: ids do not collide with the gate messages, each row is a follow-up with history, and each `retrieve` row has `question_id` and `expected_material`. No existing row or label was edited.

## What query building does with history (evidence)

- **Gate:** history is not an input. `gate_decision` (`scripts/evals/evaluate_retrieval.py`) mirrors `_prepare_authoritative_turn`, which reads the message and selected sources (`backend/coaching/execution.py`, around 2832 to 3034 per the script docstring).
- **History reaches the retriever:** `_retrieve_for_turn` (`execution.py:2372`) builds `RetrievalQuery(recent_messages=tuple(recent_messages))`. The callers pass `store_history` (`execution.py:3110`, first pass) and `list(request.history)` (`execution.py:2593`, second chance).
- **Knowledge Base query text:** `bedrock_retrieve.py:884` calls `contextual_course_query_text(query, max_chars=settings.fast_chat_project_context_chars)`, then `expand_session_query_text` (`bedrock_retrieve.py:888`), and sends that text in the single Retrieve call (`bedrock_retrieve.py:965`).
- **When history is used:** `contextual_course_query_text` (`backend/retrieval.py:259`) returns the message unchanged unless `is_anaphoric_course_lookup` (`retrieval.py:152`) is true. That needs all three of: a course-source word (lecture, reading, source, course material ...), an anaphoric cue ("that", "this idea", "what I just said", "my previous point" ...), and a question form. Then it adds the nearest substantive active **user** message (`most_recent_substantive_user_contribution`, `retrieval.py:233`). Assistant turns are never used. Summaries and project context are added only if they share terms.
- **Local retriever only:** `_query_weights` (`retrieval.py:1044`) also weights the last two user turns at 0.75. The Knowledge Base adapter does not do this. The existing `OfflineCourseSearch.search(message, history)` therefore sees history that the Knowledge Base would not. It is reported as a contrast, not used for the verdict.

Measured: 1 of the 9 `retrieve` cases (gm300, "which lecture is that from?") had its query changed by history. Its built query is `Current source question: which lecture is that from? Prior student reasoning: what is the rule of threes?`. The other 8 are sent as the bare message.

## Measurement method (implemented, offline, no network)

`captured_kb_query` runs the production `BedrockKnowledgeBaseRetriever` with a recording client that returns no results, and keeps the query text of the one Retrieve call. The text is then searched with `OfflineCourseSearch.search(text)` and no history. `evaluate_followups` adds the gate decision, the standalone control (the linked question as a normal message), and a contrast with the history-weighted local search. The verdict comes from `followup_verdict`, which holds the 5-and-5 constants written above. The measurement did not change the `retrieval` or `gate` blocks. A JSON comparison of `after-b.json` and `after-c.json` shows the only difference is the new `followups` key.

## Per-case results

Gate: does the gate search the course on the first pass. Query: top 4 for the built query hold `expected_material`. Control: the linked standalone question passes the gate and its top 4 hold the material.

| Case | Message | Gate | Query | End to end | Control | Why it passed or failed |
|---|---|---|---|---|---|---|
| gm296 | what is it good for? | fail | fail | **FAIL** | pass | Message has no course word and no topic. The classifier says ambiguous, so no search. The bare query "what is it good for?" matches reading pages, not the creative matrix. Attributable. |
| gm297 | what are the axes? | fail | fail | **FAIL** | pass | Same cause. The bare query returns no result at all in the offline search. Attributable. |
| gm298 | what goes in each part? | fail | fail | **FAIL** | fail | No topic in the message. The standalone question ("How do I write a job statement? What goes in WHEN I, BUT, HELP ME and SO I?") is also skipped by the gate. Not attributable. |
| gm299 | how many should I focus on? | fail | pass | **FAIL** | fail | Gate skips (no cue). The bare query matched the personas reading at rank 2 on the word "focus", which is luck. Standalone ("How many personas should I focus on?") is also skipped by the gate. Not attributable. |
| gm300 | which lecture is that from? | pass | pass | **PASS** | pass | The only case that uses history: "lecture" plus "that" triggers `is_anaphoric_course_lookup`, and the earlier user turn is added to the query. |
| gm301 | how would that change the HMW about transport at NUS? | fail | pass | **FAIL** | fail | Gate skips (no cue). The message already names HMW and transport, so the bare query finds Week 8. The standalone question is also skipped by the gate. Not attributable. |
| gm302 | what should I write for emotion? | fail | pass | **FAIL** | fail | Gate skips. The bare query finds Week 10 on "emotion". The standalone question is also skipped. Not attributable. |
| gm303 | and the F-pattern? | fail | pass | **FAIL** | pass | Gate skips: ellipsis, no cue. The bare query is specific enough ("F-pattern") for Week 9. The standalone question has "what is" in it, so the gate searches it. Attributable. |
| gm304 | does it have any authority? | fail | pass | **FAIL** | fail | Gate skips. The bare query matches the Pixar reading on "authority". The standalone question is also skipped. Not attributable. |
| gm305 | ok so i will fill one in for our bike lock idea | pass | n/a | **PASS** | n/a | `skip` case: nothing searched. |
| gm306 | and also the staff at the counter | pass | n/a | **PASS** | n/a | `skip` case: nothing searched. |
| gm307 | thanks, got it | pass | n/a | **PASS** | n/a | `skip` case: nothing searched. |

## Decision

Applying the recorded rule: 8 of 9 `retrieve` cases fail end to end (at least 5: met). 3 of those 8 are attributable to the follow-up form (at least 5: **not met**). The cases do **not** clearly fail. **Nothing was implemented.** No follow-up rewriting, no new setting, no change under `backend/`.

What the numbers say, in plain terms:

- The dominant failure is the gate: 8 of 9 `retrieve` follow-ups are not searched on the first pass. 5 of those 8 fail for the same reason the standalone question fails: no course-word cue, the known gap (Phase 2: 92 wrong skips). This is the problem `needs_sources` addresses, not rewriting.
- All 8 gate misses are eligible for the `needs_sources` second call (`gate_second_chance`). With a perfect model, 6 of 9 pass end to end and 2 attributable failures remain (gm296, gm297). That variant is informational only.
- Query building uses history in a narrow case (1 of 9). For the other 8 the bare message was enough for the lexical stand-in in 5 of them (gm299, gm301, gm302, gm303, gm304) and not enough in 3 (gm296, gm297, gm298). Those 3 are the real candidates for rewriting: short messages with no topic word ("what is it good for?", "what are the axes?", "what goes in each part?"). 3 of 9 is below the threshold of 5.
- The `skip` follow-ups were not searched (0 of 3 false retrieves), so nothing here argues for loosening the gate.

Sensitivity: the verdict rests on the attribution requirement. The failure count alone (8 of 9) meets the first condition, so if the follow-up form were blamed for every failure the rule would be met. The control says otherwise for 5 of the 8: the standalone question is skipped by the gate too, so the same message with the topic spelled out would still not be searched. Using the query check alone, 3 of 9 cases fail (gm296, gm297, gm298), below 5. A live Knowledge Base uses embeddings and may rank a bare "what are the axes?" differently from the lexical stand-in. That was not measured and is the main open question. If the owner wants rewriting for topic-less one-liners like gm296 to gm298, that is a product decision to take with a live check, not a result of this eval.

## Before and after numbers

Existing 295 gate messages and 94 questions: **unchanged** (`after-b.json` and `after-c.json` are identical except for the new `followups` key).

| Metric | Before (`after-b.json`) | After (`after-c.json`) |
|---|---|---|
| recall@4, material (94 questions) | 91/94 (96.8%) | 91/94 (96.8%) |
| recall@4, page | 78/94 (83.0%) | 78/94 (83.0%) |
| wrong-skip, 295 messages | 76/154 (49.4%) | 76/154 (49.4%) |
| false-retrieve, 295 messages | 7/141 (5.0%) | 7/141 (5.0%) |
| empty-result, gate-passed course searches | 1/63 (1.6%) | 1/63 (1.6%) |
| follow-up cases (new, separate) | not measured | gate wrong-skip 8/9, gate false-retrieve 0/3, query_ok 6/9, end to end 1/9, standalone control 4/9, 8 failures with 3 attributable |

## Settings and docs

No new setting, so `.env.example` is unchanged. `docs/RETRIEVAL_EVAL.md` gained a "Follow-up cases" section and a row in the data table. `scripts/evals/datasets/README.md` lists the new file. `docs/RAG_ARCHITECTURE.md` is untouched because no behaviour changed. Both prompt copies and `tests/domain/test_prompt_stage_drift.py` are untouched and pass.

## Tests and checks

- New tests in `tests/scripts/test_evaluate_retrieval.py` (5): the file loads and stays apart from the gate messages, the loader rejects rows with no history or no link or a colliding id, the verdict at 5/5 (clearly fail), 4/4 and 8/4 (not), the captured query comes from the adapter (history added for the anaphoric lecture case, bare message otherwise), and the follow-up block leaves the 295-message numbers alone.
- `ruff check .`: all checks passed.
- Full mock suite: 2480 passed, 2 failed, 1 skipped (136 s). The 2 failures are the known baseline `tests/http/test_notebook_reader.py` tests that need `frontend/dist`. Item B ended at 2475 passed, so the difference is the 5 new tests.
- No live call of any kind was made. No live mode was run.
