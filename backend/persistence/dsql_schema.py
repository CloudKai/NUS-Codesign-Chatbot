"""Aurora DSQL schema for the production data model.

Tables:

    users
     └── notebooks
          ├── messages
          ├── sources
          └── research_observations
               ├── research_reviews
               └── research_adjudications

    oauth_login_states  (pre-auth, transient)
    research_access_events  (append-only attributable audit)
    system_metadata  (workflow-contract readiness)

Cognito owns the browser session (HttpOnly refresh + ID-token cookies). There
is no ``app_sessions`` table.

Differences from local SQLite:

- No FOREIGN KEY constraints (unsupported in Aurora DSQL; enforce in app code).
- No ON DELETE CASCADE (delete child rows explicitly in the store).
- JSON-shaped fields remain TEXT.
- UUID primary keys stay application-generated TEXT ids.
- Secondary indexes use ``CREATE INDEX ASYNC`` / ``CREATE UNIQUE INDEX ASYNC``.
- Admin bootstrap waits for each ASYNC index job.
- Fresh ``notebooks`` / ``messages`` include revision columns
  (``notebooks.conversation_revision`` plus message
  ``conversation_revision``, ``previous_message_id``,
  ``superseded_at_revision``). Existing clusters get missing columns only via
  catalog-driven ``scripts/init_dsql.py`` ALTERs — never at app startup.

Do not auto-create or destroy DSQL clusters from application startup. Schema
application is explicit via ``scripts/init_dsql.py`` (admin only). Runtime
``DsqlStudentStore`` must never issue CREATE/ALTER/INDEX DDL.
"""

from __future__ import annotations

from backend.persistence.dsql_connection import split_sql_statements

DSQL_SCHEMA = """
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
"""


# Child table dependency order for explicit runtime deletion (no FK cascade).
# Predicates live in student_store.NOTEBOOK_CHILD_DELETE_PLAN because reviews
# and adjudications are linked through research_observations.
NOTEBOOK_CHILD_TABLES = (
    "research_adjudications",
    "research_reviews",
    "research_access_events",
    "research_observations",
    "messages",
    "sources",
)

# Backwards-compatible alias used by older call sites during the refactor.
THREAD_CHILD_TABLES = NOTEBOOK_CHILD_TABLES

# Printed by admin bootstrap; map the EC2 instance role to this DB user in IAM.
# Do not embed account ARNs in Git.
RUNTIME_ROLE_NAME = "co_design_app"

RUNTIME_GRANT_SQL = """
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO co_design_app;
""".strip()


def iter_dsql_ddl_statements() -> list[str]:
    """Return individual DDL statements for one-per-transaction admin bootstrap."""
    statements: list[str] = []
    for statement in split_sql_statements(DSQL_SCHEMA):
        cleaned = statement.strip()
        if cleaned:
            statements.append(cleaned)
    return statements
