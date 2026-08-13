"""SQLite schema applied by the local ``StudentStore`` initializer."""

SQLITE_SCHEMA = """
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
    current_stage TEXT NOT NULL DEFAULT 'focus',
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
"""

# DSQL lacks FK cascade, so its adapter deletes these child tables explicitly.
NOTEBOOK_CHILD_TABLES = ("messages", "sources")
