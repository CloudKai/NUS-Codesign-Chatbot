# AgentCore harness patch (structured coach_turn)

This overlay patches the existing `chatbot_harnessAgent` runtime so coaching
returns the companion app's `ProviderCoachOutput` JSON. It is **not** a second
student UI and must not be merged as the CDK `NUSCodesignChatbot/` stack.

Apply it on `origin/backend_setup_POC` (or the live runtime source), then
republish **the same** runtime
`NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` so `DEFAULT` tracks a
READY version that emits JSON.

## Why this patch exists

The live harness streams prose from a CDE2500 Socratic specialist. This
companion persists structured assessments and research coding. Prose-only
replies cannot be validated as `coach_turn`.

The FastAPI app sends:

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

`trusted_instructions` is application-owned shared coaching, the authoritative
stage file, and runtime/output rules. The last user message is untrusted
project context, retrieved evidence, summary/memory, and the current student
contribution (`compose_coach_prompt(..., include_recent_messages=False)`
untrusted product). Prior DSQL turns live only in `messages`.
`deep_analysis` is sent as topic `ethics_critical` only. Thinking Path rows in
DSQL stay `deep_analysis`. Invokes are **stateless** (fresh `runtimeSessionId`
per turn). Do not attach notebook history to AgentCore session memory.

Older companions that omit `trusted_instructions` still send the complete
composed brief as the last user message. This patch remains compatible: when
the field is absent, the thin JSON system prompt is used and the last user
message is invoked unchanged.

Coaching must keep **zero** Knowledge Base / MCP tools. Q&A may keep KB tools;
do not give them to the coaching specialist.

## Files to copy

Copy `structured_coach.py` next to `main.py` in `chatbot_harnessAgent/`.

## `phases.py`

At the top of `build_system_prompt`, do **not** add CDE2500 Q&A copy to
coaching when the caller asked for structured output. The companion app
selects the system prompt in `main.py` for `output_contract=coach_turn`, so
`phases.py` can stay unchanged if `main.py` overrides the system prompt.

## `main.py`

1. Import the helper:

```python
from structured_coach import coaching_invoke_prompts
import json
```

2. Keep `PHASE_TOOLS[phases.PHASE_COACHING] = []`.

3. When `payload.get("output_contract") == "coach_turn"`, append trusted
   instructions to the JSON system prompt and invoke **only** the untrusted
   user content (not the SSE event stream):

```python
@app.entrypoint
async def invoke(payload, context):
    phase = payload.get("phase", phases.DEFAULT_PHASE)
    topic = payload.get("topic")
    if payload.get("output_contract") == "coach_turn":
        system_prompt, prompt = coaching_invoke_prompts(payload)
        agent = Agent(
            model=load_model(),
            system_prompt=system_prompt,
            tools=[],
            callback_handler=None,
        )
        result = await agent.invoke_async(prompt)
        text = str(result).strip()
        if text.startswith("```"):
            raise ValueError("structured coaching output must be unfenced JSON")
        return json.loads(text)
    # existing streaming Q&A / scoring path unchanged
    ...
```

4. Do not enable shell or file tools from any AgentCore export.

5. Do not call `RetrieveAndGenerate`.

## Deploy

Republish this patch to the existing DEFAULT runtime **before** relying on the
companion adapter's trusted/untrusted split in live traffic. Confirm the
`DEFAULT` endpoint stays READY. Then run the companion smoke script with an
explicit cost cap:

```sh
.venv/bin/python scripts/agentcore_smoke.py \
  --i-approve-live-agentcore \
  --cost-cap 1.00 \
  --max-requests 1
```

Automated pytest never calls this runtime.

Do not attach AgentCore Memory or reuse `runtimeSessionId` as notebook history.
The companion DSQL/SQLite `messages` table is the only durable transcript.
