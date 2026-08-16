# Production AgentCore specialist runtime

This directory is the **authoritative** harness for

`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7`.

One runtime hosts one-call Haiku `fast_chat` plus legacy router, Q&A,
Coaching, Incremental Review, and Deep Review. Do not treat
`scripts/agentcore/harness_patch/` as a second implementation.

## Contract

1. `tools=[]` on every specialist — no Knowledge Base, S3, MCP, shell, or files.
2. Active normal chat sends `phase=fast_chat` and `output_contract=fast_chat_turn`.
   Legacy `phase` values (`router` | `qa` | `coaching` | `review`) remain for
   compatibility. Review also sends `review_mode` (`incremental` | `deep`).
   Unknown specialist phases fall closed to coaching, never to Q&A-with-tools.
3. Canonical pedagogy lives in `prompts/`. FastAPI sends runtime rules only.
   The combined `fast_chat` prompt must not role-play router → coach → reviewer.
4. DSQL history is Strands `messages`. AgentCore Memory is not the transcript.
5. `invoke_async(..., structured_output_model=..., structured_output_prompt=...)`
   then `result.structured_output`. Text-block JSON is a fallback. The custom
   repair prompt is `Please use the output tool now.` so Guardrail v3 does not
   classify the Strands structured-output recovery turn as PROMPT_ATTACK.
6. Never `json.loads(str(result))`.
7. Failures return `{ok: false, error: true, category: ...}`.
8. Per-role `load_runtime_model()` via `COACHING_*` (fast_chat/Haiku) /
   `REVIEW_DEEP_*` plus shared `AGENTCORE_MODEL_REGION`, `GUARDRAIL_ID`,
   `GUARDRAIL_VERSION`. Router / Q&A / Incremental Review keys are optional
   legacy. `AGENTCORE_MODEL_PROVIDER` / `AGENTCORE_MODEL_ID` are a local
   fallback only when no role keys are set. No bare `BedrockModel()`. No
   Haiku↔Sonnet fallback.

Roles:

- FAST CHAT / COACHING → `bedrock` + `global.anthropic.claude-haiku-4-5-20251001-v1:0`
- DEEP REVIEW → `bedrock` + `global.anthropic.claude-sonnet-4-6`

Changing these environment variables publishes a new Runtime **version** on
the same ARN. Do not create a second runtime resource.

Deep Review is invoked only when FastAPI sends an explicit Review payload.
This runtime never starts a second phase internally for a normal request.

Periodic Deep Review is configured on FastAPI
(`DEEP_REVIEW_INTERVAL_TURNS`), not inside this runtime. FastAPI decides
when to send `review_mode=deep`. Periodic Deep Review means every N newly
executed, successful Coaching turns since the previous successfully
persisted Deep Review. It is turn-based rather than time-based because it
represents new learning evidence, not elapsed time.

## Layout

```text
agentcore_runtime/
  main.py
  models.py
  structured_coach.py
  specialists/{qa,coaching,review,fast_chat,routing}.py
  router.py
  prompts/router.md
  prompts/fast_chat.md
  prompts/review.md
  prompts/review_incremental.md
  prompts/review_deep.md
  stage_judge.py / prompts/stage_judge.md / contracts/stage_judge_turn.py
    (compatibility only; leftover judge payloads map to Deep Review)
  prompts/shared_coaching.md
  prompts/qa.md
  prompts/stages/{problem_identification,concept_generation,
                  design_specification,ethics_critical,reflection}.md
  contracts/{coach_turn,qa_turn,review_turn,router_turn}.py
```

## Deploy

Do **not** change `AGENTCORE_RUNTIME_ARN`. Publish a zip with `main.py` at the
root (flat layout, not nested `agentcore_runtime/`), vendored linux/arm64
Python 3.14 site-packages, and entrypoint
`opentelemetry-instrument main.py`. `main.py` must call `app.run()` under
`__name__ == "__main__"` or the process exits and InvokeAgentRuntime returns
502. Overlay this package onto the existing `chatbot_harnessAgent` artifact;
do not create a second runtime.

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
