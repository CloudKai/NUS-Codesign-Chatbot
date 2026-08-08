"""Aurora DSQL schema for the production data model.

Tables:

    users
     └── notebooks
          ├── messages
          └── sources

    oauth_login_states  (pre-auth, transient)

Cognito owns the browser session (HttpOnly refresh + ID-token cookies). There
is no ``app_sessions`` table.

Differences from local SQLite:

- No FOREIGN KEY constraints (unsupported in Aurora DSQL; enforce in app code).
- No ON DELETE CASCADE (delete child rows explicitly in the store).
- JSON-shaped fields remain TEXT.
- UUID primary keys stay application-generated TEXT ids.
- Secondary indexes use ``CREATE INDEX ASYNC`` / ``CREATE UNIQUE INDEX ASYNC``.
- Admin bootstrap waits for each ASYNC index job.

Do not auto-create or destroy DSQL clusters from application startup. Schema
application is explicit via ``scripts/init_dsql.py`` (admin only). Runtime
``DsqlStudentStore`` must never issue CREATE/ALTER/INDEX DDL.
"""

from __future__ import annotations

from backend.persistence.dsql_connection import split_sql_statements

DSQL_SCHEMA = """
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
    current_stage TEXT NOT NULL DEFAULT 'focus',
    progress_text TEXT NOT NULL DEFAULT '{}',
    settings_text TEXT NOT NULL DEFAULT '{}',
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
    created_at TEXT NOT NULL
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
"""


# Child tables deleted explicitly when a notebook is removed (no FK cascade).
NOTEBOOK_CHILD_TABLES = ("messages", "sources")

# Backwards-compatible alias used by older call sites during the refactor.
THREAD_CHILD_TABLES = NOTEBOOK_CHILD_TABLES

# Printed by admin bootstrap; map the EC2 instance role to this DB user in IAM.
# Do not embed account ARNs in Git.
RUNTIME_ROLE_NAME = "co_design_app"

RUNTIME_GRANT_SQL = """
GRANT USAGE ON SCHEMA public TO co_design_app;
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
