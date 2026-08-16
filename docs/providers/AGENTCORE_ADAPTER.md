# Amazon Bedrock AgentCore coach adapter handoff

**Implemented** in `backend/agentcore_provider.py` and selected with
`MODEL_PROVIDER=agentcore`. Automated tests inject a fake
`InvokeAgentRuntime` client in `tests/domain/test_agentcore_provider.py` and
never call AWS. Live smoke still requires an explicit cost cap.

FastAPI, Streamlit, Cognito, DSQL, and the five-phase Thinking Path stay in
this application. AgentCore Runtime is generation (and the course Knowledge
Base owner), not the student UI.

## Contract

Free-text turns may make **more than one** `InvokeAgentRuntime` call on the
same runtime ARN:

1. A small Haiku **router** (`phase=router`, `output_contract=router_turn`)
   unless FastAPI already stamped a server-owned specialist.
2. The selected specialist (`qa` | `coaching` | explicit `review`).
3. Incremental Haiku Review (`phase=review`, `review_mode=incremental`) after
   a successful Coaching turn.
4. Deep Sonnet Review (`phase=review`, `review_mode=deep`) on periodic or
   event triggers (explicit Review, readiness candidate, Reflection
   checkpoint, or every N successful new Coaching turns).

Q&A never advances the Thinking Path. Incremental Review cannot advance.
Deep Review may recommend stay/advance; FastAPI still validates and
persists. AgentCore never writes DSQL.

Periodic Deep Review means every N newly executed, successful Coaching
turns since the previous successfully persisted Deep Review. It is
turn-based rather than time-based because it represents new learning
evidence, not elapsed time. Opening the Review tab does not invoke a
model.

The runtime execution role must allow `bedrock:InvokeModel` for Haiku 4.5
and Sonnet 4.6. Historical Luna versions also needed
`bedrock-mantle:CreateInference` on
`arn:aws:bedrock-mantle:us-west-2:<account>:project/default` and
`bedrock-mantle:CallWithBearerToken`; keep those statements for rollback.
Current DEFAULT does not use Mantle.

Specialist payloads look like:

```json
{
  "phase": "coaching",
  "topic": "problem_identification",
  "output_contract": "coach_turn",
  "student_id": "cognito:<sub>",
  "runtime_context": {
    "current_stage": "problem_identification",
    "response_detail": "strict",
    "language": "English",
    "allowed_citations": ["S1"],
    "allow_model_knowledge": false
  },
  "trusted_instructions": "<application runtime rules only>",
  "messages": [
    {"role": "user", "content": [{"text": "<prior DSQL turn>"}]},
    {"role": "assistant", "content": [{"text": "<prior coach reply>"}]},
    {"role": "user", "content": [{"text": "<untrusted current-turn content>"}]}
  ]
}
```

`phase` is `qa`, `coaching`, or `review` after routing. Canonical specialist
and stage pedagogy live in `agentcore_runtime/prompts/`. FastAPI must not
resend a second full curriculum in `trusted_instructions`. The router payload
contains only the current student message plus optional current stage.

`student_id` is the store owner identifier, never a notebook id. The
token-aware planner sends the **full active DSQL transcript** when it fits
the conservative Haiku-safe input budget. Only when that would overflow does
the planner compress older turns into derived `conversation_memory` and keep
a recent verbatim window (default 12). Application runtime rules travel in
`trusted_instructions` and `runtime_context`. Canonical pedagogy is loaded
inside `agentcore_runtime/`. The last user message is the untrusted product
from `compose_coach_prompt(..., include_recent_messages=False)`
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
  maps to `safety_blocked` before any refusal text is parsed;
- empty, fenced, or schema-invalid AgentCore bodies map to
  `structured_output_failure`, never `json.loads(str(AgentResult))`.

The live DEFAULT harness source of truth is
[`agentcore_runtime/`](../../agentcore_runtime/). It hosts Q&A, Coaching, and
Formative Review with Strands `structured_output_model` and returns validated
JSON or a category-only error envelope. Publish a zip with `main.py` at the
root, vendored linux/arm64 Python 3.14 site-packages (AgentCore does not
pip-install `requirements.txt`), and entrypoint
`opentelemetry-instrument main.py`. `main.py` must call `app.run()` under
`__name__ == "__main__"`. Do not create a second runtime.
[`scripts/agentcore/harness_patch/`](../../scripts/agentcore/harness_patch/)
is deployment notes plus a compatibility re-export.

## Configuration

```env
MODEL_PROVIDER=agentcore
AWS_REGION=us-west-2
AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:<account>:runtime/<id>
AGENTCORE_QUALIFIER=DEFAULT
AGENTCORE_TIMEOUT_SECONDS=110
AGENTCORE_MAX_RETRIES=0
AGENTCORE_MODEL_PROVIDER=bedrock
AGENTCORE_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
AGENTCORE_MODEL_REGION=us-west-2
ROUTER_MODEL_PROVIDER=bedrock
ROUTER_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
QA_MODEL_PROVIDER=bedrock
QA_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
COACHING_MODEL_PROVIDER=bedrock
COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
REVIEW_INCREMENTAL_MODEL_PROVIDER=bedrock
REVIEW_INCREMENTAL_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
REVIEW_DEEP_MODEL_PROVIDER=bedrock
REVIEW_DEEP_MODEL_ID=global.anthropic.claude-sonnet-4-6
ROUTER_MIN_CONFIDENCE=0.60
DEEP_REVIEW_INTERVAL_TURNS=3
GUARDRAIL_ID=<configured guardrail>
GUARDRAIL_VERSION=3
KNOWLEDGE_BASE_ID=<configured KB>
MOCK_OPENAI=false
```

The published AgentCore runtime reads per-role `*_MODEL_*` keys plus shared
`AGENTCORE_MODEL_REGION` and `GUARDRAIL_*` from **its own** process
environment. Legacy `AGENTCORE_MODEL_PROVIDER` / `AGENTCORE_MODEL_ID` remain
as a local/testing fallback only when no role keys are set. FastAPI
production validation requires explicit role configuration. Missing model or
guardrail config fails closed. There is no Haiku↔Sonnet fallback.

Roles:

- ROUTER, Q&A, COACHING, INCREMENTAL REVIEW → Claude Haiku 4.5 (`bedrock`)
- DEEP REVIEW → Claude Sonnet 4.6 (`bedrock`)

Changing model environment variables requires a new AgentCore Runtime
**version** on the same ARN, not a new runtime resource.

DEFAULT Haiku and Sonnet use
`BedrockModel(model_id=..., region_name=..., guardrail_id=...,
guardrail_version=..., guardrail_latest_message=True)`
(`GUARDRAIL_VERSION=3`). Do not pass `openai.gpt-5.6-luna` into
`BedrockModel`. Do not pass Haiku into Mantle. Historical Luna runtimes
used `OpenAIResponsesModel(stateful=False, bedrock_mantle_config={"region": ...})`
plus Bedrock `ApplyGuardrail` on untrusted input and model output.

Pinned runtime packages, pip-installed and API-checked in a clean CPython
3.12.10 venv on 2026-08-16 (companion pytest still does not install them;
GitHub job `agentcore-runtime-compatibility` does):

- `strands-agents==1.52.0`
- `bedrock-agentcore==1.21.0`
- `pydantic==2.13.4`

Confirm the same versions on the published runtime. Historical Luna
runtimes also needed the `strands-agents[openai]==1.52.0` extra in the
published zip. Current Haiku/Sonnet DEFAULT uses `BedrockModel` only.

Production accepts OpenAI **xor** Bedrock **xor** AgentCore (not mock). Direct
`BedrockCoachProvider` Converse remains a fallback/test path.

## Live smoke

Do not run paid invokes from pytest. After `agentcore_runtime/` is published
to `DEFAULT` READY:

```sh
PYTHONPATH=. .venv/bin/python scripts/agentcore_smoke.py \
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

## Isolated InvokeHarness evaluation

Live pedagogical evaluation can still use **InvokeHarness** with an explicit
`openai.gpt-5.6-luna` / `apiFormat=responses` override. That path is
`backend/agentcore_harness_provider.py` plus
`scripts/evals/evaluate_live_coach.py`. It must not change production
`AGENTCORE_QUALIFIER=DEFAULT` or `MODEL_PROVIDER=agentcore`. Claude fallback
is disabled. Compression, if required on that path, also uses Luna.

Production DEFAULT generation is the AgentCore runtime with Haiku 4.5
(lightweight roles) and Sonnet 4.6 (Deep Review), not this InvokeHarness
adapter.

## Deferred extras (do not copy from the POC)

Keep these off the Thinking Path unless a later phase explicitly adds them:

1. DEFAULT uses Haiku 4.5 + Sonnet 4.6 + guardrail version 3. Do not treat
   the app as student-ready until host `.env`, ECR, and CloudFront/Caddy
   stay aligned.
2. Do not attach unrestricted KB/MCP tools to Q&A. Pre-retrieved `[S#]`
   evidence is the production path. Do not call `RetrieveAndGenerate`.
3. Periodic Deep Review is already the N-turn checkpoint (not a grade).
   Do **not** restore scoring-as-grade, a sixth `ethics_critical`
   application stage, AgentCore Memory as transcript, or the CDK student UI.
