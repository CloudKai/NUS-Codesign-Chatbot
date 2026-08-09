# Prompt architecture

Framework-neutral local stage prompts for OpenAI testing of the educational
workflow. Prompt markdown files are the development/application equivalent of
future Bedrock Prompt Management. They contain **BEHAVIOUR** only. Course PDFs
are never prompt content; selected sources (today) or Knowledge Base chunks
(future) supply **KNOWLEDGE** through `retrieved_course_context`.

## Current test architecture

```text
Streamlit
    ↓
FastAPI (Cognito-authenticated notebook)
    ↓
DSQL / SQLite authoritative current_stage
    ↓
shared prompt + stage file  (backend/prompts/)
    ↓
existing selected-source context → PromptContext.retrieved_course_context
    ↓
PromptComposer (server-side, no Streamlit / OpenAI / Bedrock imports)
    ↓
OpenAI (or Ollama / deterministic mock)
    ↓
structured coaching response (recommendation only)
    ↓
application transition logic → confirmation / auto-advance → persist stage
```

Authoritative stage, history, selected sources, and source context are resolved
by `CoachApplicationService` from the notebook store. Clients cannot submit
arbitrary prompt text or stage instructions. Providers never persist stage
changes.

## Future architecture

```text
Streamlit
    ↓
FastAPI
    ↓
DSQL current_stage
    ↓
shared prompt + stage prompt  (Prompt Management equivalent)
    ↓
Bedrock Knowledge Base retrieved chunks
    ↓  (replaces only the producer of retrieved_course_context)
PromptComposer
    ↓
configured generation provider
```

The composer contract stays the same: only the producer of
`retrieved_course_context` changes when KB retrieval lands.

## Package layout

| Path | Role |
|---|---|
| `backend/prompts/shared/coaching.md` | Shared Socratic coach behaviour |
| `backend/prompts/stages/{focus,evidence,assumptions,perspectives,synthesis,conclusion}.md` | Stage purpose, coaching strategy, advance/stay criteria |
| `backend/prompts/loader.py` | UTF-8 load + in-process cache; stage IDs from `STAGE_BY_ID` |
| `backend/prompts/composer.py` | Ordered composition with explicit delimiters |

## Local preview (no network)

```sh
.venv/bin/python scripts/preview_prompt.py --stage evidence
```

Uses demo context only. Does not read the student database, tokens, or API keys.
