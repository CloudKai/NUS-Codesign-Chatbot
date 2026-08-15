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

Pytest imports this package without Strands or AWS.
