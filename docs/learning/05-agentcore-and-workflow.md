# 5. Bedrock, AgentCore, the harness, and the educational workflow

[Handbook index](README.md) · [Next: removing AWS](06-without-aws-and-langgraph.md)

## 5.1 The names that are easy to confuse

| Name | What it means in this project |
|---|---|
| Foundation model | Haiku or Sonnet performing generation |
| Bedrock | AWS API/service access to model inference and related features |
| AgentCore Runtime | Hosting and invocation environment for the project's generation program |
| Project harness | Python code that receives a payload, builds prompts/model calls, validates results, and returns an agreed object |
| Strands | Library implementing the model/structured-output invocation loop inside the harness |
| FastAPI provider adapter | Client-side bridge from `CoachRequest` to AgentCore and back to a provider-neutral result |
| Bedrock Knowledge Base | Separate course evidence retrieval service, called by FastAPI |
| CoachWorkflow / LangGraph | Application orchestration around assessment and recommendation |

An analogy: Bedrock supplies the engine, Strands controls an invocation of that engine, the harness is the project-specific driver program, AgentCore Runtime is where that program runs, and FastAPI decides when and with what authorized context to ask it for work.

There is also an isolated [InvokeHarness evaluation adapter](../../backend/agentcore_harness_provider.py). It is a historical/experimental Luna evaluation path, not evidence that the active production DEFAULT uses a managed InvokeHarness loop. Do not merge every occurrence of “harness” into one architecture.

## 5.2 What was implemented in the project

The project owns [agentcore_runtime/main.py](../../agentcore_runtime/main.py), [model configuration](../../agentcore_runtime/model.py), [structured extraction](../../agentcore_runtime/structured_coach.py), [schemas](../../agentcore_runtime/models.py), prompt loaders, phase prompts, and specialist prompt assembly. The old `scripts/agentcore/harness_patch` location is not a second canonical runtime.

On the FastAPI side, [agentcore_provider.py](../../backend/agentcore_provider.py) serializes application context, invokes the configured runtime, validates the returned contract, and maps it into `ProviderAssessmentResult`. The provider boundary keeps the application from depending on a raw Strands `AgentResult`.

On the runtime side, the entrypoint dispatches based on server-owned phase/output-contract fields. Normal chat chooses `fast_chat`; explicit review chooses the relevant review contract; legacy router/qa/coaching modes remain supported. `app.run()` starts the runtime server when executed as the main program; merely importing the entrypoint is insufficient to host it.

The published environment and dependency package matter. Updating a FastAPI file does not update prompt files already packaged into AgentCore. The runtime's own manifest pins Strands, AgentCore SDK, and Pydantic, separately from the application image.

## 5.3 Normal Fast Chat

The active design combines Coaching versus Q&A behavior into one `fast_chat` invocation. It uses the configured Haiku model path. Compose currently declares Haiku 4.5 for lightweight roles and Sonnet 4.6 for Deep Review. These are repository configuration values, not a fresh check of runtime model provenance.

The runtime prompt combines shared pedagogical rules, the active phase prompt, Fast Chat mode rules, and trusted runtime constraints from FastAPI. The most recent student text and retrieved evidence are supplied as untrusted content. Historical messages come from SQL through the application; the runtime does not load its own transcript.

Source Q&A must answer from evidence when grounding is required. Coaching should help the student reason rather than complete the assignment for them. A Q&A answer should not silently award stage completion merely because it contains a useful explanation. Server policy can impose expected response mode for clear intents.

## 5.4 Structured output and why “valid JSON” is only the first step

The current slim Fast Chat schema includes `mode`, `response_text`, `recommendation`, `recommendation_rationale`, `citations`, `hmw_scaffold_ready`, `needs_source_retrieval`, and `out_of_scope`. Conversation memory is attached separately by the application-side planner/provider; it is not a field in this slim runtime output. The adapter checks schema identity and supported compatibility shapes. Conflicting recommendation fields or a wrong output contract must not be silently interpreted as a successful coach turn.

For example, a minimal coaching-shaped object can say:

```json
{
  "mode": "coaching",
  "response_text": "Which observation supports that assumption?",
  "recommendation": "stay",
  "recommendation_rationale": "The claim needs supporting evidence.",
  "citations": [],
  "hmw_scaffold_ready": false,
  "needs_source_retrieval": false,
  "out_of_scope": false
}
```

This illustrates the model output, not the complete API `CoachTurn`. The runtime wire serializer adds schema identity, and the application maps the result into its broader educational contract. In Q&A mode, recommendation can be absent/null and must not act as progression. Out-of-scope normalization clears progression and citation signals.

The extraction helper prefers `AgentResult.structured_output`. If absent, it can parse ordinary final text as exactly one JSON object and validate it. It does not use `str(AgentResult)` as student-visible content. Tool-use without a valid structured result, fenced markdown instead of the expected object, and safety stop reasons have explicit failure behavior.

Several models use Pydantic `extra="ignore"`, so do not claim every unexpected field is rejected everywhere. The meaningful guarantee is validation of the relevant accepted schema and invariants, including strict Fast Chat adaptation where required. Syntax validity is weaker than semantic contract validity.

For example, a payload can parse correctly but claim the wrong active phase. It must still be rejected or normalized according to server rules. A response can contain a syntactically valid `[S9]` citation, but if S9 was never supplied, it must not be accepted as evidence.

## 5.5 Why tools are empty but a structured-output tool can exist

Specialists use `tools=[]`: they have no application-exposed KB, S3, shell, database, or browsing tools. This prevents the model from choosing a different student's source or mutating learning records through a tool call.

Strands can represent the output schema as an internal structured-output tool. That formatting mechanism is different from granting external application capabilities. The runtime includes middleware that attempts to select the sole output tool on the first Fast Chat cycle, with telemetry distinguishing “middleware installed” from “choice actually applied.”

The code depends on a pinned Strands middleware interface. This reduced repair overhead in the intended design but introduces upgrade sensitivity. Its failure behavior permits the normal bounded invocation path to continue; a dependency compatibility test is therefore valuable.

## 5.6 One invocation is not necessarily one model API call

There are several counters:

1. A student logical turn.
2. An outer FastAPI-to-AgentCore invocation.
3. A Strands event-loop/model cycle inside that invocation.
4. Transport/model retry attempts.

A normal turn aims for one outer Fast Chat invocation. Structured-output repair can require internal work. A transient harness recovery or retrieval fallback can consume a second outer invocation. These counters are not interchangeable when estimating latency and cost.

The implementation records cycle/stop-reason telemetry where available. It does not invent a repair count when the SDK provides no such field. To claim a specific number of billable model calls, inspect actual runtime traces and usage evidence.

## 5.7 Guardrails and error behavior

The Bedrock model path requires guardrail ID and version. The checked production configuration uses version 4 on both application/runtime sides. The runtime scopes configured guardrail handling to the appropriate current untrusted content rather than treating every trusted prompt as student input.

A structured-output repair prompt was constrained to avoid a framework recovery instruction being misclassified as a prompt attack. This is integration work: the framework's internal behavior can interact with model safety processing even though the student's request is ordinary.

Safety intervention becomes a category such as `safety_blocked`; schema extraction failures become structured-output errors; provider transport failures map to safe unavailability handling. A blocked model result should not be persisted as if it were a valid educational assessment. Guardrails supplement application authorization; they cannot determine whether a source belongs to a notebook.

The project also contains a historical Mantle/OpenAIResponsesModel path with explicit ApplyGuardrail handling. Its presence should be taught as provider compatibility/history, not described as the active configured Haiku path.

## 5.8 Compute affinity versus memory

Production Compose enables AgentCore session affinity using owner/notebook-derived opaque compute identity and a generation value. Reusing warm compute can reduce repeated initialization overhead. SQL remains the transcript; each invoke still receives bounded canonical history.

Thus a warm runtime is a performance optimization, not the sole keeper of what the student said. A new session should still be able to answer based on supplied history. A warm session with outdated assets is a release compatibility problem, which is why a new runtime version requires new affinity generation and an app recreate.

The generation bump must actually reach the running container. As chapter 1 notes, the current explicit Compose value overrides a same-name host `.env` entry. Inspect effective deployment configuration rather than assuming the host file changed runtime behavior.

## 5.9 The five phases and application control

| Phase | Learning purpose | Example coaching focus |
|---|---|---|
| Problem identification | Frame a meaningful user/problem opportunity | Who experiences this, and what outcome matters? |
| Concept generation | Explore possible approaches | What genuinely different alternative could address the need? |
| Design specification | Make an idea concrete enough to examine | What requirement or constraint would let us evaluate it? |
| Ethics & Critical Thinking | Examine consequences, assumptions, perspectives | Who could be excluded or harmed, and what evidence would change your view? |
| Reflection | Explain learning and changed understanding | What changed, why, and what remains uncertain? |

The table is a teaching summary, not the literal complete rubric. Canonical runtime pedagogy lives under [stage prompts](../../agentcore_runtime/prompts/stages). The backend normalizes assessment and controls state.

Current production Compose has `STUDENT_STAGE_SELECTION=true` and `AUTO_ADVANCE_STAGES=false`. A readiness result leaves focus in place until the student takes a stage-movement action. Older confirmation-based transition APIs remain, and historical month-one auto-advance is not the current Compose behavior.

Guide maps to `response_detail=short`; Free maps to `long`. Their behavior is more than response length. The application includes How Might We candidate/structural guards for Problem identification and a Free-mode promotion rule. In the inspected implementation, Free-mode promotion can upgrade a nonempty eligible coaching STAY; it is not a separately measured universal “usable idea” classifier. Meta/status/prior-review handling subsequently limits progression effects.

The original architectural aspiration was fully model-validated recommendations without keyword progression heuristics. Current HMW helpers and explicit navigation parsing add deterministic application rules. Explain the shipped behavior and its tradeoff: predictable product progression, but additional policy logic that must be tested against the intended pedagogy.

Reflection ADVANCE means completion in place. It must not invent a sixth stage. Deep Review remains formative and should not independently advance the student's current phase.

## 5.10 Stage reviews and Deep Review are different jobs

Stage reviews capture a checkpoint for a completed stage, with frozen evidence and revision context. Revisiting a completed stage marks it dirty; leaving it can coalesce new work into a refreshed review. The [stage-review executor](../../backend/coaching/stage_review_jobs.py) uses a process-local pool, but queue state and execution fences are persisted. Existing Journey reads can resubmit queued work after a restart, and stale leases can be reclaimed.

Explicit Deep Review generates broader analysis after the Thinking Path, including Reflection, is complete. The browser cannot pick the privileged review specialist by posting a field on the ordinary coach request. The dedicated route freezes stage, revision, source IDs, and message IDs and schedules a background worker. The model configuration uses Sonnet for this operation.

Crucially, `enqueue_deep_review` accepts an idempotency key for HTTP compatibility but discards it. It reuses an existing queued/running job through job state. This is not the exact-key replay mechanism of normal coach turns. If you expose a public job API later, define its desired completed-key semantics explicitly.

The [Deep Review executor](../../backend/coaching/deep_review_jobs.py) is process-local. A restart can lose queued execution; stale job polling marks the job failed with timeout behavior. That differs from the stage-review resubmission path. “We persist job status” does not mean “every job automatically resumes after a crash.”

Deep Review has a 180-second runtime Bedrock read setting in the documented release configuration, a 200-second application AgentCore timeout, and a 240-second job stale/acceptance deadline. The deadline does not forcibly kill a Python thread. The outer timeout must leave space for the inner call and result handling.

## 5.11 Deep Review context and evidence references

[deep_review_context.py](../../backend/coaching/deep_review_context.py) distinguishes full-history review from a compatible checkpoint-plus-delta plan. Small, first, legacy, or incompatible reviews keep frozen history. Larger compatible reviews can supply a previous validated checkpoint, raw evidence anchors, and subsequent active messages.

Model-visible `M#` references map to exact frozen messages. The model should not invent database IDs or reactivate superseded branches. Only references exposed in the current context may resolve to durable supporting-message IDs. This preserves traceability while reducing repeated context.

A source-ID fingerprint is a compatibility check, not always a content hash. The code notes that a shared course object overwritten at the same key could retain its virtual ID. If review reproducibility requires exact historical document bytes, add immutable content versioning/checksums; do not assume identity alone proves unchanged content.

## 5.12 Research feedback and human review

The application distinguishes educational feedback from provisional research coding. Research coding includes CLEAR strategy labels, Facione behavior occurrences, ethics concepts, and evidence offsets. These are not automatically student grades. Invalid optional research coding must not discard a valid coaching turn. The broader application supports these records, but the slim Fast Chat output above does not itself contain the full research-coding or Facione-score schema; do not assume every ordinary Haiku turn returns all historical assessment fields.

The current domain enums make the terminology concrete: CLEAR is concise, logical, explicit, adaptive, reflective. Facione behavior tags are analysis, interpretation, inference, evaluation, explanation, and self-regulation. Ethics concepts include fairness, privacy, transparency, non-maleficence, and responsibility. A behavior occurrence is evidence that a kind of thinking appeared; a holistic score is an assessment across evidence. They should not be conflated.

Human reviewers append assessments of observations; adjudicators append resolutions. Keeping original observation, prompt/model provenance, and human amendments permits later analysis of disagreement. It also supports evaluating model changes without rewriting the evidence that was actually produced at the time.

The lecturer Review rail combines incremental and checkpoint evidence through a read projection. Projection means transforming existing stored data for display, not changing the original observations. This is a useful distinction when explaining why a UI feedback improvement could ship without a database migration.

## 5.13 Why not autonomous agents for every phase?

The phases share one notebook, one student, and one transition policy. Separate autonomous agents would need to negotiate context ownership, evidence scope, state changes, and failure/retry behavior. That can add latency and complicate reproducibility without guaranteeing better pedagogy.

This architecture uses specialized prompts/contracts where useful and keeps orchestration application-owned. A separate deeper review operation is justified by a different workload and response budget. Multiple autonomous agents would be more compelling for independently decomposable research tasks, such as separately checking several evidence sources, provided their outputs remain advisory and the application reconciles them.

That is a reasoned tradeoff, not evidence of a completed multi-agent benchmark. An interview answer should say what complexity was avoided and what experiment would justify adding it, rather than claiming agents are inherently worse.
