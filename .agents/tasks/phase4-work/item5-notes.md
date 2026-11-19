# Phase 4 item 5 notes: AgentCore vs direct Bedrock Converse benchmark harness

**No live command was run** (no AWS, Bedrock, AgentCore, KB, OpenAI or paid call). The harness is built and stub-tested only. No `gate-item5.json` existed, so this was the implementation pass.

Marks: **(script run)**, **(hand)** counted or computed by hand, **(user-reported)**, **(estimate)**, **(doc)** from documentation.

## What changed and why

New script `scripts/evals/benchmark_agentcore_vs_converse.py`. It sends the same fixed 50 turns through two paths and records latency (first text, total), input/output/cache-read/cache-write tokens, parse failures and an estimated cost. It reuses `evaluate_retrieval.py` for the gate, request builder, `LiveFastChatBridge`, failure labels, auth-error classifier and `_write_json_output` (run block), so the safety style matches. No backend change, no new setting (nothing to add to `.env.example`).

## Files changed

- `scripts/evals/benchmark_agentcore_vs_converse.py` (new)
- `tests/scripts/test_benchmark_agentcore_vs_converse.py` (new, 41 tests)
- `docs/RETRIEVAL_EVAL.md` (new section "AgentCore vs direct Bedrock Converse benchmark"; chosen over a new doc because the turns and the Fast Chat call come from the retrieval eval)
- `docs/IMPLEMENTATION_STATUS.md` (new entry above the item 4 entry)
- `scripts/AGENTS.md`, `tests/AGENTS.md` (one table row each)

## The 50-turn set (decision)

Derived from the existing synthetic gate dataset, no new file: `evenly_spaced_indices(295, 50)` over `retrieval_gate_messages.synthetic.jsonl`, i.e. rows `i * 295 // 50` in file order. All rows have `synthetic: true`. Deterministic because there is no seed, clock or network, and the selected id list is pinned by SHA-256 (`TURN_IDS_SHA256 = a79b9d5a5c9f0b26e42eef9de70187c902964cb0166436d58252376ce5a0ff37`); `select_benchmark_turns` raises `BenchmarkRefused` if the dataset ever yields a different list. Alternative considered: a new synthetic file. Rejected: a second copy of rows that already carry labels, history and attachments.

Composition (script run): 50 ids, 18 of 19 categories (missing: `not_in_course_material`); `course_content` 11, `greeting_thanks_chitchat` 6, `project_reasoning` 5, others 1 to 3; 27 `retrieve` / 23 `skip`; 3 with history, 3 with attachments, 5 with selected sources.

Turns are built as in `--live-model` but with `source_need_check` off (production with `FAST_CHAT_NEEDS_SOURCES_ENABLED` off) and no retrieved excerpts.

## Exact paths compared

- **AgentCore:** `bedrock-agentcore` `invoke_agent_runtime(agentRuntimeArn, qualifier, runtimeSessionId=stateless-<uuid>, payload=<Fast Chat payload from AgentCoreCoachProvider._invoke_payload>, contentType/accept=application/json)`, parsed by the provider's `_payload_from_runtime_response`, checked by `_validated_fast_chat`.
- **Converse:** `bedrock-runtime` `converse` (or `converse_stream` with `--converse-stream`) on `COACHING_MODEL_ID`, arguments from `LiveFastChatBridge.request_kwargs(payload)` (same history, same inlined `FastChatTurnOutput` tool, `toolChoice any`), system prompt from `agent_system_prompt(payload)` so the prefix cache point appears exactly when `FAST_CHAT_PROMPT_CACHE_ENABLED` is true in the benchmark process. Checked by the bridge parser and `_validated_fast_chat`.
- Kept differences: Converse has no guardrail, no Strands event loop, no recovery turn. Both: `total_max_attempts` 1, one call per turn.

Metric definitions: `total_ms` = just before the call to the full body, before validation. `first_text_ms` = `total_ms` unless `--converse-stream` (neither the runtime nor a non-streaming Converse returns partial text; item 4 evidence). Missing usage is `null`, not zero. Parse failure = no valid tool call or contract rejection (also `ProviderUnavailableError` categories `structured_output_failure`, `malformed`); everything else is a call failure. Order alternates (even turns AgentCore first) to spread the shared-cache effect.

## Exact commands (not run)

```sh
python scripts/evals/benchmark_agentcore_vs_converse.py --dry-run --max-live-calls 100
python scripts/evals/benchmark_agentcore_vs_converse.py --live-benchmark --max-live-calls 2 --json-output .agents/tasks/phase4-work/bench-smoke.json
python scripts/evals/benchmark_agentcore_vs_converse.py --live-benchmark --max-live-calls 100 --json-output .agents/tasks/phase4-work/bench-full.json
python scripts/evals/benchmark_agentcore_vs_converse.py --live-benchmark --converse-stream --max-live-calls 100 --json-output .agents/tasks/phase4-work/bench-full-stream.json
```

Environment: `COACHING_MODEL_PROVIDER=bedrock`, `COACHING_MODEL_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0`, `AGENTCORE_RUNTIME_ARN`, `AGENTCORE_QUALIFIER`, `AWS_REGION=us-west-2`, `AGENTCORE_MODEL_REGION=us-west-2`, `FAST_CHAT_PROMPT_CACHE_ENABLED` equal to the deployed runtime's value.

## How `--max-live-calls` counts

One shared counter over both paths, every call (success or failure) counts. 2 calls per turn, so `N // 2` turns, evenly spaced over the 50 (`turns_for_limit`); a pair is never split; an odd leftover call is unused. Range 1 to 100; `1` is refused (a turn needs 2). Cap 2 = 1 turn; 10 = 5 turns; 100 = all 50 (50 calls per path). The cap counts invokes, not model calls: an AgentCore runtime recovery turn inside one invoke is not capped by the script (it shows in tokens and `runtime_cycle_count`).

Refusals (exit 2, before any client): no `--live-benchmark`; missing/out-of-range cap; provider not `bedrock`; model id not Haiku; empty region; `AGENTCORE_RUNTIME_ARN` missing or not `arn:aws:bedrock-agentcore:<region>:<account>:runtime/<id>`; `AWS_REGION` different from the ARN region; dataset no longer yields the pinned 50 ids. Stop on first auth/access error (exit 3 if any call succeeded earlier, 1 if no call succeeded). Records first failure `{id, arm, error class (code)}`, `exit_code`, `run` block (git SHA, dirty flag, UTC timestamp). No message, reply or tool-input text is stored.

## IAM (documented, not tested in an account)

- **AgentCore:** `bedrock-agentcore:InvokeAgentRuntime` on `arn:aws:bedrock-agentcore:us-west-2:<ACCOUNT>:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7` and `.../runtime-endpoint/DEFAULT`. Sources (doc): AWS service authorization reference for Amazon Bedrock AgentCore (action `InvokeAgentRuntime` lists resource types `runtime` and `runtime-endpoint`, with the ARN forms above): https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html ; API reference https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html ; repo: `docs/deploy/AWS_STATELESS_EC2.md` IAM section ("runtime ... and its `DEFAULT` endpoint") and `docs/SECURITY_BOUNDARIES.md` (this action is a privileged bypass of FastAPI authorization; give it to a short-lived operator identity only).
- **Converse:** `bedrock:InvokeModel` on the three resources from Phase 3c report section 9.3 (profile ARN; foundation-model ARN in us-west-2 with `bedrock:InferenceProfileArn` condition; region-less foundation-model ARN with `aws:RequestedRegion` = `unspecified`). Converse needs `InvokeModel`: https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html . `--converse-stream` also needs `bedrock:InvokeModelWithResponseStream` on the same three (same page).
- The identity running the script needs its own grants; the runtime role's grants do not cover it.

## Cost estimate (estimate; hand arithmetic unless marked)

Prices: Haiku 4.5 on the `global.` profile $1.00 / $5.00 per million input / output tokens (third-party pages: https://instances.usage.ai/ai/claude-haiku-4-5 , TypingMind; the AWS pricing page did not render, so **not confirmed on AWS**); cache read 0.1x, cache write 1.25x of the input rate (assumed; consistent with a Requesty page showing $0.11 for the $1.10 regional rate). AgentCore Runtime compute: $0.1276 per vCPU-hour and $0.0169 per GB-hour from the example on https://aws.amazon.com/bedrock/agentcore/pricing/ .

Tokens per call: about 7,100 in / 300 out (user-reported, Phase 3b). Cross-check (script run, offline, characters / 4): the 50 turns average about 6,900 input tokens (median 6,500; 22,929 to 34,427 characters).

Per call: 7,100 x $1 / 1e6 + 300 x $5 / 1e6 = $0.0086. Cap 2: about $0.017. Cap 100: about $0.86. Upper bound if the runtime makes a second model call on every invoke: about $1.29. With prefix-cache hits on all but the first call (static prefix about 23,100 characters, about 5,800 estimated tokens, script run, above the 4,096-token Haiku 4.5 minimum per the AWS prompt-caching page): about $0.34. Runtime compute for 50 invokes at an assumed 10 s, 1 vCPU, 2 GB: about $0.02. Not priced: guardrail, CloudWatch, data transfer. Expected full-run total about $0.9 (range $0.3 to $1.3). The script prints its own cost labelled estimate, model tokens only.

## Tests and ruff (script run)

Run once after all edits, from the repo root with the mock env vars:
- `pytest -p no:cacheprovider tests/scripts`: 245 passed (includes the 41 new tests). The new file alone passed on its first run (41 passed).
- `ruff check .`: All checks passed.
- Full suite not rerun (script-only change, no backend import changed); last full-suite result recorded in the item 4 notes (2703 passed, 1 skipped with dist built).

What the 41 tests cover: pinned set and refusal on dataset change; cap math for 2/7/50/99/100; refusal (no cap, cap 0/1/101, no flag, bad provider/model/ARN/region, dry run without cap) with `boto3.client` and `build_clients` failing the test if reached; dry run builds no client; both paths called with the same payload (same system prompt, history, tool, forced tool choice); call counts per path never above the cap; latency, token sums and cost arithmetic; unknown usage is not priced; stream first-text mark; text-only reply is a parse failure with usage kept; malformed AgentCore body is a parse failure; non-auth failure continues; auth error stops after the first call in either arm with class-only records and no secret text; exit codes 0/1/3; cache-point rule; `main` end to end with stub clients and the `run` block.

## Commit SHAs

Filled in by the final message and `git log` (see the last line of this file after the commit).

## Risks

- The two paths differ by design (guardrail, event loop, recovery turn); a gap is a sum of causes.
- Shared prompt cache across paths and turns (5-minute TTL): cached-token and latency differences are partly an order effect; order alternates but it is not eliminated.
- n=50 on one day is one sample; cold starts and throttles can move medians.
- The runtime's model must match `COACHING_MODEL_ID`; check `runtime_model_ids_seen` in the output.
- IAM resource forms come from AWS documentation, not from a test against the account; a `runtime-endpoint` grant is needed for the qualifier used.
- Prices are unconfirmed on the AWS page. The AgentCore runtime compute figure rests on an assumed 10 s per invoke.
- AgentCore arm costs the real runtime; nothing here bounds a runtime-internal second model call.
