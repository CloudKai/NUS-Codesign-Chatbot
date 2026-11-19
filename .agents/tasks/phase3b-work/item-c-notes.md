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
