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
  "prompt": "<compose_coach_prompt text>"
}
```

Invariants:

- the request's persisted phase overrides a model-supplied phase;
- `deep_analysis` maps to AgentCore topic `ethics_critical` only; UI/DSQL stay
  `deep_analysis`;
- structured `ProviderCoachOutput` / `coach_turn` JSON is mandatory (no markdown
  fence fallback);
- citations stay `[S#]` over selected notebook sources — no
  `RetrieveAndGenerate`;
- invokes are **stateless** (`runtimeSessionId` is a fresh `stateless-…` value,
  never a notebook id) so DSQL remains the only durable transcript;
- the coaching specialist must have **zero** Knowledge Base / MCP tools;
- images map to Converse-style JSON blocks or the adapter fails closed;
- provider exceptions map to category-only `ProviderUnavailableError`.

The live harness must apply
[`scripts/agentcore/harness_patch/README.md`](../../scripts/agentcore/harness_patch/README.md)
so coaching returns JSON instead of prose.

## Configuration

```env
MODEL_PROVIDER=agentcore
AWS_REGION=us-west-2
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/<id>
AGENTCORE_QUALIFIER=DEFAULT
AGENTCORE_TIMEOUT_SECONDS=110
AGENTCORE_MAX_RETRIES=0
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

## Deferred extras (do not copy from the POC)

Keep these off the Thinking Path unless a later phase explicitly adds them:

1. Harness `coach_turn` JSON must be deployed to `DEFAULT` before live AgentCore
   coaching can persist assessments (overlay already in
   `scripts/agentcore/harness_patch/`).
2. Optional separate **Ask the course** mode using KB `Retrieve` mapped onto
   locked course `source_id`s, still saved in DSQL. Do not give the coaching
   specialist unrestricted KB tools. Do not call `RetrieveAndGenerate`.
3. Do **not** add critique-every-Nth-turn, replace Review with a scoring
   specialist, restore a sixth `ethics_critical` stage, or merge the CDK
   student UI.
