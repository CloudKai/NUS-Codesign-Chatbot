# Phase 1 item 4: BLOCKED (the two prompt copies serve different purposes)

No file was changed for this item. The two copies were not merged.

## Locations

| Copy | Used by |
|---|---|
| `agentcore_runtime/prompts/` | The deployed AgentCore runtime (`agentcore_runtime/specialists/*`, `structured_coach.py`, `router.py`, `stage_judge.py`) |
| `backend/prompts/` | The FastAPI app: mock, OpenAI and Bedrock Converse providers, and the token budgeting for AgentCore |

## What each is used for

- `agentcore_runtime/prompts/` holds the pedagogy for the live AgentCore path:
  `shared_coaching.md`, per-stage files (including `ethics_critical.md`), plus
  `fast_chat.md`, `qa.md`, `review*.md`, `router.md`, `stage_judge.md`. Its loader says it
  "must not import the companion `backend` package", because the runtime deploys as its
  own package (`agentcore_runtime/requirements.txt`, own CI job).
- `backend/prompts/` holds `shared/coaching.md`, `stages/*.md` (including `deep_analysis.md`)
  and `composer.py` (786 lines). The composer builds the ordered application brief
  and runtime rules. Its loader imports `backend.student_journey.STAGE_BY_ID` and validates
  stage files against it.

## Evidence

- `docs/PROMPT_ARCHITECTURE.md` lines 3 to 9: AgentCore pedagogy is canonical in
  `agentcore_runtime/prompts/`. `backend/prompts/` "remains the composer used by mock,
  OpenAI, and Bedrock Converse, and is the token-budget stand-in for AgentCore planning".
  The doc says not to treat them as competing curricula.
- `backend/prompts/__init__.py` docstring says the same.
- `diff -rq`: the file sets differ. Only in `agentcore_runtime/prompts`: `fast_chat.md`,
  `qa.md`, `review.md`, `review_deep.md`, `review_incremental.md`, `router.md`,
  `shared_coaching.md`, `stage_judge.md`, `stages/ethics_critical.md`. Only in
  `backend/prompts`: `composer.py`, `shared/coaching.md`, `stages/deep_analysis.md`.
  Same-named stage files differ (`concept_generation`, `design_specification`,
  `reflection`). `problem_identification.md` is identical.
- Stage naming differs: the runtime uses `ethics_critical`, the app uses `deep_analysis`
  (the runtime loader notes it maps to the persisted application stage).
- Import evidence: `backend/agentcore_provider.py`, `bedrock_provider.py`,
  `mock_provider.py`, `agentcore_harness_provider.py`, `providers.py` and
  `backend/coaching/execution.py` import `backend.prompts`. `agentcore_runtime/*` imports only
  `agentcore_runtime.prompts` or `prompts.loader`.
  `backend/agentcore_provider.py` (around line 1609) imports
  `agentcore_runtime.structured_coach.specialist_system_prompt` for budgeting.
- About 12 test files and `scripts/preview_prompt.py` reference `backend.prompts`.

## Why this needs a decision

Making `agentcore_runtime/prompts` the single source would also change what mock, OpenAI
and Bedrock Converse send to their models, drop `composer.py`'s application-rule
assembly, or force `backend` to depend on the deployable runtime package. That is a
product and deployment decision. Options for you:

1. Keep both (today's documented design) and add a test that the shared stage files do not drift.
2. Make `backend/prompts` load pedagogy text from `agentcore_runtime/prompts` and keep only
   the composer logic there. This changes non-AgentCore provider output.
3. Retire the non-AgentCore providers' pedagogy copy entirely.

Items 1 to 3 of Phase 1 are done independently of this.
