# Amazon Bedrock AgentCore coach adapter handoff

**Implemented** in `backend/agentcore_provider.py` and selected with
`MODEL_PROVIDER=agentcore`. Automated tests inject a fake
`InvokeAgentRuntime` client in `tests/domain/test_agentcore_provider.py` and
never call AWS. Live smoke still requires an explicit cost cap.

FastAPI, Streamlit, Cognito, DSQL, and the five-phase Thinking Path stay in
this application. AgentCore Runtime is generation (and the course Knowledge
Base owner), not the student UI.

## Contract

Each coach turn makes **one** `InvokeAgentRuntime` call with:

```json
{
  "phase": "coaching",
  "topic": "problem_identification",
  "output_contract": "coach_turn",
  "student_id": "cognito:<sub>",
  "trusted_instructions": "<shared + stage + runtime>",
  "messages": [
    {"role": "user", "content": [{"text": "<prior DSQL turn>"}]},
    {"role": "assistant", "content": [{"text": "<prior coach reply>"}]},
    {"role": "user", "content": [{"text": "<untrusted current-turn content>"}]}
  ]
}
```

`student_id` is the store owner identifier, never a notebook id. The
token-aware planner sends the **full active DSQL transcript** when it fits
the conservative Luna-safe input budget. Only when that would overflow does
the planner compress older turns into derived `conversation_memory` and keep
a recent verbatim window (default 12). Trusted shared/stage/runtime
instructions travel in `trusted_instructions`. The last user message is the
untrusted product from `compose_coach_prompt(..., include_recent_messages=False)`
(project context, retrieved evidence, summary/memory, current student
contribution). Derived memory is model input only; DSQL remains the complete
transcript. A fresh `runtimeSessionId` (`stateless-…`) is still used per invoke.

Invariants:

- the request's persisted phase overrides a model-supplied phase;
- `deep_analysis` maps to AgentCore topic `ethics_critical` only; UI/DSQL stay
  `deep_analysis` with the student-facing label **Ethics & Critical Thinking**;
- structured `ProviderCoachOutput` / `coach_turn` JSON is mandatory (no markdown
  fence fallback);
- citations stay `[S#]` over selected notebook sources — no
  `RetrieveAndGenerate`;
- invokes are **stateless** (`runtimeSessionId` is a fresh `stateless-…` value,
  never a notebook id) so DSQL remains the only durable transcript;
- the coaching specialist must have **zero** Knowledge Base / MCP tools;
- images map to Converse-style JSON blocks or the adapter fails closed;
- provider exceptions map to category-only `ProviderUnavailableError`;
- `messageStop.stopReason=guardrail_intervened` or guardrail `action=BLOCKED`
  maps to `safety_blocked` before any refusal text is parsed.

The live harness must apply
[`scripts/agentcore/harness_patch/README.md`](../../scripts/agentcore/harness_patch/README.md)
so coaching returns JSON instead of prose **and** appends `trusted_instructions`
to the system prompt. Republish that patch to existing DEFAULT before relying
on the split in live traffic. Older payloads that omit the field still treat
the last user message as the complete brief.

## Configuration

```env
MODEL_PROVIDER=agentcore
AWS_REGION=us-west-2
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/<id>
AGENTCORE_QUALIFIER=DEFAULT
AGENTCORE_TIMEOUT_SECONDS=110
AGENTCORE_MAX_RETRIES=0
KNOWLEDGE_BASE_ID=JUQNP8AZAZ
MOCK_OPENAI=false
```

Production accepts OpenAI **xor** Bedrock **xor** AgentCore (not mock). Direct
`BedrockCoachProvider` Converse remains a fallback/test path.

## Live smoke

Do not run paid invokes from pytest. After the harness patch is deployed to
`DEFAULT` READY:

```sh
.venv/bin/python scripts/agentcore_smoke.py \
  --i-approve-live-agentcore \
  --cost-cap 1.00 \
  --max-requests 1
```

Without those flags the script refuses.

## Not a database

Aurora DSQL (and local SQLite) `messages` are the only durable transcript.
This adapter must keep invoking with a fresh `stateless-…` session id. Do not
wire AgentCore Runtime LRU, AgentCore Memory, DynamoDB, or a JSON file as chat
history. Student `GET /api/v1/threads/{id}/transcript.txt` is a projection of
`get_messages`.

## Isolated Luna evaluation (not production traffic)

Live pedagogical evaluation uses **InvokeHarness** with an explicit

`openai.gpt-5.6-luna` / `apiFormat=responses` override. That path is
`backend/agentcore_harness_provider.py` plus
`scripts/evals/evaluate_live_coach.py`. It must not change production
`AGENTCORE_QUALIFIER=DEFAULT` or `MODEL_PROVIDER=agentcore`. Claude fallback
is disabled. Compression, if required on that path, also uses Luna.

## Deferred extras (do not copy from the POC)

Keep these off the Thinking Path unless a later phase explicitly adds them:

1. Harness `coach_turn` JSON must be deployed to `DEFAULT` before live AgentCore
   coaching can persist assessments (overlay already in
   `scripts/agentcore/harness_patch/`).
2. Optional separate **Ask the course** Q&A mode (POC `phase=qa` specialist).
   Selected-source Bedrock `Retrieve` for locked Lecture Notes/Readings is
   already wired into the coaching composer. Do not give the coaching
   specialist unrestricted KB tools. Do not call `RetrieveAndGenerate`.
3. Do **not** add critique-every-Nth-turn, replace Review with a scoring
   specialist, restore a sixth `ethics_critical` stage, or merge the CDK
   student UI.
