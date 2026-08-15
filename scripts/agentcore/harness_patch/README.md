# AgentCore harness patch (structured coach_turn)

Canonical production source: [`agentcore_runtime/`](../../../agentcore_runtime/).

This folder is **deployment documentation and a compatibility re-export**.
Do not maintain a second `json.loads(str(result))` implementation here.

## Why the old snippet was unsafe

The previous overlay used:

```python
result = await agent.invoke_async(prompt)
text = str(result).strip()
return json.loads(text)
```

Strands `AgentResult.__str__` concatenates text blocks. When
`structured_output` is missing and the message has no text, that string is
empty and `json.loads` raises `JSONDecodeError` at char 0. The student
message can still be present in the invoke payload.

## What to publish

Copy the entire `agentcore_runtime/` package:

- `main.py`, `models.py`, `model.py`, `guardrails.py`, `structured_coach.py`
- `specialists/`, `prompts/`, `contracts/`
- `requirements.txt`

Inject runtime env: `AGENTCORE_MODEL_PROVIDER`, `AGENTCORE_MODEL_ID`,
`AGENTCORE_MODEL_REGION`, `GUARDRAIL_ID`, `GUARDRAIL_VERSION`. Do not
construct a bare `BedrockModel()`.

Keep `tools=[]` on every specialist. Pass the matching
`structured_output_model` into `invoke_async`. Keep JSON return and SSE
`yield` in **separate** functions.

Do not change `AGENTCORE_RUNTIME_ARN`. Publish a new READY version of
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` after deterministic
tests pass. Do not point DEFAULT at an untested version.

## Companion payload

Unchanged: `trusted_instructions` + Converse `messages`,
`output_contract=coach_turn`, stateless `runtimeSessionId`.

Failures must return:

```json
{"ok": false, "error": true, "category": "structured_output_failure"}
```

or `"safety_blocked"` for guardrail intervention — never an empty body and
never a Python traceback.

## Smoke

```sh
.venv/bin/python scripts/agentcore_smoke.py \
  --i-approve-live-agentcore \
  --cost-cap 1.00 \
  --max-requests 1
```
