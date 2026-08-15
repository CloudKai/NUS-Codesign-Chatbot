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

`phase` is `qa`, `coaching`, or `review`, selected by FastAPI. Canonical
specialist and stage pedagogy live in `agentcore_runtime/prompts/`. FastAPI
must not resend a second full curriculum in `trusted_instructions`.

`student_id` is the store owner identifier, never a notebook id. The
token-aware planner sends the **full active DSQL transcript** when it fits
the conservative Luna-safe input budget. Only when that would overflow does
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
AGENTCORE_MODEL_ID=global.anthropic.claude-sonnet-4-6
AGENTCORE_MODEL_REGION=us-west-2
GUARDRAIL_ID=<configured guardrail>
GUARDRAIL_VERSION=<configured version>
KNOWLEDGE_BASE_ID=<configured KB>
MOCK_OPENAI=false
```

The published AgentCore runtime reads `AGENTCORE_MODEL_*` and `GUARDRAIL_*`
from **its own** process environment. FastAPI production validation requires
the same keys so the host `.env` cannot look ready while the runtime would
still construct a bare `BedrockModel()`. Missing model or guardrail config
fails closed. There is no Claude↔Luna fallback.

First paid specialist evaluation uses Sonnet 4.6 (`BedrockModel` with
`guardrail_latest_message=True`). Optional Luna uses
`AGENTCORE_MODEL_PROVIDER=bedrock_mantle_responses` and
`OpenAIResponsesModel(stateful=False, bedrock_mantle_config={"region": ...})`
plus Bedrock `ApplyGuardrail` on untrusted input and model output. Do not
pass `openai.gpt-5.6-luna` into `BedrockModel`.

Pinned runtime packages, pip-installed and API-checked in a clean CPython
3.12.10 venv on 2026-08-16 (companion pytest still does not install them;
GitHub job `agentcore-runtime-compatibility` does):

- `strands-agents==1.52.0`
- `bedrock-agentcore==1.21.0`
- `pydantic==2.13.4`

Confirm the same versions on the published runtime. Optional Luna extra is
`strands-agents[openai]==1.52.0` and is not required for Sonnet 4.6.

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

## Isolated Luna evaluation (not production traffic)

Live pedagogical evaluation uses **InvokeHarness** with an explicit

`openai.gpt-5.6-luna` / `apiFormat=responses` override. That path is
`backend/agentcore_harness_provider.py` plus
`scripts/evals/evaluate_live_coach.py`. It must not change production
`AGENTCORE_QUALIFIER=DEFAULT` or `MODEL_PROVIDER=agentcore`. Claude fallback
is disabled. Compression, if required on that path, also uses Luna.

## Deferred extras (do not copy from the POC)

Keep these off the Thinking Path unless a later phase explicitly adds them:

1. DEFAULT v14 is published and one capped Sonnet smoke passed. Do not treat
   that as student-ready until host `.env`, ECR, and CloudFront/Caddy are aligned.
2. Do not attach unrestricted KB/MCP tools to Q&A. Pre-retrieved `[S#]`
   evidence is the production path. Do not call `RetrieveAndGenerate`.
3. Do **not** add critique-every-Nth-turn, restore scoring-as-grade, restore
   a sixth `ethics_critical` application stage, restore AgentCore Memory as
   transcript, or merge the CDK student UI.
