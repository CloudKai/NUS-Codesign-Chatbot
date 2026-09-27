# Code-derived project reference

Generated from source at Git HEAD `85f79cc`; uncommitted source, if any, is included.

Companion: [learning handbook](README.md). This is a static inventory, not a live OpenAPI or AWS inspection.

## HTTP routes

Decorators are extracted from application and auth source, including routes that may be conditional. Internal FastAPI routes are not necessarily publicly reachable through Caddy. A function's docstring is a navigation aid and can itself become stale; chapters explain verified behavior.

| Method | Path | Handler / line | Declared response | Dependency defaults | Purpose |
|---|---|---|---|---|---|
| GET | `/api/v1/auth/callback` | [backend/auth_routes.py](../../backend/auth_routes.py) `auth_callback` L214 | RedirectResponse | Inspect handler/auth logic | Complete Cognito login, set auth cookies, and redirect to the UI. |
| GET | `/api/v1/auth/login` | [backend/auth_routes.py](../../backend/auth_routes.py) `auth_login` L177 | RedirectResponse | Inspect handler/auth logic | Redirect the browser to Cognito Managed Login (authorization code + PKCE). |
| GET | `/api/v1/auth/logout` | [backend/auth_routes.py](../../backend/auth_routes.py) `auth_logout` L370 | RedirectResponse | Inspect handler/auth logic | Best-effort revoke refresh token, always clear cookies, return to UI. |
| POST | `/api/v1/auth/logout` | [backend/auth_routes.py](../../backend/auth_routes.py) `auth_logout` L370 | RedirectResponse | Inspect handler/auth logic | Best-effort revoke refresh token, always clear cookies, return to UI. |
| GET | `/api/v1/auth/logout/callback` | [backend/http/app.py](../../backend/http/app.py) `auth_logout_callback` L1020 | RedirectResponse | Inspect handler/auth logic | Deprecated Streamlit-cookie clear path kept for migration only. |
| GET | `/api/v1/auth/me` | [backend/auth_routes.py](../../backend/auth_routes.py) `auth_me` L299 | JSONResponse | Inspect handler/auth logic | Return the authenticated user for valid Cognito cookies (no tokens). |
| GET | `/api/v1/auth/refresh` | [backend/auth_routes.py](../../backend/auth_routes.py) `auth_refresh` L260 | RedirectResponse | Inspect handler/auth logic | Refresh Cognito in the browser context, then return to Streamlit. |
| POST | `/api/v1/coach/turn` | [backend/http/app.py](../../backend/http/app.py) `coach_turn` L1660 | CoachTurn | Depends(current_owner) | Run the typed coaching workflow for an owned notebook. |
| POST | `/api/v1/coach/turn/stream` | [backend/http/app.py](../../backend/http/app.py) `coach_turn_stream` L1865 | StreamingResponse | Depends(current_owner) | Stream one coaching turn as NDJSON progress events, then the final turn. |
| GET | `/api/v1/health` | [backend/http/app.py](../../backend/http/app.py) `health` L473 | dict[str, str] | Inspect handler/auth logic | Return a lightweight process-health response. |
| GET | `/api/v1/preferences` | [backend/http/app.py](../../backend/http/app.py) `get_preferences` L1144 | dict[str, Any] | Depends(current_owner) | Return preferences for the authenticated (or local demo) owner. |
| PATCH | `/api/v1/preferences` | [backend/http/app.py](../../backend/http/app.py) `patch_preferences` L1149 | dict[str, Any] | Depends(current_owner) | Merge preference keys for the authenticated owner. |
| GET | `/api/v1/professor/critical-thinking` | [backend/http/app.py](../../backend/http/app.py) `professor_critical_thinking` L855 | CriticalThinkingResponse | Depends(current_professor) | Return current, non-causal Facione assessment aggregates. |
| GET | `/api/v1/professor/engagement` | [backend/http/app.py](../../backend/http/app.py) `professor_engagement` L865 | EngagementResponse | Depends(current_professor) | Return usage/session analytics, kept distinct from performance. |
| GET | `/api/v1/professor/overview` | [backend/http/app.py](../../backend/http/app.py) `professor_overview` L557 | OverviewResponse | Depends(current_professor) | Return a compact class snapshot for teaching staff only. |
| POST | `/api/v1/professor/research/adjudications` | [backend/http/app.py](../../backend/http/app.py) `professor_research_adjudication` L975 | ResearchAdjudication | Depends(current_professor) | Append an adjudication with server-derived staff identity. |
| GET | `/api/v1/professor/research/export.csv` | [backend/http/app.py](../../backend/http/app.py) `professor_research_export` L991 | Response | Depends(current_professor) | Return an audited, formula-safe CSV export of active observations. |
| GET | `/api/v1/professor/research/notebooks/{notebook_id}` | [backend/http/app.py](../../backend/http/app.py) `professor_research_notebook` L926 | ResearchNotebookDetailResponse | Depends(current_professor) | Return one audited transcript with automated and human coding. |
| GET | `/api/v1/professor/research/queue` | [backend/http/app.py](../../backend/http/app.py) `professor_research_queue` L896 | ResearchQueueResponse | Depends(current_professor) | Return an audited, filtered page of identifiable observations. |
| POST | `/api/v1/professor/research/reviews` | [backend/http/app.py](../../backend/http/app.py) `professor_research_review` L955 | ResearchReview | Depends(current_professor) | Append a review with reviewer identity derived from authentication. |
| GET | `/api/v1/professor/research/summary` | [backend/http/app.py](../../backend/http/app.py) `professor_research_summary` L882 | ResearchSummaryResponse | Depends(current_professor) | Return aggregate research-coding counts without identities. |
| GET | `/api/v1/professor/students` | [backend/http/app.py](../../backend/http/app.py) `professor_students` L571 | StudentsResponse | Depends(current_professor) | List privacy-minimised student rows with safe server-side filters. |
| GET | `/api/v1/professor/students/{student_id}` | [backend/http/app.py](../../backend/http/app.py) `professor_student_detail` L606 | StudentDetailResponse | Depends(current_professor) | Return one student's active learning journey and authorised transcript. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}` | [backend/http/app.py](../../backend/http/app.py) `professor_conversation_transcript` L628 | ConversationTranscriptResponse | Depends(current_professor) | Return one selected student's active notebook transcript only. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/attachments/{attachment_id}` | [backend/http/app.py](../../backend/http/app.py) `professor_conversation_attachment` L820 | Response | Depends(current_professor) | Stream one message-associated attachment after lecturer checks. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/journey` | [backend/http/app.py](../../backend/http/app.py) `professor_notebook_journey` L739 | ProfessorJourneyProjection | Depends(current_professor) | Return persisted journey state without transcript bodies. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/messages` | [backend/http/app.py](../../backend/http/app.py) `professor_notebook_messages` L680 | ProfessorMessagePage | Depends(current_professor) | Return one paginated active-branch transcript page for lecturers. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/review` | [backend/http/app.py](../../backend/http/app.py) `professor_notebook_review` L763 | ProfessorReviewProjection | Depends(current_professor) | Return persisted review projection without regeneration. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources` | [backend/http/app.py](../../backend/http/app.py) `professor_notebook_sources` L715 | ProfessorSourcesResponse | Depends(current_professor) | Return allow-listed library sources for one owned notebook. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/sources/{source_id}` | [backend/http/app.py](../../backend/http/app.py) `professor_notebook_source` L786 | Response | Depends(current_professor) | Stream one library source after lecturer ownership checks. |
| GET | `/api/v1/professor/students/{student_id}/conversations/{notebook_id}/workspace` | [backend/http/app.py](../../backend/http/app.py) `professor_notebook_workspace` L654 | NotebookWorkspaceResponse | Depends(current_professor) | Return one authorised read-only notebook workspace for lecturers. |
| GET | `/api/v1/ready` | [backend/http/app.py](../../backend/http/app.py) `ready` L1059 | dict[str, str] | Inspect handler/auth logic | Return readiness once dependencies and production config are usable. |
| GET | `/api/v1/threads` | [backend/http/app.py](../../backend/http/app.py) `list_threads` L1158 | list[dict[str, Any]] | Depends(current_owner) | List notebooks owned by the authenticated user. |
| POST | `/api/v1/threads` | [backend/http/app.py](../../backend/http/app.py) `create_thread` L1166 | dict[str, Any] | Depends(current_owner) | Create a notebook owned by the authenticated user. |
| DELETE | `/api/v1/threads/{thread_id}` | [backend/http/app.py](../../backend/http/app.py) `delete_thread` L1214 | dict[str, str] | Depends(current_owner) | Delete an owned notebook. |
| GET | `/api/v1/threads/{thread_id}` | [backend/http/app.py](../../backend/http/app.py) `get_thread` L1183 | dict[str, Any] | Depends(current_owner) | Return one owned notebook. |
| PATCH | `/api/v1/threads/{thread_id}` | [backend/http/app.py](../../backend/http/app.py) `update_thread` L1194 | dict[str, Any] | Depends(current_owner) | Rename an owned notebook and/or merge metadata. |
| POST | `/api/v1/threads/{thread_id}/attachments` | [backend/http/app.py](../../backend/http/app.py) `upload_attachments` L1402 | list[dict[str, Any]] | Depends(current_owner) | Store private files used only by one submitted coaching turn. |
| GET | `/api/v1/threads/{thread_id}/deep-analysis.pdf` | [backend/http/app.py](../../backend/http/app.py) `download_deep_analysis_pdf` L1307 | Response | Depends(current_owner) | Return a PDF built from the notebook's completed Sonnet Deep Review. |
| GET | `/api/v1/threads/{thread_id}/deep-review` | [backend/http/app.py](../../backend/http/app.py) `get_deep_review` L1819 | DeepReviewJob | Depends(current_owner) | Return the owner-scoped Deep Review job, including a completed snapshot. |
| POST | `/api/v1/threads/{thread_id}/deep-review` | [backend/http/app.py](../../backend/http/app.py) `start_deep_review` L1751 | DeepReviewJob | Depends(current_owner) | Enqueue one server-owned explicit Deep Review for the owned notebook. |
| GET | `/api/v1/threads/{thread_id}/graph` | [backend/http/app.py](../../backend/http/app.py) `graph_inspection` L2075 | dict[str, Any] | Depends(current_owner) | Return the latest inspectable coach-graph summary for a notebook. |
| GET | `/api/v1/threads/{thread_id}/journey-stage-reviews` | [backend/http/app.py](../../backend/http/app.py) `get_journey_stage_reviews` L1839 | dict[str, Any] | Depends(current_owner) | Return Journey stage-completion review checkpoints for one notebook. |
| POST | `/api/v1/threads/{thread_id}/journey-stage-reviews/read` | [backend/http/app.py](../../backend/http/app.py) `mark_journey_stage_reviews_read` L1852 | dict[str, Any] | Depends(current_owner) | Clear the Journey unread notification after the student views Journey. |
| GET | `/api/v1/threads/{thread_id}/learning-state` | [backend/http/app.py](../../backend/http/app.py) `learning_state` L1530 | dict | Depends(current_owner) | Return persisted notebook learning metadata for the owned thread. |
| POST | `/api/v1/threads/{thread_id}/learning-state/select-stage` | [backend/http/app.py](../../backend/http/app.py) `select_learning_stage` L1553 | dict | Depends(current_owner) | Move the owned notebook to a student-chosen Thinking Path stage. |
| GET | `/api/v1/threads/{thread_id}/messages` | [backend/http/app.py](../../backend/http/app.py) `list_messages` L1226 | list[dict[str, Any]] | Depends(current_owner) | Return canonical chat history for an owned notebook. |
| POST | `/api/v1/threads/{thread_id}/messages` | [backend/http/app.py](../../backend/http/app.py) `create_message` L1324 | dict[str, str] | Depends(current_owner) | Persist one message on an owned notebook. |
| GET | `/api/v1/threads/{thread_id}/messages/exists` | [backend/http/app.py](../../backend/http/app.py) `has_messages` L1240 | bool | Depends(current_owner) | Return whether an owned notebook has a visible active message. |
| GET | `/api/v1/threads/{thread_id}/messages/page` | [backend/http/app.py](../../backend/http/app.py) `list_message_page` L1254 | MessagePage | Depends(current_owner) | Return a bounded newest-first page of an owned notebook transcript. |
| GET | `/api/v1/threads/{thread_id}/messages/title-context` | [backend/http/app.py](../../backend/http/app.py) `title_context` L1278 | list[str] | Depends(current_owner) | Return only the bounded oldest user prompts used for title migration. |
| POST | `/api/v1/threads/{thread_id}/messages/{message_id}/revise` | [backend/http/app.py](../../backend/http/app.py) `revise_user_message` L1576 | CoachTurn | Depends(current_owner) | Revise an owned user message via append-only supersede, then coach again. |
| GET | `/api/v1/threads/{thread_id}/phase-transitions/pending` | [backend/http/app.py](../../backend/http/app.py) `pending_transition` L1650 | PendingPhaseTransition \| None | Depends(current_owner) | Return the student's unresolved stage transition recommendation. |
| POST | `/api/v1/threads/{thread_id}/phase-transitions/{transition_id}/resolve` | [backend/http/app.py](../../backend/http/app.py) `resolve_transition` L2091 | PendingPhaseTransition | Depends(current_owner) | Persist the student's accept/reject decision for a transition. |
| GET | `/api/v1/threads/{thread_id}/sources` | [backend/http/app.py](../../backend/http/app.py) `list_sources` L1342 | list[dict[str, Any]] | Depends(current_owner) | List owned notebook sources without filesystem paths. |
| POST | `/api/v1/threads/{thread_id}/sources` | [backend/http/app.py](../../backend/http/app.py) `upload_sources` L1368 | list[dict[str, Any]] | Depends(current_owner) | Upload files into an owned notebook's source library. |
| POST | `/api/v1/threads/{thread_id}/sources/backfill-legacy` | [backend/http/app.py](../../backend/http/app.py) `backfill_legacy` L1499 | dict[str, int] | Depends(current_owner) | Import legacy message attachments into the owned source library. |
| POST | `/api/v1/threads/{thread_id}/sources/select-all` | [backend/http/app.py](../../backend/http/app.py) `select_all_sources` L1452 | list[dict[str, Any]] | Depends(current_owner) | Select or deselect every source in an owned notebook. |
| POST | `/api/v1/threads/{thread_id}/sources/sync-course-materials` | [backend/http/app.py](../../backend/http/app.py) `sync_course_materials` L1511 | dict[str, Any] | Depends(current_owner) | Synchronize lecture-note folder materials into the owned notebook. |
| DELETE | `/api/v1/threads/{thread_id}/sources/{source_id}` | [backend/http/app.py](../../backend/http/app.py) `delete_source` L1466 | dict[str, str] | Depends(current_owner) | Delete a non-locked owned source. |
| GET | `/api/v1/threads/{thread_id}/sources/{source_id}` | [backend/http/app.py](../../backend/http/app.py) `get_source` L1356 | dict[str, Any] | Depends(current_owner) | Return one owned source without a filesystem path. |
| PATCH | `/api/v1/threads/{thread_id}/sources/{source_id}` | [backend/http/app.py](../../backend/http/app.py) `update_source` L1430 | dict[str, Any] | Depends(current_owner) | Rename and/or change selection for one owned source. |
| GET | `/api/v1/threads/{thread_id}/sources/{source_id}/content` | [backend/http/app.py](../../backend/http/app.py) `source_content` L1479 | Response | Depends(current_owner) | Return owned source file bytes for preview or download. |
| GET | `/api/v1/threads/{thread_id}/transcript.txt` | [backend/http/app.py](../../backend/http/app.py) `download_transcript` L1290 | Response | Depends(current_owner) | Return a student-readable .txt projection of persisted messages. |

Static route registrations: **64**.

## Main API input models

Fields below come from class annotations. Defaults and Field expressions are shown as source, not evaluated settings. Inherited fields and custom validators require reading the linked source. Accepted input is also subject to server ownership and authoritative-state validation.

### CoachRequest

Source: [backend/domain.py](../../backend/domain.py), line 384.

| Field | Type | Default / constraint expression |
|---|---|---|
| `thread_id` | str | Required |
| `student_message` | str | Field(min_length=1, max_length=12000) |
| `current_stage` | str | Required |
| `response_detail` | str | Field(pattern='^(short\|long)$') |
| `student_id` | str \| None | Field(default=None, max_length=128) |
| `source_ids` | list[str] | Field(default_factory=list) |
| `attachment_source_ids` | list[str] | Field(default_factory=list, max_length=5) |
| `attachment_titles` | list[str] | Field(default_factory=list, max_length=5) |
| `source_context` | str | '' |
| `student_project_context` | str | '' |
| `conversation_summary` | str | '' |
| `conversation_memory` | dict[str, Any] \| None | None |
| `retrieved_chunks` | list[RetrievalChunkReference] | Field(default_factory=list) |
| `image_inputs` | list[CoachImageInput] | Field(default_factory=list, max_length=5) |
| `allow_model_knowledge` | bool | False |
| `response_language` | str | Field(default='English', min_length=1, max_length=50) |
| `history` | list[dict[str, Any]] | Field(default_factory=list) |
| `model_id` | str \| None | None |
| `reasoning_effort` | str \| None | None |
| `conversation_revision` | int \| None | None |
| `revise_user_message_id` | str \| None | Field(default=None, max_length=64) |
| `idempotency_key` | str \| None | Field(default=None, min_length=1, max_length=128, pattern='^[A-Za-z0-9][A-Za-z0-9._:-]*$') |
| `specialist` | str \| None | Field(default=None, max_length=32) |
| `coaching_turns_since_deep_review` | int | Field(default=0, ge=0) |
| `deep_review_interval_turns` | int | Field(default=3, ge=1, le=50) |
| `review_id` | str \| None | Field(default=None, max_length=64) |
| `retrieval_required` | bool | False |
| `expected_response_mode` | str \| None | Field(default=None, max_length=16) |
| `mode_policy_intent` | str | Field(default='', max_length=64) |
| `deep_review_context_mode` | str | Field(default='', max_length=32) |
| `deep_review_compact_context` | str | '' |
| `deep_review_ref_map` | dict[str, str] | Field(default_factory=dict) |
| `deep_review_context_metrics` | dict[str, Any] | Field(default_factory=dict) |

### DeepReviewRequest

Source: [backend/domain.py](../../backend/domain.py), line 549.

| Field | Type | Default / constraint expression |
|---|---|---|
| `idempotency_key` | str \| None | Field(default=None, min_length=1, max_length=128, pattern='^[A-Za-z0-9][A-Za-z0-9._:-]*$') |

### PreferencePatch

Source: [backend/domain.py](../../backend/domain.py), line 692.

| Field | Type | Default / constraint expression |
|---|---|---|
| `appearance` | str \| None | None |
| `active_thread_id` | str \| None | None |
| `sources_expander_state` | dict[str, Any] \| None | None |

### NotebookMetadataPatch

Source: [backend/domain.py](../../backend/domain.py), line 702.

| Field | Type | Default / constraint expression |
|---|---|---|
| `response_detail` | Literal['short', 'long'] \| None | None |
| `response_language` | str \| None | Field(default=None, min_length=1, max_length=50) |
| `selected_model` | str \| None | Field(default=None, min_length=1, max_length=120) |
| `reasoning_effort` | str \| None | Field(default=None, min_length=1, max_length=30) |
| `support_mode` | str \| None | Field(default=None, min_length=1, max_length=120) |
| `assignment` | dict[str, str] \| None | None |
| `allow_model_knowledge` | bool \| None | None |
| `display_name` | str \| None | Field(default=None, min_length=1, max_length=80) |
| `tags` | list[str] \| None | Field(default=None, max_length=50) |

### NotebookCreateRequest

Source: [backend/domain.py](../../backend/domain.py), line 723.

| Field | Type | Default / constraint expression |
|---|---|---|
| `name` | str | Field(default='Untitled notebook', min_length=1, max_length=120) |
| `model_id` | str | Field(min_length=1, max_length=120) |
| `support_mode` | str | Field(min_length=1, max_length=120) |
| `assignment` | dict[str, str] | Field(default_factory=dict) |
| `metadata` | NotebookMetadataPatch | Field(default_factory=NotebookMetadataPatch) |

### NotebookUpdateRequest

Source: [backend/domain.py](../../backend/domain.py), line 733.

| Field | Type | Default / constraint expression |
|---|---|---|
| `name` | str \| None | Field(default=None, min_length=1, max_length=120) |
| `metadata` | NotebookMetadataPatch \| None | None |

### MessageCreateRequest

Source: [backend/domain.py](../../backend/domain.py), line 749.

| Field | Type | Default / constraint expression |
|---|---|---|
| `role` | Literal['assistant'] | 'assistant' |
| `content` | str | Field(min_length=1, max_length=100000) |
| `metadata` | WelcomeMessageMetadata | Field(default_factory=WelcomeMessageMetadata) |

### SourceUpdateRequest

Source: [backend/domain.py](../../backend/domain.py), line 781.

| Field | Type | Default / constraint expression |
|---|---|---|
| `title` | str \| None | Field(default=None, min_length=1, max_length=180) |
| `selected` | bool \| None | None |

### SourceSelectAllRequest

Source: [backend/domain.py](../../backend/domain.py), line 788.

| Field | Type | Default / constraint expression |
|---|---|---|
| `selected` | bool | Required |

### TransitionResolution

Source: [backend/http/app.py](../../backend/http/app.py), line 130.

| Field | Type | Default / constraint expression |
|---|---|---|
| `accepted` | bool | Required |

### StageSelectionRequest

Source: [backend/http/app.py](../../backend/http/app.py), line 136.

| Field | Type | Default / constraint expression |
|---|---|---|
| `stage_id` | str | Field(min_length=1, max_length=64) |

### MessageReviseRequest

Source: [backend/http/app.py](../../backend/http/app.py), line 142.

| Field | Type | Default / constraint expression |
|---|---|---|
| `content` | str | Field(min_length=1, max_length=12000) |
| `idempotency_key` | str | Field(min_length=1, max_length=128, pattern='^[A-Za-z0-9][A-Za-z0-9._:-]*$') |
| `model_id` | str \| None | None |
| `reasoning_effort` | str \| None | None |
| `response_detail` | str \| None | Field(default=None, pattern='^(short\|long)$') |
| `response_language` | str \| None | Field(default=None, min_length=1, max_length=50) |

## Exact schema declarations

SQL below is extracted verbatim from schema constants. It is reference material, not an instruction to apply DDL to an existing database. Use the documented initialization/migration tools and review their plans.

### SQLITE_SCHEMA

Source: [backend/persistence/store/sqlite_schema.py](../../backend/persistence/store/sqlite_schema.py). Tables: **10**.

`users`, `oauth_login_states`, `notebooks`, `messages`, `sources`, `research_observations`, `research_reviews`, `research_adjudications`, `research_access_events`, `system_metadata`

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL UNIQUE,
    cognito_sub TEXT,
    email TEXT,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    preferences_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS oauth_login_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    current_stage TEXT NOT NULL DEFAULT 'problem_identification',
    progress_text TEXT NOT NULL DEFAULT '{}',
    settings_text TEXT NOT NULL DEFAULT '{}',
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notebooks_user_updated
ON notebooks(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    is_error INTEGER NOT NULL DEFAULT 0,
    assessment_text TEXT,
    cited_source_ids_text TEXT,
    proposed_stage TEXT,
    decision_status TEXT,
    decision_at TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    previous_message_id TEXT,
    superseded_at_revision INTEGER,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_notebook_created
ON messages(notebook_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_messages_notebook_decision
ON messages(notebook_id, decision_status, created_at);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0,
    object_key TEXT,
    extracted_text_key TEXT,
    source_url TEXT,
    selected INTEGER NOT NULL DEFAULT 1,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sources_notebook_created
ON sources(notebook_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_observations (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL UNIQUE,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    coding_status TEXT NOT NULL,
    coding_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    coaching_profile TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    dominant_clear TEXT,
    facione_behaviors_text TEXT NOT NULL DEFAULT '[]',
    ethics_concepts_text TEXT NOT NULL DEFAULT '[]',
    evidence_text TEXT NOT NULL DEFAULT '[]',
    holistic_candidate_text TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_observations_notebook_created
ON research_observations(notebook_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_research_observations_status_created
ON research_observations(coding_status, created_at, id);

CREATE TABLE IF NOT EXISTS research_reviews (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    reviewer_user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    coding_status TEXT,
    dominant_clear TEXT,
    facione_behaviors_text TEXT,
    ethics_concepts_text TEXT,
    evidence_text TEXT,
    holistic_candidate_text TEXT,
    notes TEXT,
    supersedes_review_id TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (observation_id) REFERENCES research_observations(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_user_id) REFERENCES users(id),
    FOREIGN KEY (supersedes_review_id) REFERENCES research_reviews(id)
);

CREATE INDEX IF NOT EXISTS idx_research_reviews_observation_created
ON research_reviews(observation_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_adjudications (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    adjudicator_user_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    coding_status TEXT,
    dominant_clear TEXT,
    facione_behaviors_text TEXT,
    ethics_concepts_text TEXT,
    evidence_text TEXT,
    holistic_candidate_text TEXT,
    notes TEXT,
    supersedes_adjudication_id TEXT,
    referenced_review_ids_text TEXT NOT NULL DEFAULT '[]',
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (observation_id) REFERENCES research_observations(id) ON DELETE CASCADE,
    FOREIGN KEY (adjudicator_user_id) REFERENCES users(id),
    FOREIGN KEY (supersedes_adjudication_id) REFERENCES research_adjudications(id)
);

CREATE INDEX IF NOT EXISTS idx_research_adjudications_observation_created
ON research_adjudications(observation_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_access_events (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_user_id TEXT,
    target_count INTEGER,
    notebook_id TEXT,
    observation_id TEXT,
    filters_text TEXT NOT NULL DEFAULT '{}',
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_access_actor_created
ON research_access_events(actor_user_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_research_access_request
ON research_access_events(request_id, created_at, id);

CREATE TABLE IF NOT EXISTS system_metadata (
    key TEXT PRIMARY KEY,
    value_text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### DSQL_SCHEMA

Source: [backend/persistence/dsql_schema.py](../../backend/persistence/dsql_schema.py). Tables: **10**.

`users`, `oauth_login_states`, `notebooks`, `messages`, `sources`, `research_observations`, `research_reviews`, `research_adjudications`, `research_access_events`, `system_metadata`

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL,
    cognito_sub TEXT,
    email TEXT,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    preferences_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_login_at TEXT
);

CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_users_identifier
ON users(identifier);

CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_users_cognito_sub
ON users(cognito_sub);

CREATE TABLE IF NOT EXISTS oauth_login_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    current_stage TEXT NOT NULL DEFAULT 'problem_identification',
    progress_text TEXT NOT NULL DEFAULT '{}',
    settings_text TEXT NOT NULL DEFAULT '{}',
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ASYNC IF NOT EXISTS idx_notebooks_user_updated
ON notebooks(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    is_error INTEGER NOT NULL DEFAULT 0,
    assessment_text TEXT,
    cited_source_ids_text TEXT,
    proposed_stage TEXT,
    decision_status TEXT,
    decision_at TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    previous_message_id TEXT NULL,
    superseded_at_revision INTEGER NULL
);

CREATE INDEX ASYNC IF NOT EXISTS idx_messages_notebook_created
ON messages(notebook_id, created_at, id);

CREATE INDEX ASYNC IF NOT EXISTS idx_messages_notebook_decision
ON messages(notebook_id, decision_status, created_at);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0,
    object_key TEXT,
    extracted_text_key TEXT,
    source_url TEXT,
    selected INTEGER NOT NULL DEFAULT 1,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ASYNC IF NOT EXISTS idx_sources_notebook_created
ON sources(notebook_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_observations (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    coding_status TEXT NOT NULL,
    coding_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    coaching_profile TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    dominant_clear TEXT,
    facione_behaviors_text TEXT NOT NULL DEFAULT '[]',
    ethics_concepts_text TEXT NOT NULL DEFAULT '[]',
    evidence_text TEXT NOT NULL DEFAULT '[]',
    holistic_candidate_text TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX ASYNC IF NOT EXISTS idx_research_observations_assistant
ON research_observations(assistant_message_id);

CREATE INDEX ASYNC IF NOT EXISTS idx_research_observations_notebook_created
ON research_observations(notebook_id, created_at, id);

CREATE INDEX ASYNC IF NOT EXISTS idx_research_observations_status_created
ON research_observations(coding_status, created_at, id);

CREATE TABLE IF NOT EXISTS research_reviews (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    reviewer_user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    coding_status TEXT,
    dominant_clear TEXT,
    facione_behaviors_text TEXT,
    ethics_concepts_text TEXT,
    evidence_text TEXT,
    holistic_candidate_text TEXT,
    notes TEXT,
    supersedes_review_id TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX ASYNC IF NOT EXISTS idx_research_reviews_observation_created
ON research_reviews(observation_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_adjudications (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    adjudicator_user_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    coding_status TEXT,
    dominant_clear TEXT,
    facione_behaviors_text TEXT,
    ethics_concepts_text TEXT,
    evidence_text TEXT,
    holistic_candidate_text TEXT,
    notes TEXT,
    supersedes_adjudication_id TEXT,
    referenced_review_ids_text TEXT NOT NULL DEFAULT '[]',
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX ASYNC IF NOT EXISTS idx_research_adjudications_observation_created
ON research_adjudications(observation_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_access_events (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_user_id TEXT,
    target_count INTEGER,
    notebook_id TEXT,
    observation_id TEXT,
    filters_text TEXT NOT NULL DEFAULT '{}',
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX ASYNC IF NOT EXISTS idx_research_access_actor_created
ON research_access_events(actor_user_id, created_at, id);

CREATE INDEX ASYNC IF NOT EXISTS idx_research_access_request
ON research_access_events(request_id, created_at, id);

CREATE TABLE IF NOT EXISTS system_metadata (
    key TEXT PRIMARY KEY,
    value_text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Python module map

The first paragraph of each module docstring is extracted below. Compatibility aliases and historical modules remain visible; presence in this list does not imply execution on the active production chat path.

| File | Responsibility from module docstring | Top-level classes |
|---|---|---|
| [backend/__init__.py](../../backend/__init__.py) | Co-design Chatbot backend package. | — |
| [backend/agentcore_harness_provider.py](../../backend/agentcore_harness_provider.py) | Isolated AgentCore InvokeHarness adapter for GPT-5.6 Luna evaluation. | LunaHistoryCompressor, AgentCoreHarnessCoachProvider |
| [backend/agentcore_provider.py](../../backend/agentcore_provider.py) | Amazon Bedrock AgentCore Runtime adapter for one structured specialist turn. | _TransientStructuredOutputError, AgentCoreCoachProvider |
| [backend/analysis_tool.py](../../backend/analysis_tool.py) | No module docstring; inspect source. | — |
| [backend/api.py](../../backend/api.py) | Backward-compatible FastAPI façade. | — |
| [backend/api_client.py](../../backend/api_client.py) | Typed synchronous client used by Streamlit once the local API is running. | _HttpSession, LocalApiClient |
| [backend/application.py](../../backend/application.py) | Backward-compatible coaching application façade. | — |
| [backend/auth_oidc.py](../../backend/auth_oidc.py) | Server-side Cognito authorization-code + PKCE helpers for FastAPI login. | CognitoIdentity, CognitoAuthSession, CognitoOIDCError, CognitoOIDCClient |
| [backend/auth_profiles.py](../../backend/auth_profiles.py) | Cognito identity claims to application user profile rules. | AuthProfile |
| [backend/auth_routes.py](../../backend/auth_routes.py) | FastAPI authentication handlers: Cognito login + HttpOnly token cookies. | — |
| [backend/bedrock_provider.py](../../backend/bedrock_provider.py) | Amazon Bedrock Converse adapter for one structured coaching turn. | BedrockCoachProvider |
| [backend/bedrock_retrieve.py](../../backend/bedrock_retrieve.py) | Bedrock Knowledge Base ``Retrieve`` adapter for selected course sources. | RetrieveCapacityError, BedrockKnowledgeBaseRetriever |
| [backend/chat_service.py](../../backend/chat_service.py) | Legacy direct chat engine retained for compatibility tests. | ChatOptions, ChatStream, StudentChatEngine |
| [backend/coaching/__init__.py](../../backend/coaching/__init__.py) | Application-layer coaching orchestration and deterministic projections. | — |
| [backend/coaching/deep_review_context.py](../../backend/coaching/deep_review_context.py) | Deep Review full-history vs checkpoint-delta context planning. | DeepReviewContextPlan |
| [backend/coaching/deep_review_jobs.py](../../backend/coaching/deep_review_jobs.py) | Process-local background executor for Deep Review jobs. | — |
| [backend/coaching/execution.py](../../backend/coaching/execution.py) | Durable coaching execution across workflow, retrieval, and persistence. | CoachApplicationService |
| [backend/coaching/mode_policy.py](../../backend/coaching/mode_policy.py) | Server-side Q&A vs Coaching mode policy for one Fast Chat turn. | ModePolicy, ModeEnforcement |
| [backend/coaching/progress.py](../../backend/coaching/progress.py) | Request-scoped coaching progress events for FastAPI NDJSON streaming. | coach_progress |
| [backend/coaching/progress_fields.py](../../backend/coaching/progress_fields.py) | Canonical filtering of notebook progress fields that carry meaning. | — |
| [backend/coaching/stage_review_jobs.py](../../backend/coaching/stage_review_jobs.py) | Process-local executor for durable Journey stage-review jobs. | — |
| [backend/coaching/turn_snapshot.py](../../backend/coaching/turn_snapshot.py) | Request-scoped authoritative notebook state for one coaching submit. | TurnSnapshot |
| [backend/coaching/workflow_navigation.py](../../backend/coaching/workflow_navigation.py) | Deterministic Thinking Path workflow-intent recognition. | WorkflowIntent |
| [backend/cognito_config.py](../../backend/cognito_config.py) | Cognito OIDC client configuration for FastAPI-owned login. | CognitoAuthConfig |
| [backend/cognito_cookies.py](../../backend/cognito_cookies.py) | HttpOnly Cognito refresh / ID-token cookie helpers for FastAPI auth routes. | — |
| [backend/context_planner.py](../../backend/context_planner.py) | Provider-neutral token-aware model-context planner. | ContextBudgetError, ContextBudget, ConversationMemory, ModelContextPlan, HistoryCompressor, ExtractiveHistoryCompressor, HistoryContextPlanner |
| [backend/domain.py](../../backend/domain.py) | Typed domain objects for the critical-thinking coach. | StageDecision, ResearchCodingStatus, ClearCode, FacioneBehavior, EthicsConcept, ResearchEvidence, HolisticCandidate, ProvisionalResearchCoding, TransitionStatus, CitationReference, RetrievalChunkReference, FacioneDimensionScores, EducationalAssessment, PendingPhaseTransition, CoachImageInput, CoachRequest, DeepReviewRequest, DeepReviewJobStatus, DeepReviewJob, CoachTurn, ProviderCoachOutput, ProviderAssessmentResult, PreferencePatch, NotebookMetadataPatch, NotebookCreateRequest, NotebookUpdateRequest, WelcomeMessageMetadata, MessageCreateRequest, MessagePage, SourceUpdateRequest, SourceSelectAllRequest |
| [backend/file_processing.py](../../backend/file_processing.py) | No module docstring; inspect source. | StoredUpload |
| [backend/http/__init__.py](../../backend/http/__init__.py) | HTTP composition root for the FastAPI application. | — |
| [backend/http/app.py](../../backend/http/app.py) | FastAPI application composition for the Co-design Chatbot. | TransitionResolution, StageSelectionRequest, MessageReviseRequest |
| [backend/learning/__init__.py](../../backend/learning/__init__.py) | Provider-independent Thinking Path domain and Review projection. | — |
| [backend/learning/deep_analysis_pdf.py](../../backend/learning/deep_analysis_pdf.py) | Build a student-facing Deep Analysis PDF from a Sonnet Deep Review snapshot. | DeepAnalysisPdfExport, _PdfWriter |
| [backend/learning/hmw.py](../../backend/learning/hmw.py) | Server-owned How Might We scaffold eligibility for Problem Identification. | — |
| [backend/learning/journey.py](../../backend/learning/journey.py) | Provider-independent Thinking Path domain and Review projection. | — |
| [backend/learning/stage_briefing.py](../../backend/learning/stage_briefing.py) | Deterministic coach briefings after a Thinking Path stage move or revisit. | — |
| [backend/learning/stages.py](../../backend/learning/stages.py) | Immutable definitions for the five-phase Thinking Path. | ThinkingStage |
| [backend/learning_service.py](../../backend/learning_service.py) | Application service for confirmation-gated and student-selected stage progression. | LearningProgressService |
| [backend/live_eval_config.py](../../backend/live_eval_config.py) | Server-side live-evaluation model configuration (GPT-5.6 Luna only). | LiveEvalConfigurationError, LiveEvalModelConfig |
| [backend/local_tools.py](../../backend/local_tools.py) | No module docstring; inspect source. | — |
| [backend/mock_provider.py](../../backend/mock_provider.py) | Deterministic local provider for API-free tests and demonstrations. | DeterministicCoachProvider |
| [backend/models.py](../../backend/models.py) | No module docstring; inspect source. | ModelDefinition |
| [backend/operational_metrics.py](../../backend/operational_metrics.py) | Privacy-safe structured operational metrics for the API boundary. | — |
| [backend/owner_context.py](../../backend/owner_context.py) | Resolve the authenticated notebook owner for FastAPI application requests. | OwnerServices, OwnerResolver |
| [backend/persistence/__init__.py](../../backend/persistence/__init__.py) | Storage ports and provider selection for local and AWS production runtimes. | — |
| [backend/persistence/dsql_connection.py](../../backend/persistence/dsql_connection.py) | Aurora DSQL connection helpers (IAM auth, OCC retries, SQL adaptation). | DsqlCursorResult, DsqlConnectionProxy, _Row |
| [backend/persistence/dsql_schema.py](../../backend/persistence/dsql_schema.py) | Aurora DSQL schema for the production data model. | — |
| [backend/persistence/dsql_student_store.py](../../backend/persistence/dsql_student_store.py) | Aurora DSQL-backed StudentStore for production structured state. | DsqlStudentStore |
| [backend/persistence/factory.py](../../backend/persistence/factory.py) | Configuration-driven factories for database and file-storage providers. | — |
| [backend/persistence/local_files.py](../../backend/persistence/local_files.py) | Local filesystem FileStorage adapter for development and tests. | LocalFileStorage |
| [backend/persistence/memory_files.py](../../backend/persistence/memory_files.py) | In-memory FileStorage used by deterministic automated tests. | MemoryFileStorage |
| [backend/persistence/object_keys.py](../../backend/persistence/object_keys.py) | Safe object-key helpers for local and S3 file storage. | — |
| [backend/persistence/ports.py](../../backend/persistence/ports.py) | Narrow storage ports used by application services. | StoredObject, ListedObject, FileStorage |
| [backend/persistence/s3_files.py](../../backend/persistence/s3_files.py) | S3 FileStorage adapter for production user uploads. | S3DeleteObjectsError, S3FileStorage |
| [backend/persistence/store/__init__.py](../../backend/persistence/store/__init__.py) | Provider-neutral persistence contracts and SQLite implementation helpers. | — |
| [backend/persistence/store/contracts.py](../../backend/persistence/store/contracts.py) | Stable contracts shared by SQLite, DSQL, services, and compatibility façades. | StoreContext, CoachIdempotencyConflictError, CoachRequestLeaseLostError, CoachRequestInProgressError, ConversationRevisionConflictError, CoachingStyleConflictError, AtomicAutoAdvance, ConversationRevisionResult, CoachRequestReservation |
| [backend/persistence/store/migrations.py](../../backend/persistence/store/migrations.py) | SQLite compatibility migrations applied during local store startup. | — |
| [backend/persistence/store/operations/__init__.py](../../backend/persistence/store/operations/__init__.py) | Cohesive operation objects composed behind the ``StudentStore`` façade. | StoreOperations |
| [backend/persistence/store/operations/sources.py](../../backend/persistence/store/operations/sources.py) | Owned source metadata operations shared by SQLite and DSQL stores. | SourceOperations |
| [backend/persistence/store/sqlite_schema.py](../../backend/persistence/store/sqlite_schema.py) | SQLite schema applied by the local ``StudentStore`` initializer. | — |
| [backend/professor_analytics/__init__.py](../../backend/professor_analytics/__init__.py) | Read-only, professor-authorized learning analytics for Co-design. | — |
| [backend/professor_analytics/models.py](../../backend/professor_analytics/models.py) | Typed public contracts for the professor analytics API. | AttentionSignal, StageDistributionItem, ScoreValue, StudentListItem, OverviewResponse, StudentsResponse, StudentDetailResponse, ConversationTranscriptResponse, ProfessorNotebookSummary, ProfessorMessageAttachment, ProfessorMessageCitation, ProfessorTranscriptMessage, ProfessorMessagePage, ProfessorSourcesResponse, ProfessorJourneyStage, ProfessorJourneyProjection, ProfessorReviewStage, ProfessorReviewProjection, ProfessorWorkspaceTranscript, ProfessorSourceSummary, ProfessorLearningState, NotebookWorkspaceResponse, CriticalThinkingResponse, EngagementResponse |
| [backend/professor_analytics/repository.py](../../backend/professor_analytics/repository.py) | Batch, read-only SQL access for professor analytics. | ProfessorAnalyticsUnavailable, ProfessorAnalyticsRepository |
| [backend/professor_analytics/research.py](../../backend/professor_analytics/research.py) | Application boundary for attributable professor research review. | ResearchRepository, CoOccurrencePair, CoAbsenceItem, ResearchSummaryResponse, ResearchQueueItem, ResearchQueueResponse, ResearchNotebookDetailResponse, ResearchReviewRequest, ResearchAdjudicationRequest, ProfessorResearchService |
| [backend/professor_analytics/service.py](../../backend/professor_analytics/service.py) | Pure, read-only learning analytics derived from persisted application data. | AttentionRules, ProfessorAnalyticsService |
| [backend/prompts/__init__.py](../../backend/prompts/__init__.py) | Application composer for mock/OpenAI/Bedrock Converse. | — |
| [backend/prompts/composer.py](../../backend/prompts/composer.py) | Compose shared + stage + turn context into one provider-ready prompt. | PromptContext, PreparedCoachPrompt, PromptComposer |
| [backend/prompts/loader.py](../../backend/prompts/loader.py) | UTF-8 prompt-file loader with an in-process immutable cache. | PromptLoadError |
| [backend/providers.py](../../backend/providers.py) | Coach provider selection and optional OpenAI adapter. | ProviderUnavailableError, OpenAICoachProvider |
| [backend/rate_limit.py](../../backend/rate_limit.py) | In-process coach and auth-login rate limiting for a single EC2 instance. | CoachExecutionLease, RateLimitExceeded, CoachRateLimiter, DeepReviewConcurrencyLimiter, LoginStartLimiter |
| [backend/repositories.py](../../backend/repositories.py) | Repository ports and SQLite adapters for the local demonstration runtime. | NotebookRepository, SourceRepository, PreferenceRepository, PhaseTransitionRepository, SQLiteNotebookRepository, SQLiteSourceRepository, SQLitePreferenceRepository, SQLitePhaseTransitionRepository |
| [backend/research/__init__.py](../../backend/research/__init__.py) | Internal research-coding persistence contracts and repository adapter. | — |
| [backend/research/models.py](../../backend/research/models.py) | Typed internal records for research coding, review, and access auditing. | ResearchEvidenceSpan, ResearchOffsetSpan, ResearchHolisticCandidate, ResearchCodingFields, ResearchObservationCreate, ResearchObservation, ResearchReviewCreate, ResearchReview, ResearchAdjudicationCreate, ResearchAdjudication, ResearchAccessEventCreate, ResearchAccessEvent |
| [backend/research/repository.py](../../backend/research/repository.py) | Narrow repository port and StudentStore adapter for research persistence. | ResearchRepository, StudentStoreResearchRepository |
| [backend/retrieval.py](../../backend/retrieval.py) | Provider-neutral retrieval contracts and local selected-source retrieval. | RetrievalSource, RetrievalQuery, RetrievedChunk, RetrievalResult, ContextRetriever, CompositeContextRetriever, _Candidate, LocalChunkRetriever |
| [backend/retrieval_gate.py](../../backend/retrieval_gate.py) | Deterministic retrieval gate for latency-sensitive normal chat. | RetrievalClassification |
| [backend/session_tokens.py](../../backend/session_tokens.py) | OAuth state and PKCE verifier helpers for Cognito authorization-code login. | — |
| [backend/settings.py](../../backend/settings.py) | Application settings loaded from the project ``.env`` file. | Settings |
| [backend/source_library.py](../../backend/source_library.py) | Compatibility alias for the source-library implementation. | — |
| [backend/sources/__init__.py](../../backend/sources/__init__.py) | Focused source ingestion, course-material, context, and projection helpers. | — |
| [backend/sources/chunk_artifacts.py](../../backend/sources/chunk_artifacts.py) | Disposable derived chunk artifacts for selected-source retrieval. | SourceChunkRecord, SourceChunkArtifact |
| [backend/sources/chunk_cache.py](../../backend/sources/chunk_cache.py) | Byte-bounded in-process LRU for parsed student-source chunk artifacts. | ChunkCacheKey, ChunkCacheStats, _CachedEntry, StudentSourceChunkCache |
| [backend/sources/chunk_load.py](../../backend/sources/chunk_load.py) | Hydrate selected student sources for retrieval without listing objects. | _HydrateMetrics |
| [backend/sources/context.py](../../backend/sources/context.py) | Provider-neutral projection of selected sources into bounded coach context. | — |
| [backend/sources/kb_metadata.py](../../backend/sources/kb_metadata.py) | Canonical Bedrock Knowledge Base sidecar payloads for course materials. | — |
| [backend/sources/library.py](../../backend/sources/library.py) | Source ingestion, course-material synchronization, and compatibility re-exports. | SourceImportError, LectureNotesSyncResult, SharedCourseItem, _SharedCatalogMemo, shared_course_catalog_scope, CourseMaterialSyncCoordinator, _ReadableHTML, _SafeRedirectHandler |
| [backend/sources/projection.py](../../backend/sources/projection.py) | Resolve notebook source bytes and image inputs across storage adapters. | — |
| [backend/specialists/__init__.py](../../backend/specialists/__init__.py) | Server-owned specialist routing for Q&A, Coaching, and Formative Review. | — |
| [backend/specialists/review_orchestration.py](../../backend/specialists/review_orchestration.py) | Review Agent orchestration: incremental Haiku vs deep Sonnet. | — |
| [backend/specialists/routing.py](../../backend/specialists/routing.py) | Server-owned specialist selection for mock/offline fallback. | — |
| [backend/student_journey.py](../../backend/student_journey.py) | Backward-compatible Thinking Path façade. | — |
| [backend/student_store.py](../../backend/student_store.py) | Student persistence shared by FastAPI, Streamlit, and DSQL. | MessagePageCursorError, MessagePageRevisionConflictError, StudentStore |
| [backend/student_support.py](../../backend/student_support.py) | No module docstring; inspect source. | SupportMode |
| [backend/title_service.py](../../backend/title_service.py) | Concise notebook-title generation without an additional model request. | NotebookTitleService |
| [backend/turn_perf.py](../../backend/turn_perf.py) | Privacy-safe per-request latency and context instrumentation. | CoachTurnPerf |
| [backend/workflow.py](../../backend/workflow.py) | Local, typed critical-thinking workflow with an optional LangGraph runtime. | AssessmentProvider, CoachWorkflow |
| [backend/workflow_contract.py](../../backend/workflow_contract.py) | Shared identity and validation for the research learning-workflow contract. | — |
| [backend/workspace_service.py](../../backend/workspace_service.py) | Application service for notebook, history, source, and preference CRUD. | SourceContent, TranscriptExport, WorkspaceService |
| [ui/__init__.py](../../ui/__init__.py) | Streamlit presentation-layer modules for Co-design Chatbot. | — |
| [ui/assets/__init__.py](../../ui/assets/__init__.py) | Static UI assets loaded by the Streamlit presentation layer. | — |
| [ui/auth/__init__.py](../../ui/auth/__init__.py) | Streamlit authentication helpers that stay independent of panel code. | — |
| [ui/auth/cookies.py](../../ui/auth/cookies.py) | Read browser cookies without coupling authentication to runtime services. | — |
| [ui/auth_gate.py](../../ui/auth_gate.py) | Signed-out shell and Cognito cookie-session login gate for Streamlit. | — |
| [ui/chat.py](../../ui/chat.py) | Backward-compatible alias for :mod:`ui.panels.chat`. | — |
| [ui/coach_welcome.py](../../ui/coach_welcome.py) | Shared coach welcome copy seeded into new notebook chat history. | _MessageStore |
| [ui/column_resize.py](../../ui/column_resize.py) | Compatibility shim — prefer ``ui.layout.column_resize``. | — |
| [ui/components.py](../../ui/components.py) | Reusable presentation helpers for the Streamlit UI. | — |
| [ui/composer_layout.py](../../ui/composer_layout.py) | Compatibility shim — prefer ``ui.layout.composer_layout``. | — |
| [ui/constants.py](../../ui/constants.py) | Shared Streamlit UI constants. | — |
| [ui/html_embed.py](../../ui/html_embed.py) | Helpers for embedding browser scripts through Streamlit components. | — |
| [ui/layout/__init__.py](../../ui/layout/__init__.py) | Streamlit layout helpers that inject browser-side DOM/CSS adjustments. | — |
| [ui/layout/chat_scroll.py](../../ui/layout/chat_scroll.py) | Bounded chat-transcript scroll policy for notebook paging and Send. | — |
| [ui/layout/column_resize.py](../../ui/layout/column_resize.py) | Desktop sizing for the Gemini-style three-region workspace. | — |
| [ui/layout/composer_layout.py](../../ui/layout/composer_layout.py) | Keep the chat composer in a Cursor-style card with a footer control row. | — |
| [ui/layout/sources_scroll.py](../../ui/layout/sources_scroll.py) | Keep the Sources folder list scrollable inside the Library destination. | — |
| [ui/layout/studio_scroll.py](../../ui/layout/studio_scroll.py) | Keep Journey and Review scrollable inside the Thinking Path panel. | — |
| [ui/layout/user_message_edit_layout.py](../../ui/layout/user_message_edit_layout.py) | Edit-bubble sizing tokens shared with the chat stylesheet. | — |
| [ui/menu_popovers.py](../../ui/menu_popovers.py) | Helpers to remount select-only Streamlit popovers so they close after a pick. | — |
| [ui/notebooks.py](../../ui/notebooks.py) | Notebook library dialogs without folder management. | — |
| [ui/panels/__init__.py](../../ui/panels/__init__.py) | Streamlit panel implementations for chat, sources, and Journey/Review. | — |
| [ui/panels/chat.py](../../ui/panels/chat.py) | Discussion panel, message rendering, and composer handling. | CoachTurnStreamError |
| [ui/panels/nav.py](../../ui/panels/nav.py) | Gemini-style left chat navigation rail. | — |
| [ui/panels/search.py](../../ui/panels/search.py) | Center-pane chat search (Gemini-style). | — |
| [ui/panels/sources.py](../../ui/panels/sources.py) | Sources panel, dialogs, and source display helpers. | — |
| [ui/panels/studio.py](../../ui/panels/studio.py) | Thinking Path studio panel and learning review. | DeepReviewControlView |
| [ui/professor.py](../../ui/professor.py) | Lecturer-facing learning analytics rendered solely from the FastAPI client. | — |
| [ui/profile.py](../../ui/profile.py) | Profile settings popover for local appearance, coaching style, and logout. | — |
| [ui/rename.py](../../ui/rename.py) | Shared Enter-only rename helpers for notebooks, sources, and the top bar. | — |
| [ui/retry_keys.py](../../ui/retry_keys.py) | Bounded, privacy-preserving UI retry keys for coach submissions. | — |
| [ui/run_memo.py](../../ui/run_memo.py) | Page-run memo for repeated workspace reads inside one Streamlit script run. | — |
| [ui/runtime.py](../../ui/runtime.py) | Backward-compatible alias for :mod:`ui.services.runtime`. | — |
| [ui/services/__init__.py](../../ui/services/__init__.py) | Presentation-neutral cached runtime facades for Streamlit. | — |
| [ui/services/runtime.py](../../ui/services/runtime.py) | Cached runtime resources shared across Streamlit UI modules. | PendingSourceUpload, SourceUploadCoordinator, _NonPersistentCookies, WorkspaceFacade |
| [ui/session.py](../../ui/session.py) | Notebook session initialization and lifecycle helpers. | — |
| [ui/settings.py](../../ui/settings.py) | Preference persistence callbacks shared by the profile menu. | — |
| [ui/sources.py](../../ui/sources.py) | Backward-compatible alias for :mod:`ui.panels.sources`. | — |
| [ui/sources_scroll.py](../../ui/sources_scroll.py) | Compatibility shim — prefer ``ui.layout.sources_scroll``. | — |
| [ui/studio.py](../../ui/studio.py) | Backward-compatible alias for :mod:`ui.panels.studio`. | — |
| [ui/theme.py](../../ui/theme.py) | Theme CSS injection and appearance overrides for the Streamlit UI. | — |
| [ui/toasts.py](../../ui/toasts.py) | Browser corner toasts for short-lived Streamlit notifications. | — |
| [ui/topbar.py](../../ui/topbar.py) | Nonvisual workspace preparation retained from the retired top bar. | — |
| [ui/workspace.py](../../ui/workspace.py) | Gemini-style notebook workspace layout. | — |
| [agentcore_runtime/__init__.py](../../agentcore_runtime/__init__.py) | Canonical AgentCore coaching runtime for the companion application. | — |
| [agentcore_runtime/contracts/__init__.py](../../agentcore_runtime/contracts/__init__.py) | Runtime structured-output contracts. Canonical models live in ``models.py``. | — |
| [agentcore_runtime/contracts/coach_turn.py](../../agentcore_runtime/contracts/coach_turn.py) | Coach-turn structured-output contract. | — |
| [agentcore_runtime/contracts/qa_turn.py](../../agentcore_runtime/contracts/qa_turn.py) | Q&A structured-output contract. | — |
| [agentcore_runtime/contracts/review_turn.py](../../agentcore_runtime/contracts/review_turn.py) | Formative Review structured-output contract. | — |
| [agentcore_runtime/contracts/router_turn.py](../../agentcore_runtime/contracts/router_turn.py) | Router structured-output contract. | — |
| [agentcore_runtime/contracts/stage_judge_turn.py](../../agentcore_runtime/contracts/stage_judge_turn.py) | Stage Judge structured-output contract. | — |
| [agentcore_runtime/guardrails.py](../../agentcore_runtime/guardrails.py) | Provider-neutral Bedrock ApplyGuardrail helpers for Mantle/Luna. | — |
| [agentcore_runtime/main.py](../../agentcore_runtime/main.py) | Production AgentCore entrypoint for companion specialist invokes. | — |
| [agentcore_runtime/model.py](../../agentcore_runtime/model.py) | Fail-closed AgentCore model factory. | RuntimeModelError, RuntimeModelConfig, RuntimeModelRegistry |
| [agentcore_runtime/models.py](../../agentcore_runtime/models.py) | Focused coach_turn wire schema for the AgentCore harness. | FacioneScoresOutput, CitationOutput, AssessmentOutput, CoachTurnOutput, QATurnOutput, FastChatContractError, FastChatTurnOutput, ReviewTurnOutput, DeepReviewStageFeedback, DeepReviewTurnOutput, RouterOutput, StageJudgeOutput |
| [agentcore_runtime/prompt_cache.py](../../agentcore_runtime/prompt_cache.py) | Fast-chat pedagogical prefix cache helpers for pinned Strands 1.52.0. | — |
| [agentcore_runtime/prompts/__init__.py](../../agentcore_runtime/prompts/__init__.py) | Canonical AgentCore pedagogical prompts. This package does not import backend. | — |
| [agentcore_runtime/prompts/loader.py](../../agentcore_runtime/prompts/loader.py) | UTF-8 loader for canonical AgentCore specialist and stage prompts. | PromptLoadError |
| [agentcore_runtime/router.py](../../agentcore_runtime/router.py) | Haiku router helpers. Classification only; FastAPI owns authorization. | — |
| [agentcore_runtime/specialists/__init__.py](../../agentcore_runtime/specialists/__init__.py) | Deterministic specialist prompt builders for one AgentCore runtime. | — |
| [agentcore_runtime/specialists/coaching.py](../../agentcore_runtime/specialists/coaching.py) | Coaching specialist: Socratic Thinking Path pedagogy. | — |
| [agentcore_runtime/specialists/fast_chat.py](../../agentcore_runtime/specialists/fast_chat.py) | Combined fast-chat specialist: one Haiku call for Coaching or Q&A. | — |
| [agentcore_runtime/specialists/qa.py](../../agentcore_runtime/specialists/qa.py) | Q&A specialist: grounded course answers over pre-retrieved evidence. | — |
| [agentcore_runtime/specialists/review.py](../../agentcore_runtime/specialists/review.py) | Formative Review specialist: incremental Haiku or deep Sonnet. | — |
| [agentcore_runtime/specialists/routing.py](../../agentcore_runtime/specialists/routing.py) | Deterministic specialist phase selection inside the AgentCore runtime. | — |
| [agentcore_runtime/stage_judge.py](../../agentcore_runtime/stage_judge.py) | Compatibility wrapper. Deep Review replaced the Stage Judge authority. | — |
| [agentcore_runtime/structured_coach.py](../../agentcore_runtime/structured_coach.py) | Structured coach_turn helpers for the production AgentCore harness. | ModelRetryPolicy, CoachTurnExtractionError |
| [agentcore_runtime/system_prompt_budget.py](../../agentcore_runtime/system_prompt_budget.py) | Shared AgentCore system-prompt text for FastAPI token estimation. | — |

## Pinned dependency manifests

These are repository pins, not claims about the newest package versions or the packages installed on AWS.

### requirements.txt

Source: [requirements.txt](../../requirements.txt)

```text
streamlit==1.60.0
Authlib==1.7.2
joserfc==1.7.4
streamlit-pdf==1.0.8
openai==2.46.0
python-dotenv==1.2.2
fastapi==0.139.2
uvicorn==0.35.0
httpx==0.28.1
langgraph==1.0.10
pypdf==6.15.0
pymupdf==1.28.0
Pillow==12.3.0
python-docx==1.2.0
python-pptx==1.0.2
openpyxl==3.1.5
matplotlib==3.11.1

# Production AWS adapters (lazy-imported; not required for local mock tests)
# 1.43+ is required for bedrock-agentcore, InvokeHarness, and aws login CRT creds.
boto3==1.43.35
botocore[crt]==1.43.35
psycopg[binary]==3.2.9

# This file is the production image install surface (see Dockerfile). Test and
# lint tooling belongs in requirements-dev.txt so it is not shipped to EC2.
```

### requirements-dev.txt

Source: [requirements-dev.txt](../../requirements-dev.txt)

```text
# Development and CI surface: runtime pins plus test/lint tooling. The
# production image installs requirements.txt only.
-r requirements.txt
pytest==9.0.3
ruff==0.11.13
```

### agentcore_runtime/requirements.txt

Source: [agentcore_runtime/requirements.txt](../../agentcore_runtime/requirements.txt)

```text
# AgentCore DEFAULT coaching runtime.
# Exact pins were pip-installed and API-checked in a clean CPython 3.12.10
# venv on 2026-08-16 against the public PyPI index. Companion pytest does
# not install this stack; GitHub job agentcore-runtime-compatibility does.
#
# bedrock-agentcore 1.21.0 requires pydantic<2.41.3,>=2.0.0.
# pydantic==2.13.4 is the compatible exact pin used by this runtime.
strands-agents==1.52.0
bedrock-agentcore==1.21.0
pydantic==2.13.4
# Mantle Responses extra kept for historical Luna runtime versions.
# Current DEFAULT Haiku/Sonnet uses BedrockModel only; the extra is unused
# on that path. The parser in model.py skips extra markers; keep the exact
# strands-agents pin above.
strands-agents[openai]==1.52.0
```
