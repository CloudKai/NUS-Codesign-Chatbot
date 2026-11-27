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

## What reaches the model today

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
the gaps when older messages leave the recent window. The current compressor
extracts text using English keyword patterns. It keeps the first recognized
selected concept, caps category lists, and uses the last eligible compressed
student turn as a working conclusion. A student correction can therefore become
hard to distinguish from the earlier choice. The planner can also omit derived
memory when input is crowded. [Context planner](../../backend/context_planner.py)

AgentCore includes stage-derived context both in the adapter and in its runtime
system prompt. The application also supplies the stage and conversation summary
to the retrieval path. To make Improve my design stage-blind, build mode-specific
instructions and stage-state inputs at each of these boundaries. Both modes can
read the shared transcript and use the same authorized evidence, with retrieval
gated per turn. Treat student-authored references to a stage as transcript
content. The existing Project Brief reads the whole active transcript and can
incorporate both modes' turns in a mixed chat.
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
