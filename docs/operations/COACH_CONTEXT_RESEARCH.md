# Context quality for Improve my design

Reviewed 27 November 2026 SGT. Research and implementation proposal for the
[Improve my design spec](../specs/IMPROVE_MY_DESIGN.md).

## Recommendation

Keep Fast Chat's existing input budgets for the initial implementation. Test
whether the coach finds the student's current design, intent, and constraints
within those budgets. When a request refers to older work, retrieve a small
number of excerpts from the active notebook and put the strongest one beside
the current request. Keep the recent exchange for continuity and use existing
derived memory as a fallback. A/B test a shorter stage-blind instruction prefix
to free room for evidence. Raise the budget only if these changes still leave
relevant context out of the prompt.

## Initial context budget and baseline

| Surface | Checked-in default |
| --- | --- |
| AgentCore Fast Chat input | 12,000 estimated tokens as a soft target and 16,000 as a hard input limit. The estimate accounts for system text, the current turn, evidence, images, and history. The planner uses a 4,000-token output reserve and a 1,000-token margin. |
| AgentCore recent history | Up to six historical messages, with 3,000 estimated tokens across the recent messages and 1,500 per historical message. The planner can trim earlier messages further when the combined context is large. |
| Composed text and evidence | The current student text is capped at 12,000 characters. Fast Chat allows up to four retrieved chunks and clips the retrieved text to 8,000 characters and project context to 2,000. Canvas text is capped at 3,500 characters, conversation memory at 8,000, and conversation summary at 4,000. Other current providers can receive inline recent messages, capped at six messages and 800 characters each. |
| Deep Review | The separate review lane defaults to an adjustable 210,000-token input ceiling. Its policy chooses full history or a qualifying checkpoint and transcript delta. The general planner's 272,000-token model-context setting includes a 32,000-token output reserve and a 30,000-token safety margin. |

These are application settings and estimates. The model cards advertise context
windows of 256K for Gemma 4 31B, 200K for Claude Haiku 4.5, and 1M for Claude
Sonnet 4.6. A November 2026 release record identifies Gemma for Fast Chat,
Haiku as its rollback path, and Sonnet for Deep Review. The recorded Gemma
adapter caps reasoning plus visible output at 2,048 tokens per model call.
If a broader path is reused with another model, clamp its input ceiling to
the selected model and transport after accounting for output and overhead.
For example, the general 210,000-token input ceiling exceeds Haiku's entire
200K window. Current production configuration was outside this review.
[Settings](../../backend/settings.py) ·
[AgentCore adapter](../../backend/agentcore_provider.py) ·
[Composer](../../backend/prompts/composer.py) ·
[Review context](../PROMPT_ARCHITECTURE.md#ownership) ·
[Provider configuration](../providers/MODEL_PROVIDERS.md) ·
[Gemma model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-google-gemma-4-31b.html) ·
[Haiku model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html) ·
[Sonnet model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html)

An offline `problem_identification` Fast Chat sample using the checked-in
demo context produced an estimated 10,554 input tokens. The system prompt
accounted for 10,212. The other 342 covered the current untrusted content block
(285, including about 30 for evidence and 28 for the student request), recent
history (49), and message overhead (8). This single sample contained no memory
or images. It used the local planner's estimator without provider tokenization
or transport-specific schema overhead. [Demo context](../../scripts/preview_prompt.py) ·
[Runtime system-prompt estimator](../../agentcore_runtime/system_prompt_budget.py)

SQLite and DSQL retain the complete transcript. Derived memory fills some of
the gaps when older messages leave the recent window. The initial compressor
extracted text using English keyword patterns. It kept the first recognized
selected concept, capped category lists, and used the last eligible compressed
student turn as a working conclusion. That made some student corrections hard
to distinguish from the earlier choice. The planner can also omit derived
memory when input is crowded. [Context planner](../../backend/context_planner.py)

The original AgentCore path included stage-derived context in the adapter and
the runtime system prompt. The application also supplied the stage and
conversation summary to retrieval. The Improve spec called for mode-specific
instructions and stage-state inputs at those boundaries. Both modes can read the
shared transcript and use the same authorized evidence, with retrieval gated
per turn. Student-authored stage references remain transcript content. The
Project Brief reads the whole active transcript and can incorporate both modes'
turns in a mixed chat.
[Execution](../../backend/coaching/execution.py) ·
[AgentCore adapter](../../backend/agentcore_provider.py) ·
[Runtime Fast Chat prompt](../../agentcore_runtime/specialists/fast_chat.py) ·
[Project Brief context](../../backend/coaching/project_brief.py)

## What the studies support

- Liu et al. varied where relevant information appeared in question-answering
  and key-value retrieval inputs. The tested models often performed better
  with relevant material at the start or end of long inputs than in the middle.
  For this coach, test whether placing the referenced design evidence near the
  current request helps. The paper measures other models and tasks.
  [Lost in the Middle, TACL](https://aclanthology.org/2024.tacl-1.9/)
- Hsieh et al. found that strong single-needle retrieval could coexist with
  declining performance as context length and task complexity increased. Their
  benchmark includes tracing and aggregation. A coach can remember a budget
  number and still miss the trade-off that explains the budget decision, so
  test multistep use of context as well as factual recall.
  [RULER, COLM 2024](https://arxiv.org/abs/2404.06654)
- Wu et al. evaluate dialog memory across retrieval, multi-session and temporal
  reasoning, knowledge updates, and abstention. Their results support trying
  smaller retrievable conversation units and indexing facts or dates where
  useful. For this repo, start by retrieving existing transcript excerpts with
  their role and order preserved. Add an index only if the initial evaluation
  shows a recall gap. [LongMemEval, ICLR](https://arxiv.org/html/2410.10813)

## Proposed behavior

1. When the student names a design and a focus, address them on the first
   turn. When the focus is open, ask one targeted question grounded in the
   available selection or recent chat. Start from the student's selected
   canvas or artifact and current constraints when supplied.
2. For a reference to older work, try a bounded lookup over active saved turns
   in the same notebook. Pass the matched excerpts as untrusted content with
   their speaker and chronology. Treat later explicit student corrections as
   authoritative for their stated preferences, and preserve earlier choices
   for comparison when requested. Ask a short clarification when no excerpt
   establishes the missing detail.
3. Keep transcript recall separate from evidence retrieval. The student’s
   prior choice can ground a follow-up, while claims about course readings
   and private source files still use the evidence gate and validated citations.
   Verify that an Improve send preserves existing stage decisions and that
   switching back resumes the saved Design coaching stage.

## Evaluation before changing a budget

Compare the current bounded planner with targeted recall at the same input
budget. Compare context placement separately by shifting the same evidence
between the middle of the supplied context and a position beside the current
request. Evaluate prompt length independently by holding the retrieved context
and response contract fixed while comparing a full stage-blind instruction
prefix and a shorter version that preserves coaching, grounding, and safety
rules. Use synthetic notebooks that isolate the following outcomes.

| Case | Expected result |
| --- | --- |
| The student said early on that the bin sign costs at most $30, then asks for an accessible alternative many turns later. | The reply preserves the $30 constraint and applies it to the proposed change. |
| The student initially chose QR codes, later switched to pictograms because the site has patchy internet, and asks whether the latest design still needs a phone. | The reply identifies pictograms as current and uses the internet constraint where relevant. |
| A selected sketch shows a narrow handle. The student asks for a change people can operate with one hand. | The coach addresses the selected handle directly, with a usable trade-off or test. A course search is unnecessary for this prompt. |
| The student asks whether their selected prototype follows a named method from the course. | The reply uses the selected design and verified course evidence, distinguishing observations from the method. |
| The student asks why they rejected a material that does not appear in the chat. | The coach asks for the missing reason or acknowledges the gap. |
| A mixed chat has a pending stage recommendation when the student switches to Improve and asks about a constraint mentioned during Design coaching. | The coach can recover the constraint. The provider request omits application-owned stage instructions, and the pending recommendation stays available after switching back. |

Score inclusion of the right evidence, preservation of student corrections,
useful first-turn feedback, and citation support. Track estimated tokens and
provider input tokens separately, alongside reply latency when available.
Use deterministic mocks to check packing, ownership, revisions, and stage
invariants. Use a separate explicitly authorized model comparison to measure
answer quality, since mock responses cannot measure recall by a live model.
The combined mock run passed 68 tests across planner, prompt architecture,
Fast Chat packing, and conversation memory continuity.
[Planner tests](../../tests/domain/test_context_planner.py) ·
[Prompt architecture tests](../../tests/domain/test_prompt_architecture.py) ·
[Fast Chat context tests](../../tests/domain/test_fast_chat_context.py) ·
[Memory continuity tests](../../tests/domain/test_conversation_memory_continuity.py)

## Priorities after integrating the context review

The integrated branch keeps the latest explicit concept selection, preserves
unrelated decisions, removes a duplicated HMW rubric, and puts retrieved course
evidence beside the current question. It still relies on recent messages and
derived memory for older conversation details. The existing scenarios verify
payload and workflow behavior with mocks. Generated-answer quality, actual
provider token counts, and cache savings remain unmeasured.
[Integration and review record](../IMPLEMENTATION_STATUS.md#current-status)

A fresh offline sample asked “How can I improve the visibility of my crossing
timer?” with a short response and empty history, sources, and images. The table
counts the reconstructed runtime system prompt and the final user text block
separately at three characters per estimated token. Reproduce it with the
scenario test's fake provider: submit a `CoachRequest` with those fields, the
corresponding intent and stage, and other fields at their defaults. Decode
`client.calls[0]["payload"]`, then run `estimate_tokens` on
`specialist_system_prompt(payload)` and on the text of the last message's first
content block. These estimates exclude transport and schema overhead.
[Scenario fixture](../../tests/domain/test_context_scenarios.py) ·
[Runtime system prompt](../../agentcore_runtime/structured_coach.py) ·
[Estimator](../../backend/context_planner.py)

| Fast Chat mode and stage | System estimate | User block estimate |
| --- | ---: | ---: |
| Design coaching, Problem identification | 9,989 | 239 |
| Design coaching, Concept generation | 7,408 | 239 |
| Design coaching, Design specification | 7,182 | 239 |
| Design coaching, Ethics & Critical Thinking | 7,562 | 239 |
| Design coaching, Reflection | 7,314 | 239 |
| Improve my design | 572 | 205 |

1. **Compact Design coaching instructions first.** Use a concise shared
   coaching contract and one stage rubric per request. Consolidate repeated
   rules and overlapping examples by hand. Hold the student context and output
   contract fixed. Keep the stage-specific checks, grounding and citation rules,
   and explicit stage confirmation. Use the existing offline prompt-variant
   harness as a starting point for measurement. Target at least 20% lower
   median estimated system tokens over all five stages with every deterministic
   contract check passing. A shorter prompt can lose useful examples and fall
   below the Haiku cache threshold, so measure quality and cache economics as
   separate experiments. LongLLMLingua supports testing information density
   and placement on long inputs. Its reported gains come from other models
   and tasks. [Offline prompt harness](../../scripts/evals/benchmark_prompt_variants.py) ·
   [Runtime assembly](../../agentcore_runtime/specialists/fast_chat.py) ·
   [LongLLMLingua, ACL](https://aclanthology.org/2024.acl-long.91/)
2. **Give Improve a budgeted recall path.** Use the active, authorized notebook
   transcript already loaded by execution. When the student refers to an older
   decision, rank a small number of original excerpts by entity overlap and
   order. Keep speaker, chronology, and any adjacent turn that establishes a
   correction or rationale. Deduplicate against the recent exchange and pin
   the applicable constraint or selection during packing. The current planner
   can evict the whole memory block under pressure. Start with a per-turn
   projection and the existing durable memory format. Lexical matching can
   miss paraphrases and multilingual references, so score it against a hand-
   labeled evidence set before adding an index or model call. Test an oracle
   variant with the known matching excerpts at the same budget. The gap to
   oracle helps identify retrieval misses, while failures with oracle evidence
   point to reading or response generation. Keep recalled turns untrusted and
   validate course citations through the existing evidence path.
   [Execution](../../backend/coaching/execution.py) ·
   [Planner](../../backend/context_planner.py) ·
   [LongMemEval, ICLR, §3.4 and §5](https://arxiv.org/html/2410.10813v2)
3. **Calibrate the budget against the selected provider.** Start with existing
   planner metrics and provider usage, grouped by model, mode, stage, and
   payload type. Where supported, count a small set of synthetic, fully
   composed requests through the matching provider API. Include tools, images,
   and multilingual samples where the surface supports them. Bedrock exposes
   model-specific counting on supported Runtime and Mantle surfaces. Verify
   support for the exact model and transport before using a count. For Converse
   caching, track uncached, read, and write tokens separately and add them to
   obtain total input. On Haiku 4.5, compare cold writes and warm same-prefix
   reads, including cache misses, before changing cache policy. Keep counting
   off the normal reply path and keep the current Fast Chat ceilings while
   establishing the baseline. [Turn metrics](../../backend/turn_perf.py) ·
   [Bedrock token counting](https://docs.aws.amazon.com/bedrock/latest/userguide/count-tokens.html) ·
   [Bedrock caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html) ·
   [Haiku 4.5 model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html)

Start by replaying the existing six synthetic cases. Add coverage for an edited
or inactive turn, a paraphrased or multilingual reference, and a large turn
that competes with a relevant memory item for prompt space. At the existing
ceilings, the recall candidate should include more labeled excerpts on older
references, preserve recall on recent ones, and exclude other notebooks and
inactive revisions in every case. For an explicitly authorized, capped model
comparison, use the same inputs and a blinded rubric for correct constraints,
useful design feedback, unsupported claims, citations, and stage behavior.
Record input tokens across all model calls, including retries, and time to
first reply text. Keep Deep Review on its existing context policy for these
Fast Chat experiments.

## Paired offline surrogate study (2026-11-27)

This follows the priorities above with a deterministic payload build and a
blinded, rubric-scored surrogate run. It measures prompt/context coverage and
rubric behavior, not the production coach.

**Method.** Requests were assembled through the real Fast Chat provider path
with the fake AgentCore client (no network, no application model call), then
answered by Hermes `x-test-2` as a surrogate. Twenty Design cases cover four
cases per stage (`problem_identification`, `concept_generation`,
`design_specification`, `ethics_critical`, `reflection`): each is a usable
answer, a premature/solution-locked or unsupported answer, a citation-gap
question with source knowledge disallowed, and a stay case. Twelve Improve
cases ask for one aged-out detail after an unrelated recent exchange.
Candidate arms: compact shared coaching + compact `fast_chat.md` (and the
compact Problem Identification stage file), with canonical stage files for the
other four stages; the recall candidate instead adds a bounded
`<older_student_excerpts>` block while holding the canonical prompt fixed.
Scoring is deterministic against gold `mode`, `recommendation`, citations,
scaffold flag, required/forbidden phrases, and required recall fact; verdicts
are computed before arm labels are read. One answer per case per arm, generated
in one batch per arm per stage.

| Stage | Design cases (base / candidate) | Estimated system tokens (base → candidate) |
| --- | --- | --- |
| Problem Identification | 4/4 / 4/4 | 9,924 → 5,344 (−46.2%) |
| Concept Generation | 4/4 / 4/4 | 7,343 → 4,985 (−32.1%) |
| Design Specification | 4/4 / 4/4 | 7,117 → 4,759 (−33.1%) |
| Ethics & Critical Thinking | 4/4 / 4/4 | 7,497 → 5,140 (−31.4%) |
| Reflection | 4/4 / 4/4 | 7,249 → 4,891 (−32.5%) |
| Improve older-detail recall | 4/12 → 12/12 | prompt fixed; excerpt adds ~30–70 user-block tokens per case |

No rubric regression appeared at this sample size: both arms kept the stage
contract in the usable, premature, citation-gap and stay cases, both advanced a
complete Reflection in place, and both refused to grade. The compact
candidate is still above the estimated Haiku cache floor in every stage, but
the actual provider tokens and cache eligibility were not measured.

The recall arm isolates the excerpt: the canonical prompt was fixed in both
arms. Without it, four of twelve details survived — the ones derived memory or
constraints already carried (`$30`, the pictogram selection, the matte/glare
reason, the December deadline). The other eight (measurement, name, location,
count, weather, dimensions, percentage, part swap) were absent from the
baseline payload and recovered only with the excerpt. So the gain depends on
whether packing/memory already surfaces the detail; injecting an excerpt that
duplicates memory adds tokens without new recall.

**Limitations.** One surrogate model, one answer per case per arm, batches of
four to twelve records (cross-case leakage possible), and deterministic rubric
scoring rather than an independent human or second-model grader. Four design
cases per stage cannot establish an accuracy rate, and the rubric checks listed
fields, not pedagogical quality. Token figures are local 3-chars/token
estimates. The compact Problem Identification file and the compact shared
contract were changed together, so their separate contributions are not
isolated. A first recall fixture was discarded because a single aged-out user
message is stored as `problem_definition` by the extractive compressor, which
hid the gap; the reported recall run puts a neutral turn before the fact.

**Next exact step.** Get explicit approval and a hard cap for a small live
AgentCore comparison (same cases, blinded grading, recorded input/uncached/
cache-read tokens), or expand the offline set to 10+ cases per stage with an
independent grader. Do not adopt the compact prompts or the excerpt path on
this evidence alone; keep the dedupe-against-memory requirement from priority 2.

Evidence: `/private/tmp/coach_context_stage_study` (`build_requests.py`,
`requests/`, `answers/`, `score.py`, `score.txt`, `manifest.json`) and the
earlier three-case run in `/private/tmp/coach_context_study` (`score.md`).
