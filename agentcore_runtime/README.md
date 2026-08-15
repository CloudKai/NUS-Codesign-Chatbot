# Production AgentCore specialist runtime

This directory is the **authoritative** harness for

`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`.

One runtime hosts Q&A, Coaching, and Formative Review. Do not treat
`scripts/agentcore/harness_patch/` as a second implementation.

## Contract

1. `tools=[]` on every specialist — no Knowledge Base, S3, MCP, shell, or files.
2. Caller sends `phase` (`qa` | `coaching` | `review`). Unknown phases fall
   closed to coaching, never to Q&A-with-tools.
3. Canonical pedagogy lives in `prompts/`. FastAPI sends runtime rules only.
4. DSQL history is Strands `messages`. AgentCore Memory is not the transcript.
5. `invoke_async(..., structured_output_model=...)` then
   `result.structured_output`. Text-block JSON is a fallback.
6. Never `json.loads(str(result))`.
7. Failures return `{ok: false, error: true, category: ...}`.
8. Explicit `load_runtime_model()`: `AGENTCORE_MODEL_PROVIDER`,
   `AGENTCORE_MODEL_ID`, `AGENTCORE_MODEL_REGION`, `GUARDRAIL_ID`,
   `GUARDRAIL_VERSION`. No bare `BedrockModel()`. No Claude↔Luna fallback.

First paid evaluation: `bedrock` + `global.anthropic.claude-sonnet-4-6` +
`guardrail_latest_message=True`. Optional Luna:
`bedrock_mantle_responses` + `openai.gpt-5.6-luna` + `stateful=False` +
ApplyGuardrail. Pin versions in `requirements.txt`.

## Layout

```text
agentcore_runtime/
  main.py
  models.py
  structured_coach.py
  specialists/{qa,coaching,review,routing}.py
  prompts/shared_coaching.md
  prompts/qa.md
  prompts/review.md
  prompts/stages/{problem_identification,concept_generation,
                  design_specification,ethics_critical,reflection}.md
  contracts/{coach_turn,qa_turn,review_turn}.py
```

## Deploy

Do **not** change `AGENTCORE_RUNTIME_ARN`. Copy this **entire package** onto
the existing `chatbot_harnessAgent/` sources and publish a new READY version.

Rollback is the previous READY qualifier. Do not point DEFAULT at an untested
version.

```sh
.venv/bin/python scripts/agentcore_smoke.py \
  --i-approve-live-agentcore \
  --cost-cap 1.00 \
  --max-requests 1
```

## Tests

Pytest imports this package without Strands or AWS. Runtime pins are proven
by `scripts/diagnostics/check_agentcore_runtime_dependencies.py` after
`pip install -r agentcore_runtime/requirements.txt`.
